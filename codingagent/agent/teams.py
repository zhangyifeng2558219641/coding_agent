"""Agent Teams 多 Agent 团队:多名角色化成员并行作业,负责人汇总产出。

流程:
  1. 执行:每位成员(独立子 Agent)按自己的角色视角处理任务,并行进行;
  2. 汇总:负责人(编排器)读取所有成员产出,综合成最终成果。

成员可配置各自的模型/工具范围/系统提示,配置放 config.yaml 的 teams 段。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..llm import ChatClient, LLMError, client_from_config
from ..types import Usage
from ..tools import ToolRegistry
from .permissions import PermissionPolicy
from .subagent import SubAgent


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
    ):
        self.name = name
        self.members = members
        self.config = config
        self.workspace = workspace.resolve()
        self.client = client
        self.registry = registry
        self.permissions = permissions
        self.ui = ui
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
            sub = SubAgent(self.config, self.workspace, client, self.registry,
                           name=m.name, system_prompt=m.role_prompt(),
                           allow_tools=m.allow_tools,
                           permissions=self.permissions, ui=ui)
            r = sub.run(task)
            return {"name": m.name, "role": m.role, "text": r.text,
                    "success": r.success, "usage": r.usage, "error": r.error}

        with ThreadPoolExecutor(max_workers=max(2, len(self.members))) as pool:
            futs = [pool.submit(one, m) for m in self.members]
            for f in as_completed(futs):
                out = f.result()
                member_outputs.append(out)
                usage += out["usage"]
        member_outputs.sort(key=lambda o: [m.name for m in self.members].index(o["name"]))

        # 负责人汇总
        if ui:
            ui.event("status", {"message": f"负责人正在汇总 {len(member_outputs)} 份成员产出…"})
        summary_prompt = self._leader_prompt(task, member_outputs)
        try:
            resp = self.client.chat([{"role": "user", "content": summary_prompt}],
                                    max_tokens=2048)
            final_text = resp.content
            usage += resp.usage
            success = bool(final_text.strip())
            error = ""
        except LLMError as e:
            final_text = ""
            success = False
            error = str(e)

        result = TeamResult(final_text=final_text, success=success,
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
            blocks.append(f"【成员 {o['name']}({o['role']})-{state}】\n{o['text']}")
        body = "\n\n".join(blocks)
        return f"{self.leader_prompt}\n\n原始任务:\n{task}\n\n成员产出:\n{body}\n\n请输出最终成果:"
