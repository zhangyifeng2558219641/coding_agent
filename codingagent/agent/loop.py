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
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from ..llm import ChatClient, LLMError, StreamEvent
from ..llm.history import History
from ..prompts import base_system_prompt
from ..types import FinalResult, ToolCall, ToolResult, Usage
from ..tools import ToolContext, ToolRegistry
from .checkpoint import CheckpointStore
from .memory import MemoryStore
from .permissions import Decision, PermissionPolicy, _is_within

# 计划模式:只读调研 + 结构化计划,供 run() 按需注入 system(不入持久化)
PLAN_MODE_PROMPT = (
    "【计划模式】你现在处于计划模式:只能进行只读调查,禁止修改/创建/删除任何文件、"
    "禁止执行有副作用的命令。请先充分调研现状,然后输出结构化实现计划:"
    "①目标 ②现状与关键发现 ③实施步骤(编号) ④涉及的文件 ⑤验证方式。"
    "计划完成后停下,等待用户批准后再执行。"
)
# 计划模式下允许的只读 shell 命令(研究用),含管道,但拒绝重定向/命令链
PLAN_READONLY_BASH = re.compile(
    r"^(git (log|status|diff|show|branch|remote|rev-parse)|ls|cat|head|tail|grep|find|wc|pwd|which|type|date)\b"
)
_PLAN_BASH_BAD = re.compile(r"[;>`]|\$\(|&&|\|\|")


