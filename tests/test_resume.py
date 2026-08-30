"""CLI 会话持久化与 /resume 恢复测试。

回归:此前 CLI 从不保存历史(save_history 只在 Web 端调用),
导致有历史对话时 /resume 仍返回"(无历史会话)"。
"""

from __future__ import annotations

from pathlib import Path

from codingagent.agent.loop import UISink
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

    # 模拟 run_cli 的 finally 行为(按会话时间戳命名)
    session1.save_history(agent1.history, "cli-20260830-100000")

    saved = tmp_path / ".coding_agent" / "sessions" / "cli-20260830-100000.json"
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


def save_session(cfg: Config, marker: int, sid: str):
    s = Session(cfg)
    s.client = MockClient([(f"第{marker}个会话的答复", [])])
    a = s.make_agent()
    a.run(f"任务{marker}")
    s.save_history(a.history, f"cli-{sid}")
    return a


def test_resume_lists_and_selects_multiple_sessions(tmp_path: Path):
    """多次 CLI 会话应可被 /resume 列出并按编号选择。"""
    cfg = make_resume_config(tmp_path)
    a_old = save_session(cfg, 1, "20260830-100000")  # 旧会话
    a_new = save_session(cfg, 2, "20260830-110000")  # 新会话(时间更晚,排序靠前)

    s = Session(cfg)
    agent = s.make_agent()
    ctx = s.context(agent)

    listing = s.slash.run("resume", "list", ctx)
    assert "cli-20260830-110000" in listing
    assert "cli-20260830-100000" in listing

    # 不带编号 → 恢复最新(110000)
    s.slash.run("resume", "", ctx)
    assert agent.history.messages == a_new.history.messages
    assert agent.history.messages[0]["content"] == "任务2"

    # 编号 2 → 恢复 100000(旧会话)
    s.slash.run("resume", "2", ctx)
    assert agent.history.messages == a_old.history.messages
    assert agent.history.messages[0]["content"] == "任务1"

    # 越界 / 非法编号给出提示
    assert "编号越界" in s.slash.run("resume", "99", ctx)
    assert "无效编号" in s.slash.run("resume", "abc", ctx)


def test_resume_legacy_single_file(tmp_path: Path):
    """旧版单个 cli.json 仍可被 /resume 恢复(向后兼容)。"""
    cfg = make_resume_config(tmp_path)
    s1 = Session(cfg)
    s1.client = MockClient([("旧版会话的答复", [])])
    a1 = s1.make_agent()
    a1.run("旧任务")
    s1.save_history(a1.history, "cli")

    s = Session(cfg)
    agent = s.make_agent()
    resp = s.slash.run("resume", "", s.context(agent))
    assert "已恢复会话历史 cli.json" in resp
    assert agent.history.messages == a1.history.messages


class PickingUI(UISink):
    """记录 choose 调用并返回预设选择的假 UI。"""

    def __init__(self, pick: int):
        self.pick = pick
        self.prompt = None
        self.options = None

    def choose(self, prompt: str, options: list[str]) -> int:
        self.prompt = prompt
        self.options = list(options)
        return self.pick


def test_resume_interactive_choose(tmp_path: Path):
    """多个会话时,无参数 /resume 应弹出选择供用户挑选。"""
    cfg = make_resume_config(tmp_path)
    a_old = save_session(cfg, 1, "20260830-100000")
    a_new = save_session(cfg, 2, "20260830-110000")

    # 选第 2 项 → 旧会话
    s = Session(cfg, ui=PickingUI(pick=1))
    agent = s.make_agent()
    ctx = s.context(agent)
    resp = s.slash.run("resume", "", ctx)
    assert s.ui.prompt                      # 确实触发了交互选择
    assert len(s.ui.options) == 2
    assert agent.history.messages == a_old.history.messages
    assert "已恢复会话历史 cli-20260830-100000.json" in resp

    # 取消 → 不恢复
    s2 = Session(cfg, ui=PickingUI(pick=-1))
    agent2 = s2.make_agent()
    resp2 = s2.slash.run("resume", "", s2.context(agent2))
    assert "(已取消恢复)" in resp2
    assert agent2.history.count() == 0

    # 只有一个会话时,不应弹出选择,直接恢复
    import shutil
    shutil.rmtree(tmp_path / ".coding_agent" / "sessions")
    save_session(cfg, 9, "20260830-120000")
    s4 = Session(cfg, ui=PickingUI(pick=-1))
    agent4 = s4.make_agent()
    resp4 = s4.slash.run("resume", "", s4.context(agent4))
    assert s4.ui.prompt is None              # 单个会话不弹选择
    assert "已恢复会话历史" in resp4
    assert agent4.history.messages[0]["content"] == "任务9"
