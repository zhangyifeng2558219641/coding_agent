"""子任务分发:把任务委派给独立的子 Agent 并行执行。

子 Agent 复用同一套 AgentLoop,但拥有独立的对话历史与(可选的)独立工作区,
互不干扰;主 Agent 通过 DispatchTask 工具把子任务交出去并收回结果。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..llm import ChatClient
from ..types import Usage
from ..tools import ToolRegistry
from .loop import AgentLoop, AgentOptions, UISink
from .permissions import PermissionPolicy


@dataclass
class SubAgentResult:
    task: str
    text: str = ""
    success: bool = False
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    error: str = ""


class SubAgent:
    """独立上下文的子 Agent。"""

    def __init__(
        self,
        config,
        workspace: Path,
        client: ChatClient,
        registry: ToolRegistry,
        *,
        name: str = "sub",
        system_prompt: str = "",
        allow_tools: Optional[list[str]] = None,
        permissions: Optional[PermissionPolicy] = None,
        ui: Optional[UISink] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.config = config
        self.name = name
        self.workspace = workspace.resolve()
        self.loop = AgentLoop(
            config, self.workspace, client, registry,
            permissions=permissions,
            history=None,
            ui=ui,
            options=AgentOptions(
                max_iterations=config.agent.get("max_iterations", 20),
                system_prompt=system_prompt or _default_sub_prompt(name),
                allow_tools=allow_tools,
            ),
            stop_event=stop_event,
        )

    def run(self, task: str) -> SubAgentResult:
        r = self.loop.run(task)
        return SubAgentResult(task=task, text=r.text, success=r.success,
                              iterations=r.iterations, usage=r.usage, error=r.error)


def _default_sub_prompt(name: str) -> str:
    return (
        f"你是子 Agent「{name}」。你被主 Agent 委派处理一项子任务。"
        "请独立完成:先理解任务,必要时读取文件/搜索代码,完成后只输出你的结论与产出,"
        "不要与用户闲聊。"
    )


def run_subagents_parallel(
    config,
    workspace: Path,
    client: ChatClient,
    registry: ToolRegistry,
    tasks: list[str],
    *,
    name_prefix: str = "worker",
    system_prompt: str = "",
    allow_tools: Optional[list[str]] = None,
    max_workers: int = 3,
) -> list[SubAgentResult]:
    """并行执行多个子任务(线程池),互不共享上下文。"""
    results: list[SubAgentResult] = []

    def one(task: str, idx: int) -> SubAgentResult:
        sub = SubAgent(config, workspace, client, registry,
                       name=f"{name_prefix}{idx}", system_prompt=system_prompt,
                       allow_tools=allow_tools)
        return sub.run(task)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(one, task, i) for i, task in enumerate(tasks)]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: tasks.index(r.task))
    return results
