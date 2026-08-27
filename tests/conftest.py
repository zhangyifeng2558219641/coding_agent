"""pytest 公共 fixture:临时工作区 + Mock LLM + 构造 Agent 的辅助。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from codingagent.agent import AgentLoop, PermissionPolicy
from codingagent.config import Config
from codingagent.llm import ChatResponse, StreamEvent
from codingagent.tools import ToolRegistry, default_registry
from codingagent.types import ToolCall, Usage


class MockClient:
    """按脚本逐轮返回 (text, tool_calls) 的假 LLM;支持 callable 按消息自适应。"""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[list[dict]] = []
        self.model = "mock"

    def chat_stream(self, messages, tools=None, **kw):
        self.calls.append(list(messages))
        if not self.script:
            yield StreamEvent(type="text", text="(脚本耗尽)")
            yield StreamEvent(type="finish", reason="stop")
            return
        item = self.script.pop(0)
        if callable(item):
            item = item(messages)
        text, calls = item
        if text:
            yield StreamEvent(type="text", text=text)
        if calls:
            yield StreamEvent(type="tool_calls", calls=calls)
        yield StreamEvent(type="finish", reason="tool_calls" if calls else "stop")

    def chat(self, messages, **kw):
        self.calls.append(list(messages))
        return ChatResponse(content="(mock 摘要)", tool_calls=[], usage=Usage(10, 5))


def make_config(workspace: Path, **overrides) -> Config:
    """构造指向临时工作区的配置,可注入覆盖项。"""
    data = {
        "provider": {"base_url": "https://mock", "model": "mock", "include_usage": False},
        "context": {"budget_tokens": 64000, "max_tool_output": 10000},
        "agent": {"max_iterations": 10},
        "permissions": {"mode": "auto-approve", "sandbox": True,
                        "allow_tools": [], "deny_tools": [], "ask_tools": [],
                        "allow_commands": [], "dangerous_commands": [],
                        "sensitive_paths": [".git"], "sensitive_file_names": [".env"]},
        "memory": {"enabled": True,
                   "project_file": ".coding_agent/memory/project.md",
                   "user_file": str(Path.home() / ".coding_agent_mock" / "memory" / "user.md")},
        "skills": {"dirs": []},
        "mcp": {"servers": {}},
        "hooks": {},
        "teams": {},
    }
    import copy
    merged = copy.deepcopy(data)
    merged.update(overrides)
    if "permissions" in overrides:
        merged["permissions"] = {**data["permissions"], **overrides["permissions"]}
    return Config(merged, workspace)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "note.txt").write_text("hello world\nhello again\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> Config:
    return make_config(workspace)


def make_agent(config: Config, workspace: Path, script, registry: Optional[ToolRegistry] = None,
               perm_mode: str = "auto-approve", ui=None) -> AgentLoop:
    reg = registry or default_registry(with_memory=True, with_agent_tools=False)
    perms = PermissionPolicy({**config.permissions, "mode": perm_mode}, workspace)
    return AgentLoop(config, workspace, MockClient(script), reg,
                     permissions=perms, ui=ui or None)
