"""Agent Teams 多 Agent 团队:多名角色化成员并行作业,负责人汇总产出。

流程:
  1. 执行:每位成员(独立子 Agent)按自己的角色视角处理任务,并行进行;
  2. 汇总:负责人(编排器)读取所有成员产出,综合成最终成果。

成员可配置各自的模型/工具范围/系统提示,配置放 config.yaml 的 teams 段。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..llm import ChatClient, LLMError, client_from_config
from ..types import Usage
from ..tools import ToolRegistry
from .permissions import PermissionPolicy
from .subagent import SubAgent

# 每位成员产出在负责人汇总 prompt 中的字符上限:多成员产出拼起来很容易超出模型
# 上下文/让模型返回空响应,先截断再汇总。
LEADER_MEMBER_MAX = 3000


@dataclass
class TeamMember:
    name: str
    role: str
    model: Optional[str] = None
    allow_tools: Optional[list[str]] = None
    system_prompt: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TeamMember":
        return cls(name=d.get("name", "成员"),
                   role=d.get("role", ""),
                   model=d.get("model"),
                   allow_tools=d.get("allow_tools"),
                   system_prompt=d.get("system_prompt", ""))

    def role_prompt(self) -> str:
        base = f"你是团队中的「{self.name}」,担任{self.role}。从你的专业视角处理任务。"
        return base + (("\n额外要求:\n" + self.system_prompt) if self.system_prompt else "")


@dataclass
class TeamResult:
    final_text: str
    success: bool = False
    members: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    error: str = ""
    saved_to: str = ""  # 负责人汇总成果写入的文件路径(空表示未写)


def _member_digest(task: str, outputs: list[dict[str, Any]]) -> str:
    """负责人汇总失败时的兜底:把各成员产出整理成可读摘要返回,避免用户只看到一句错误。"""
    blocks = [f"原始任务: {task}", ""]
    for o in outputs:
        state = "成功" if o["success"] else f"失败({o['error']})"
        text = o["text"] or "(无输出)"
        if len(text) > LEADER_MEMBER_MAX:
            text = text[:LEADER_MEMBER_MAX] + f"\n…(已截断,共 {len(text)} 字符)"
        blocks.append(f"## 成员 {o['name']}({o['role']}) - {state}\n{text}")
    return "\n\n".join(blocks)


class Team:
    def __init__(
        self,
        name: str,
        members: list[TeamMember],
        config,
        workspace: Path,
        client: ChatClient,
        registry: ToolRegistry,
        *,
        leader_prompt: str = "",
        permissions: Optional[PermissionPolicy] = None,
        ui=None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.name = name
        self.members = members
        self.config = config
        self.workspace = workspace.resolve()
        self.client = client
        self.registry = registry
        self.permissions = permissions
        self.ui = ui
        # 共享停止信号:Web「停止生成」置位后成员子 Agent 尽快退出
        self.stop_event = stop_event
        self.leader_prompt = leader_prompt or (
            "你是团队负责人,负责把成员产出整合成一份完整、可执行、条理清晰的最终成果。"
            "成员产出可能有冲突或冗余,请去重、纠错并提炼。")

    def run(self, task: str) -> TeamResult:
        if not self.members:
            return TeamResult("", success=False, error="团队没有成员")
        ui = self.ui
        if ui:
            ui.event("status", {"message": f"团队 {self.name} 开始并行作业({len(self.members)} 名成员)…"})

        member_outputs: list[dict[str, Any]] = []
        usage = Usage()

        def one(m: TeamMember) -> dict[str, Any]:
            client = self.client
            if m.model and m.model != self.config.provider.get("model"):
                client = client_from_config(self.config)
                client.model = m.model
            if ui:
                ui.event("status", {"message": f"成员「{m.name}」({m.role}) 开始处理…"})
            # 成员静默执行(ui=None):不把逐 token 的推理/工具过程实时泄漏到聊天,
            # 否则多名成员并行会把各自的"第 N 轮推理"等事件交织在一起,阅读顺序混乱。
            # 只在开始/结束时各发一条状态,最终成果由负责人统一汇总后一次性给出。
            sub = SubAgent(self.config, self.workspace, client, self.registry,
                           name=m.name, system_prompt=m.role_prompt(),
                           allow_tools=m.allow_tools,
                           permissions=self.permissions, ui=None,
                           stop_event=self.stop_event)
            r = sub.run(task)
            if ui:
                state = "成功" if r.success else f"失败({r.error})"
                tail = (r.text or "").strip().replace("\n", " ")
                if len(tail) > 50:
                    tail = tail[:50] + "…"
                ui.event("status", {"message": f"成员「{m.name}」({m.role}) {state}: {tail}"})
            return {"name": m.name, "role": m.role, "text": r.text,
                    "success": r.success, "usage": r.usage, "error": r.error}

        with ThreadPoolExecutor(max_workers=max(2, len(self.members))) as pool:
            futs = [pool.submit(one, m) for m in self.members]
            for f in as_completed(futs):
                out = f.result()
                member_outputs.append(out)
                usage += out["usage"]
        member_outputs.sort(key=lambda o: [m.name for m in self.members].index(o["name"]))

        # 用户点了「停止生成」:跳过汇总、不写汇总文档,兜底展示成员已有产出
        if self.stop_event is not None and self.stop_event.is_set():
            result = TeamResult(final_text=_member_digest(task, member_outputs),
                                success=False,
                                members=[{k: v for k, v in o.items() if k != "usage"}
                                         for o in member_outputs],
                                usage=usage,
                                error="用户已停止生成,未完成最终汇总。")
            if ui:
                ui.event("status", {"message": f"团队 {self.name} 已停止"})
                ui.event("turn_end", {"final_text": result.final_text, "success": False,
                                      "iterations": len(member_outputs),
                                      "usage": {"prompt_tokens": usage.prompt_tokens,
                                                "completion_tokens": usage.completion_tokens},
                                      "error": result.error})
            return result

        # 负责人汇总:prompt 已截断,空响应/异常重试一次(多为瞬时),仍失败则兜底展示成员产出
        if ui:
            ui.event("status", {"message": f"负责人正在汇总 {len(member_outputs)} 份成员产出…"})
        summary_prompt = self._leader_prompt(task, member_outputs)
        final_text, error = "", ""
        for attempt in range(2):
            try:
                resp = self.client.chat([{"role": "user", "content": summary_prompt}],
                                        max_tokens=2048)
                usage += resp.usage
                final_text = resp.content or ""
            except LLMError as e:
                error = str(e)
                final_text = ""
            if final_text.strip():
                error = ""
                break
            if attempt == 0:
                if not error:
                    error = "模型返回了空响应"
                continue
        success = bool(final_text.strip())
        saved_to = ""
        if not success:
            final_text = _member_digest(task, member_outputs)
            error = f"负责人汇总失败({error or '模型返回了空响应'}),已改为展示成员产出原文。"
        else:
            # 负责人汇总成果统一写入工作区一份文档,作为唯一权威交付物
            # (成员已被配置为只输出文本、不各自写文件)。
            out = self.workspace / f"{self.name}_汇总.md"
            out.write_text(final_text, encoding="utf-8")
            saved_to = str(out)

        result = TeamResult(final_text=final_text, success=success, saved_to=saved_to,
                            members=[{k: v for k, v in o.items() if k != "usage"}
                                     for o in member_outputs],
                            usage=usage, error=error)
        if ui:
            ui.event("status", {"message": f"团队 {self.name} 完成"})
            ui.event("turn_end", {"final_text": result.final_text,
                                  "success": result.success,
                                  "iterations": len(member_outputs),
                                  "usage": {"prompt_tokens": usage.prompt_tokens,
                                            "completion_tokens": usage.completion_tokens},
                                  "error": result.error})
        return result

    def _leader_prompt(self, task: str, outputs: list[dict[str, Any]]) -> str:
        blocks = []
        for o in outputs:
            state = "成功" if o["success"] else f"失败({o['error']})"
            text = o["text"] or ""
            if len(text) > LEADER_MEMBER_MAX:
                text = text[:LEADER_MEMBER_MAX] + f"\n…(已截断,共 {len(text)} 字符)"
            blocks.append(f"【成员 {o['name']}({o['role']})-{state}】\n{text}")
        body = "\n\n".join(blocks)
        return f"{self.leader_prompt}\n\n原始任务:\n{task}\n\n成员产出:\n{body}\n\n请输出最终成果:"
