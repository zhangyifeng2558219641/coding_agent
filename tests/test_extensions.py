"""斜杠命令 / 钩子 / MCP / 技能 的单元测试。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from codingagent.commands import SlashCommand, SlashRegistry
from codingagent.hooks import HookManager
from codingagent.skills import SkillManager
from codingagent.tools import MCPClient, MCPManager, MCPToolAdapter
from codingagent.types import ToolResult


# ---------------------------------------------------------------------------
# 斜杠命令
# ---------------------------------------------------------------------------

def test_slash_basics():
    reg = SlashRegistry()

    def handler(session, args):
        return f"ran:{args}"

    reg.register(SlashCommand("ping", "test", handler, aliases=("p",)))
    assert reg.get("ping") and reg.get("p") and reg.get("PING")
    assert reg.run("ping", "hello", None) == "ran:hello"
    assert "未知命令" in reg.run("nope", "", None)
    assert any(c.name == "ping" for c in reg.list())


def test_slash_custom_markdown(tmp_path: Path):
    d = tmp_path / "commands"
    d.mkdir()
    (d / "review.md").write_text(
        "# review - 审查代码\n请审查以下改动,重点看正确性:\n{args}\n", encoding="utf-8")

    class FakeAgent:
        def __init__(self):
            self.prompt = ""
            self.results = {}

        def run(self, prompt):
            self.prompt = prompt
            return type("R", (), {"text": "审查结果", "success": True})()

    fake = FakeAgent()
    session = type("S", (), {"agent": fake})()
    reg = SlashRegistry()
    n = reg.load_custom(d)
    assert n == 1
    out = reg.run("review", "a.py", session)
    assert out == "审查结果"
    assert "a.py" in fake.prompt and "请审查" in fake.prompt


# ---------------------------------------------------------------------------
# 钩子
# ---------------------------------------------------------------------------

def test_hooks_command(tmp_path: Path):
    marker = tmp_path / "hook.log"

    def hook_cmd(event):
        return f'echo "{event}" >> "{marker}"'

    mgr = HookManager({
        "session_start": [{"command": hook_cmd("start")}],
        "agent_end": [{"command": hook_cmd("end")}],
    })
    mgr.fire("session_start", workspace=tmp_path)
    mgr.fire("agent_end", workspace=tmp_path)
    text = marker.read_text(encoding="utf-8")
    assert "start" in text and "end" in text


def test_hooks_pre_tool_veto(tmp_path: Path):
    mgr = HookManager({"pre_tool_call": [{"command": "exit 1"}]})
    assert mgr.fire_pre_tool("Bash", {"command": "ls"}) is False
    mgr2 = HookManager({"pre_tool_call": [{"command": "exit 0"}]})
    assert mgr2.fire_pre_tool("Bash", {"command": "ls"}) is True


def test_hooks_callable(tmp_path: Path):
    import hooks_test_helper as helper

    mgr = HookManager({"post_tool_call": [{"callable": "hooks_test_helper.record"}]})
    helper.records = []
    mgr.fire_post_tool("Bash", ToolResult(name="Bash", success=True, output="ok"))
    assert helper.records and helper.records[0]["tool_name"] == "Bash"


# ---------------------------------------------------------------------------
# MCP(自写 stdio + JSON-RPC 客户端)
# ---------------------------------------------------------------------------

DEMO_SERVER = Path(__file__).parent.parent / "examples" / "mcp_server_demo.py"


def test_mcp_client_roundtrip():
    client = MCPClient("python", [str(DEMO_SERVER)], name="demo")
    try:
        client.initialize()
        tools = client.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"demo_echo", "demo_add"}
        assert client.call_tool("demo_echo", {"text": "hi"}) == "echo: hi"
        assert client.call_tool("demo_add", {"a": 2, "b": 3}) == "2 + 3 = 5"
    finally:
        client.close()


def test_mcp_adapter():
    client = MCPClient("python", [str(DEMO_SERVER)], name="demo")
    try:
        client.initialize()
        spec = next(t for t in client.list_tools() if t["name"] == "demo_add")
        adapter = MCPToolAdapter("demo", client, spec)
        assert adapter.name == "demo_add"
        r = adapter.run(ctx=None, a=1, b=4)
        assert r.success and "1 + 4 = 5" in r.output
    finally:
        client.close()


def test_mcp_manager_connect(tmp_path: Path):
    mgr = MCPManager()
    try:
        tools = mgr.connect("demo", "python", [str(DEMO_SERVER)])
        assert set(tools) == {"demo_echo", "demo_add"}
        assert mgr.list_servers() == ["demo"]
    finally:
        mgr.close_all()
        assert mgr.list_servers() == []


# ---------------------------------------------------------------------------
# Worktree
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t.t"],
              ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True,
                       capture_output=True, text=True, encoding="utf-8")
    (repo / "a.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"],
                   check=True, capture_output=True)
    return repo


def test_worktree_create_list_remove(tmp_path: Path):
    from codingagent.agent.worktree import WorktreeManager
    repo = _make_repo(tmp_path)
    mgr = WorktreeManager(repo)
    assert mgr.is_repo()
    info = mgr.create(branch="feature-x")
    assert info.path.exists() and (info.path / "a.txt").exists()
    assert any("feature-x" in w.branch for w in mgr.list())
    mgr.remove(info.path)
    assert not info.path.exists()
    assert len(mgr.list()) == 1


def test_worktree_slash_handler(tmp_path: Path):
    from types import SimpleNamespace

    from codingagent.commands import SlashRegistry
    from codingagent.commands.builtins import register_builtin_commands
    repo = _make_repo(tmp_path)
    reg = SlashRegistry()
    register_builtin_commands(reg)
    ctx = SimpleNamespace(workspace=repo)
    out = reg.run("worktree", "create feature-a", ctx)
    assert "已创建" in out
    wt = repo.parent / f"{repo.name}.feature-a"
    assert wt.exists()
    assert "branch=" in reg.run("worktree", "list", ctx)
    out2 = reg.run("worktree", f"remove {wt}", ctx)
    assert "已移除" in out2 and not wt.exists()


# ---------------------------------------------------------------------------
# 技能
# ---------------------------------------------------------------------------

def test_skill_manager_load(tmp_path: Path):
    skill_dir = tmp_path / "skills"
    skill = skill_dir / "my-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: 测试技能\n---\n按照以下规范处理…\n",
        encoding="utf-8")
    mgr = SkillManager([str(skill_dir)])
    assert mgr.get("my-skill") is not None
    assert "my-skill" in mgr.available_block()
    from codingagent.llm.history import History
    h = History()
    mgr.history = h
    msg = mgr.load("my-skill")
    assert "已装载" in msg
    assert any(k == "skill:my-skill" for k, _ in h._system_parts)
    assert mgr.unload("my-skill")
    assert all(k != "skill:my-skill" for k, _ in h._system_parts)
