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
