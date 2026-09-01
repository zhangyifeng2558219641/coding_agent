"""Web 端 API 测试:对话管理 CRUD + SSE 流式(用 Mock LLM,ASGI 直连)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from codingagent.session import Session
from codingagent.types import ToolCall
from codingagent.ui.web import create_app
from conftest import MockClient


def make_client_session(workspace: Path, script):
    from codingagent.config import Config
    cfg = Config({"provider": {"model": "mock", "base_url": "mock"},
                  "context": {"budget_tokens": 64000, "max_tool_output": 10000},
                  "agent": {"max_iterations": 10},
                  "permissions": {"mode": "auto-approve", "sandbox": True},
                  "memory": {"enabled": False},
                  "skills": {"dirs": []},
                  "commands": {"dir": str(workspace / ".coding_agent" / "commands")},
                  "mcp": {"servers": {}},
                  "teams": {"demo-team": {"members": [
                      {"name": "成员A", "role": "分析员"},
                  ]}},
                  "sessions_dir": str(workspace / ".coding_agent" / "sessions")},
                 workspace)
    session = Session(cfg)
    session.client = MockClient(script)
    return session


def run(coro):
    return asyncio.run(coro)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_web_health_and_config(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.get("/health")
            assert r.json() == {"status": "ok"}
            cfg = (await c.get("/api/config")).json()
            assert cfg["provider"]["model"] == "mock"
            assert "ReadFile" in cfg["tools"]
            assert "has_api_key" in cfg

    run(go())


def test_web_conversation_crud(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            meta = (await c.post("/api/conversations", json={"title": "t1"})).json()
            cid = meta["id"]
            assert (await c.get("/api/conversations")).json()[0]["id"] == cid
            got = (await c.get(f"/api/conversations/{cid}")).json()
            assert got["meta"]["id"] == cid
            assert (await c.delete(f"/api/conversations/{cid}")).json() == {"ok": True}
            assert (await c.get("/api/conversations")).json() == []

    run(go())


def test_web_chat_sse_tool_call(tmp_path: Path):
    session = make_client_session(tmp_path, [
        ("我来写文件。", [ToolCall(id="1", name="WriteFile",
                                   arguments={"path": "out.txt", "content": "web ok"})]),
        ("写好了。", []),
    ])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            r = await c.post("/api/chat",
                             json={"conversation_id": cid, "message": "创建 out.txt"})
            body = r.text
            assert "写好了" in body
            assert "tool_call" in body
            assert "done" in body
            assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "web ok"
            got = (await c.get(f"/api/conversations/{cid}")).json()
            assert any(m.get("role") == "tool" for m in got["messages"])

    run(go())


def test_web_chat_slash_command(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            r = await c.post("/api/chat",
                             json={"conversation_id": cid, "message": "/tools"})
            assert "ReadFile" in r.text
            assert "done" in r.text

    run(go())


def test_web_slash_team_streams_status(tmp_path: Path):
    """/team 长任务:状态事件(如"开始并行作业")应作为独立 status 事件流式下发,
    而非整段结果一次性吐出(回归:slash 分支曾阻塞事件循环且不排空队列)。"""
    session = make_client_session(tmp_path, [("成员完成", [])])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            r = await c.post("/api/chat",
                             json={"conversation_id": cid,
                                   "message": "/team demo-team 完成一次计划"})
            assert "event: status" in r.text
            assert "开始并行作业" in r.text
            assert "负责人正在汇总" in r.text
            assert "(mock 摘要)" in r.text  # 负责人汇总产出
            assert "done" in r.text

    run(go())


def test_index_served(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            html = (await c.get("/")).text
            assert "coding_agent" in html

    run(go())
