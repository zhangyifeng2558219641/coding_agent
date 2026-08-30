"""Agent 自主任务循环(ReAct 范式):想 → 调工具 → 看结果 → 再决策,直至任务完成。

重要逻辑(全部自行实现):
- 对话历史与上下文管理(经 History 组装/压缩);
- 工具调用解析(来自 LLM 原生 tool calling);
- 循环终止条件:无工具调用 / 达到最大迭代 / 预算耗尽 / 用户中断;
- 错误处理:单工具失败不中断整个任务,LLM 失败重试后兜底;
- 事件向 UI 派发(CLI/Web 共用一套 UISink 接口)。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..llm import ChatClient, LLMError, StreamEvent
from ..llm.history import History
from ..prompts import base_system_prompt
from ..types import FinalResult, ToolCall, ToolResult, Usage
from ..tools import ToolContext, ToolRegistry
from .memory import MemoryStore
from .permissions import Decision, PermissionPolicy


class UISink:
    """UI 回调接口:CLI 与 Web 各自实现。event() 是唯一事件通道。"""

    def event(self, type: str, data: dict[str, Any]) -> None:
        pass

    def ask(self, question: str) -> bool:
        """交互确认;无交互能力时返回 False(默认拒绝)。"""
        return False

    def choose(self, prompt: str, options: list[str]) -> Optional[int]:
        """让用户在选项中挑选,返回 0-based 索引。

        None:当前 UI 不支持交互选择(调用方应自行兜底,如恢复最新);
        -1:用户取消;其余为选中索引。
        """
        return None


@dataclass
class AgentOptions:
    max_iterations: int = 30
    max_tool_output: int = 30000
    budget_tokens: int = 64000
    system_prompt: str = ""
    # 允许/禁止的工具白名单(用于子 Agent 裁剪能力)
    allow_tools: Optional[list[str]] = None


class AgentLoop:
    def __init__(
        self,
        config,
        workspace: Path,
        client: ChatClient,
        registry: ToolRegistry,
        *,
        permissions: Optional[PermissionPolicy] = None,
        memory: Optional[MemoryStore] = None,
        history: Optional[History] = None,
        ui: Optional[UISink] = None,
        hooks=None,
        options: Optional[AgentOptions] = None,
    ):
        self.config = config
        self.workspace = workspace.resolve()
        self.client = client
        self.registry = registry
        self.permissions = permissions or PermissionPolicy(config.permissions, self.workspace)
        self.memory = memory
        self.ui = ui or UISink()
        self.hooks = hooks
        if options is None:
            options = AgentOptions(
                max_iterations=config.agent.get("max_iterations", 30),
                budget_tokens=config.context.get("budget_tokens", 64000),
                max_tool_output=config.context.get("max_tool_output", 30000),
            )
        self.options = options
        self.history = history or History(
            budget_tokens=self.options.budget_tokens,
            max_tool_output=self.options.max_tool_output,
        )
        # 组装基础 system(子 Agent 可覆盖)
        if self.options.system_prompt:
            self.history.add_system_part("base", self.options.system_prompt)
        else:
            self.history.add_system_part("base", base_system_prompt(self.workspace))
        if memory and memory.enabled:
            self.history.add_system_part("memory", memory.load_all())
        self._usage = Usage()
        self._tool_history: list[dict[str, Any]] = []
        self._interrupted = False
        self._compact_count = 0

    # ------------------------------------------------------------------ 公共
    @property
    def usage(self) -> Usage:
        return self._usage

    @property
    def tool_history(self) -> list[dict[str, Any]]:
        return self._tool_history

    @property
    def conversation_messages(self) -> list[dict[str, Any]]:
        """会话消息(不含 system),供持久化/展示。"""
        return list(self.history.messages)

    def interrupt(self) -> None:
        """供 UI 在用户 Ctrl+C 时调用,中断当前轮。"""
        self._interrupted = True

    # ------------------------------------------------------------------ 主循环
    def run(self, user_text: str) -> FinalResult:
        start = time.monotonic()
        self._interrupted = False
        if user_text.strip():
            self.history.append({"role": "user", "content": user_text})

        self._fire("agent_start")
        final_text = ""
        last_error = ""
        iterations = 0

        try:
            while iterations < self.options.max_iterations:
                if self._interrupted:
                    last_error = "用户中断"
                    break

                # 预算检查:超限自动压缩
                if self.history.should_compact():
                    self._compact()

                iterations += 1
                self.ui.event("status", {"message": f"第 {iterations} 轮推理…"})

                text_parts: list[str] = []
                calls: list[ToolCall] = []
                try:
                    events = self.client.chat_stream(self.history.to_api(),
                                                     self._schemas())
                    for ev in events:
                        if ev.type == "text":
                            text_parts.append(ev.text)
                            self.ui.event("text", {"delta": ev.text})
                        elif ev.type == "tool_calls":
                            calls = ev.calls
                        elif ev.type in ("usage", "finish"):
                            self._usage += ev.usage
                        elif ev.type == "error":
                            last_error = ev.message
                except LLMError as e:
                    last_error = str(e)
                    break

                text = "".join(text_parts)
                final_text += text

                if not calls:
                    # 没有工具调用 → 输出最终答复,循环终止
                    self.history.append({"role": "assistant", "content": text})
                    break

                # 有工具调用:记录 assistant 消息,逐条执行
                self.history.append({"role": "assistant", "content": text,
                                     "tool_calls": [c.to_dict() for c in calls]})
                for call in calls:
                    if self._interrupted:
                        last_error = "用户中断"
                        break
                    result = self._execute_tool(call)
                    self.history.append(result.to_message())
                if not calls:
                    break

                # 工具被全部拒绝/中断时避免死循环
                if iterations >= self.options.max_iterations:
                    last_error = f"达到最大迭代次数 {self.options.max_iterations}"
                    break
            else:
                last_error = f"达到最大迭代次数 {self.options.max_iterations}"
        except KeyboardInterrupt:
            last_error = "用户中断"
            self._interrupted = True

        self._fire("agent_end")

        success = not last_error and bool(final_text.strip())
        result = FinalResult(
            text=final_text,
            success=success,
            iterations=iterations,
            usage=self._usage,
            tool_history=list(self._tool_history),
            error=last_error,
            elapsed=time.monotonic() - start,
        )
        self.ui.event("turn_end", {
            "final_text": result.text,
            "success": result.success,
            "iterations": result.iterations,
            "usage": {"prompt_tokens": result.usage.prompt_tokens,
                      "completion_tokens": result.usage.completion_tokens},
            "error": result.error,
            "elapsed": round(result.elapsed, 2),
        })
        return result

    # ------------------------------------------------------------------ 工具执行
    def _schemas(self) -> list[dict[str, Any]]:
        if self.options.allow_tools is not None:
            return [t.to_openai_function() for t in self.registry.all()
                    if t.name in self.options.allow_tools]
        return self.registry.schemas()

    def _execute_tool(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get_ci(call.name)
        if tool is None:
            return ToolResult(name=call.name, call_id=call.id, success=False,
                              error=f"未知工具: {call.name}")

        # 权限裁决
        decision = self.permissions.decide(call.name, call.arguments, tool)
        if decision.decision == Decision.DENY:
            self.ui.event("tool_call", {"id": call.id, "name": call.name,
                                        "arguments": call.arguments,
                                        "status": "denied", "reason": decision.reason})
            self._tool_history.append({"name": call.name, "status": "denied"})
            return ToolResult(name=call.name, call_id=call.id, success=False,
                              error=f"权限拒绝: {decision.reason}")
        if decision.decision == Decision.ASK:
            question = f"允许调用工具 {call.name}({decision.reason})?\n参数: {json.dumps(call.arguments, ensure_ascii=False)[:300]}"
            ok = self.ui.ask(question)
            self.ui.event("tool_call", {"id": call.id, "name": call.name,
                                        "arguments": call.arguments,
                                        "status": "allowed" if ok else "declined"})
            if not ok:
                self._tool_history.append({"name": call.name, "status": "declined"})
                return ToolResult(name=call.name, call_id=call.id, success=False,
                                  error="用户拒绝本次工具调用")
        else:
            self.ui.event("tool_call", {"id": call.id, "name": call.name,
                                        "arguments": call.arguments, "status": "auto"})

        # 生命周期钩子:pre_tool_call(可 veto)
        if self.hooks:
            if not self.hooks.fire_pre_tool(call.name, call.arguments, tool):
                self._tool_history.append({"name": call.name, "status": "hook-veto"})
                return ToolResult(name=call.name, call_id=call.id, success=False,
                                  error="被 pre_tool_call 钩子拦截")

        ctx = ToolContext(
            workspace=self.workspace,
            cwd=self.workspace,
            config=self.config,
            permissions=self.permissions,
            memory=self.memory,
            llm=self.client,
            registry=self.registry,
            ask=self.ui.ask,
            emit=lambda t, d: self.ui.event(t, d),
        )

        try:
            result = tool.run(ctx, **call.arguments)
        except Exception as e:
            result = ToolResult(name=call.name, call_id=call.id, success=False,
                                error=f"工具异常: {type(e).__name__}: {e}")
        # 工具自身创建的 ToolResult 通常不带 call_id,必须补上,
        # 否则发给模型的 tool 消息 tool_call_id 为空,网关会 400 拒绝
        result.call_id = call.id

        if self.hooks:
            self.hooks.fire_post_tool(call.name, result)
        self._tool_history.append({"name": call.name, "status": "ok" if result.success else "error"})
        self.ui.event("tool_result", {
            "id": call.id, "name": call.name,
            "success": result.success, "output": result.content[:1500],
            "error": result.error,
        })
        return result

    # ------------------------------------------------------------------ 压缩
    def _compact(self) -> None:
        self.ui.event("status", {"message": "上下文超预算,正在压缩历史…"})
        ok = self.history.compact(self._summarize)
        self._compact_count += 1 if ok else 0
        if ok:
            self.ui.event("compact", {"summary": self.history.summary})

    def _summarize(self, instruction: str) -> str:
        resp = self.client.chat([{"role": "user", "content": instruction}],
                                max_tokens=512, temperature=0.1)
        return resp.content

    # ------------------------------------------------------------------ 钩子
    def _fire(self, event: str) -> None:
        if self.hooks:
            try:
                self.hooks.fire(event, workspace=self.workspace)
            except Exception as e:
                self.ui.event("status", {"message": f"钩子 {event} 异常: {e}"})