class UISink:
    """UI 回调接口:CLI 与 Web 各自实现。event() 是唯一事件通道。"""

    def event(self, type: str, data: dict[str, Any]) -> None:
        pass

    def ask(self, question: str) -> bool:
        """交互确认;无交互能力时返回 False(默认拒绝)。"""
        return False

    def choose(self, prompt: str, options: list[str]) -> Optional[Union[int, str]]:
        """让用户在选项中挑选或输入自定义文本。

        None:当前 UI 不支持交互选择(调用方应自行兜底);
        -1:用户取消;
        int(>=0):选中 options[idx];
        str:用户输入的自定义文本。
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
        stop_event: Optional[threading.Event] = None,
        checkpoints: Optional[CheckpointStore] = None,
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
        self._usage = self.history.usage
        self._tool_history: list[dict[str, Any]] = []
        self._interrupted = False
        self._compact_count = 0
        # 计划模式:只读调研+出计划;写入工具被硬拦截,只读工具才暴露给模型
        self.plan_mode = False
        # 线程安全停止信号(Web「停止生成」用):interrupt() 或外部 set() 都会让主循环尽快退出
        self.stop_event = stop_event
        # 文件检查点:WriteFile/EditFile 自动快照 before/after,回合末 finalize 成一条
        self.checkpoints = checkpoints or CheckpointStore(None)

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
        """供 UI 在用户 Ctrl+C / 点击停止时调用,中断当前轮。"""
        self._interrupted = True
        if self.stop_event is not None:
            self.stop_event.set()

    # ------------------------------------------------------------------ 主循环
    def run(self, user_text: str) -> FinalResult:
        start = time.monotonic()
        self._interrupted = False
        self.checkpoints.begin_turn()
        # 按当前模式增删计划模式系统提示(system 段不入持久化,每轮自清洁)
        if self.plan_mode:
            self.history.add_system_part("plan", PLAN_MODE_PROMPT)
        else:
            self.history.remove_system_part("plan")
        if user_text.strip():
            self.history.append({"role": "user", "content": user_text})

        self._fire("agent_start")
        final_text = ""
        last_error = ""
        iterations = 0
        empty_retries = 0

        try:
            while iterations < self.options.max_iterations:
                if self._interrupted or (self.stop_event is not None and self.stop_event.is_set()):
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
                                                     self._schemas(),
                                                     stop_event=self.stop_event)
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

                text = "".join(text_parts)
                final_text += text

                # LLM 出错(网络/网关重试耗尽)→ 本回合到此为止,原因交给下方集中上报
                if last_error:
                    break

                if not calls:
                    # 没有工具调用 → 输出最终答复,循环终止
                    if not text.strip():
                        if empty_retries < 2:
                            empty_retries += 1
                            continue  # 空响应多为瞬时,重试(不写回历史)
                        last_error = "模型返回了空响应(无文本且无工具调用)"
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

        # 回合收尾:把本轮写盘的 before/after 落成检查点(所有退出路径汇合于此)
        self._finalize_checkpoint()

        # 异常结束(LLM 失败/空响应/超限/中断)一律显式上报,避免 UI 静默结束
        if last_error:
            self.ui.event("error", {"message": last_error})

        self._fire("agent_end")

        self.history.usage = self._usage  # 写回,供会话持久化/跨请求累计

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
        tools = ([t for t in self.registry.all() if t.name in self.options.allow_tools]
                 if self.options.allow_tools is not None else list(self.registry.all()))
        # 计划模式:只暴露只读工具,模型自然不会请求写操作
        if self.plan_mode:
            tools = [t for t in tools if t.read_only]
        return [t.to_openai_function() for t in tools]

    def _finalize_checkpoint(self) -> None:
        """把本回合 pending 的检查点落盘并通知 UI;失败绝不中断回合。"""
        try:
            cp = self.checkpoints.finalize()
            if cp:
                self.ui.event("checkpoint", {"seq": cp["seq"], "ts": cp["ts"],
                                             "files": sorted(cp["files"])})
        except Exception:
            pass

    def _checkpoint_relpath(self, ctx: ToolContext, raw: Any) -> Optional[str]:
        """WriteFile/EditFile 写前快照,返回工作区内相对路径;越界/敏感/自写跳过。"""
        if not raw:
            return None
        try:
            path = ctx.resolve(str(raw))
        except Exception:
            return None
        if not _is_within(path, self.workspace):
            return None
        if self.permissions._check_sensitive_path(path):
            return None
        try:
            rel = path.relative_to(self.workspace).as_posix()
        except ValueError:
            return None
        if rel == ".coding_agent" or rel.startswith(".coding_agent/"):
            return None  # 不跟踪自写文件,避免检查点套娃/泄露密钥
        self.checkpoints.snapshot_before(self.workspace, rel)
        return rel

    def _is_plan_readonly_bash(self, call: ToolCall) -> bool:
        """计划模式下判断 Bash 命令是否只读(git log/ls/cat 等),含管道可、重定向/链式不可。"""
        cmd = str(call.arguments.get("command") or "").strip()
        return bool(PLAN_READONLY_BASH.match(cmd) and not _PLAN_BASH_BAD.search(cmd))

    def _execute_tool(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get_ci(call.name)
        if tool is None:
            return ToolResult(name=call.name, call_id=call.id, success=False,
                              error=f"未知工具: {call.name}")

        # 计划模式:硬门控(与 _schemas 过滤互补,兜底模型硬要调写工具的情况)。
        # Bash 特殊放行只读命令白名单(git log/ls/cat 等),其余写工具一律拒绝。
        if self.plan_mode and not getattr(tool, "read_only", False):
            if tool.name != "Bash" or not self._is_plan_readonly_bash(call):
                self.ui.event("tool_call", {"id": call.id, "name": call.name,
                                            "arguments": call.arguments,
                                            "status": "denied",
                                            "reason": "计划模式仅允许只读操作"})
                self._tool_history.append({"name": call.name, "status": "plan-blocked"})
                return ToolResult(name=call.name, call_id=call.id, success=False,
                                  error="计划模式仅允许只读操作,已禁止本次调用")

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
            choose=self.ui.choose,
            emit=lambda t, d: self.ui.event(t, d),
        )

        # 文件写工具:写前快照(跳过越界/敏感/自写),成功写盘后快照 after
        cp_rel = None
        if call.name in ("WriteFile", "EditFile") and call.arguments.get("path"):
            cp_rel = self._checkpoint_relpath(ctx, call.arguments.get("path"))

        try:
            result = tool.run(ctx, **call.arguments)
        except Exception as e:
            result = ToolResult(name=call.name, call_id=call.id, success=False,
                                error=f"工具异常: {type(e).__name__}: {e}")
        if cp_rel is not None:
            if result.success:
                self.checkpoints.snapshot_after(self.workspace, cp_rel)
            else:
                self.checkpoints.discard(cp_rel)  # 写失败不记录
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
