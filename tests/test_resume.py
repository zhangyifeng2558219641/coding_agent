"""CLI 会话持久化与 /resume 恢复测试。

回归:此前 CLI 从不保存历史(save_history 只在 Web 端调用),
导致有历史对话时 /resume 仍返回"(无历史会话)"。
"""

from __future__ import annotations

from pathlib import Path

from codingagent.config import Config
from codingagent.session import Session
from codingagent.types import ToolCall
from conftest import MockClient


def make_resume_config(workspace: Path) -> Config:
    return Config({"provider": {"model": "mock", "base_url": "mock"},
                   "context": {"budget_tokens": 64000, "max_tool_output": 10000},
                   "agent": {"max_iterations": 10},
                   "permissions": {"mode": "auto-approve", "sandbox": True},
                   "memory": {"enabled": False},
                   "skills": {"dirs": []},
                   "commands": {"dir": str(workspace / ".coding_agent" / "commands")},
                   "mcp": {"servers": {}},
                   "sessions_dir": str(workspace / ".coding_agent" / "sessions")},
                  workspace)


def test_resume_no_history(tmp_path: Path):
    """无历史文件时 /resume 应提示无历史会话。"""
    cfg = make_resume_config(tmp_path)
    session = Session(cfg)
    agent = session.make_agent()
    resp = session.slash.run("resume", "", session.context(agent))
    assert "(无历史会话)" in resp


def test_cli_save_then_resume(tmp_path: Path):
    """CLI 保存会话后,新会话 /resume 能恢复历史消息。"""
    cfg = make_resume_config(tmp_path)
    session1 = Session(cfg)
    session1.client = MockClient([
        ("先找文件。", [ToolCall(id="t0", name="Glob", arguments={"pattern": "*.py"})]),
        ("已找到。", []),
    ])
    agent1 = session1.make_agent()
    agent1.run("找一下文件")

    # 模拟 run_cli 的 finally 行为
    session1.save_history(agent1.history, "cli")

    saved = tmp_path / ".coding_agent" / "sessions" / "cli.json"
    assert saved.is_file()
    orig_msgs = agent1.history.messages
    assert orig_msgs and orig_msgs[0]["role"] == "user"

    # 全新会话恢复
    session2 = Session(cfg)
    agent2 = session2.make_agent()
    assert agent2.history.count() == 0
    resp = session2.slash.run("resume", "", session2.context(agent2))
    assert "已恢复会话历史" in resp
    assert agent2.history.messages == orig_msgs
    assert any(m.get("role") == "tool" for m in agent2.history.messages)
