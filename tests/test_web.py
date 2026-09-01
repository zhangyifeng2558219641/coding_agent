"""Web 端 API 测试:对话管理 CRUD + SSE 流式(用 Mock LLM,ASGI 直连)。"""

from __future__ import annotations

import asyncio
import json
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


def make_ask_session(workspace: Path, script):
    """interactive 权限模式 + WriteFile 需确认,用于审批交互测试。"""
    from codingagent.config import Config
    cfg = Config({"provider": {"model": "mock", "base_url": "mock"},
                  "context": {"budget_tokens": 64000, "max_tool_output": 10000},
                  "agent": {"max_iterations": 10},
                  "permissions": {"mode": "interactive", "sandbox": True,
                                  "ask_tools": ["WriteFile"]},
                  "memory": {"enabled": False},
                  "skills": {"dirs": []},
                  "commands": {"dir": str(workspace / ".coding_agent" / "commands")},
                  "mcp": {"servers": {}},
                  "teams": {},
                  "sessions_dir": str(workspace / ".coding_agent" / "sessions")},
                 workspace)
    session = Session(cfg)
    session.client = MockClient(script)
    return session


def run(coro):
    return asyncio.run(coro)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def sse_events(text: str) -> list[tuple[str, str]]:
    """把 SSE 响应体解析成 [(event_type, data), ...]。"""
    out = []
    for block in text.split("\n\n"):
        e, data = None, []
        for line in block.split("\n"):
            if line.startswith("event:"):
                e = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if e:
            out.append((e, "\n".join(data)))
    return out


async def chat_with_ask(c, cid, message, allow):
    """后台跑 /api/chat(读完整 body),轮询 _ASKS 注册表见到 pending 即回 /api/respond。

    ASGITransport 缓冲整段响应,不能边读流边发请求;改为后台任务读 body,
    主流程直接轮询注册表定位 ask 的 qid,再 /api/respond 解锁。
    """
    import codingagent.ui.web as webmod

    async def run_chat():
        async with c.stream("POST", "/api/chat",
                            json={"conversation_id": cid, "message": message}) as r:
            return (await r.aread()).decode("utf-8")

    task = asyncio.create_task(run_chat())
    qid = None
    for _ in range(200):  # 最多 ~4s 等 ask 注册
        bucket = webmod._ASKS.get(cid) or {}
        if bucket:
            qid = next(iter(bucket))
            break
        await asyncio.sleep(0.02)
    if qid is None:
        task.cancel()
        raise AssertionError("未收到 ask 事件(注册表无 pending)")
    rr = await c.post("/api/respond",
                      json={"conversation_id": cid, "id": qid, "allow": allow})
    assert rr.status_code == 200
    return await asyncio.wait_for(task, timeout=5)


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
            evs = sse_events(r.text)
            statuses = [json.loads(d).get("message", "") for e, d in evs if e == "status"]
            assert "开始并行作业" in r.text
            assert any("开始处理" in s for s in statuses)     # 成员开始状态
            assert any("成功" in s and "成员A" in s for s in statuses)  # 成员完成状态
            assert "负责人正在汇总" in r.text
            assert "(mock 摘要)" in r.text  # 负责人汇总产出
            assert "done" in r.text
            # 成员原始推理不再作为 text 流泄漏(静默执行,避免多成员输出交织)
            texts = [json.loads(d).get("delta", "") for e, d in evs if e == "text"]
            assert not any("成员完成" in t for t in texts)

    run(go())


def test_index_served(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            html = (await c.get("/")).text
            assert "coding_agent" in html

    run(go())


def test_web_stop_endpoint(tmp_path: Path):
    """/api/stop:无进行中任务返回 ok=False;有则调用 agent.interrupt()(置位共享信号)。"""
    import threading
    import codingagent.ui.web as webmod
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.post("/api/stop", json={"conversation_id": "none"})
            assert r.json() == {"ok": False, "reason": "无进行中的任务"}

            interrupted = []
            class FakeAgent:
                def interrupt(self):
                    interrupted.append(True)
            ev = threading.Event()
            webmod._RUNNING["abc"] = {"agent": FakeAgent(), "stop_event": ev}
            try:
                r2 = await c.post("/api/stop", json={"conversation_id": "abc"})
                assert r2.json() == {"ok": True}
                assert interrupted == [True]
            finally:
                webmod._RUNNING.pop("abc", None)

            r3 = await c.post("/api/stop", json={"conversation_id": "abc"})
            assert r3.json()["ok"] is False

    run(go())


def test_web_chat_unregisters_running(tmp_path: Path):
    """chat 完成后从运行中注册表移除(该注册表供 /api/stop 中断时定位 agent)。"""
    import codingagent.ui.web as webmod
    session = make_client_session(tmp_path, [("写好了", [])])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            r = await c.post("/api/chat", json={"conversation_id": cid, "message": "hi"})
            assert "写好了" in r.text
            assert cid not in webmod._RUNNING

    run(go())


def test_web_export_markdown(tmp_path: Path):
    """导出 Markdown:含用户消息/助手分节/工具调用与结果,并作为附件下载。"""
    session = make_client_session(tmp_path, [
        ("我来读文件。", [ToolCall(id="1", name="ReadFile", arguments={"path": "a.py"})]),
        ("读好了,内容是 def foo。", []),
    ])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            await c.post("/api/chat", json={"conversation_id": cid, "message": "请读取 a.py"})
            r = await c.get(f"/api/conversations/{cid}/export", params={"format": "markdown"})
            assert r.status_code == 200
            assert "attachment" in r.headers.get("content-disposition", "")
            assert "请读取 a.py" in r.text
            assert "## 助手" in r.text
            assert "ReadFile" in r.text

    run(go())


def test_web_export_json(tmp_path: Path):
    """导出 JSON:返回带 meta 与 messages 的原始历史。"""
    session = make_client_session(tmp_path, [("你好", [])])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            await c.post("/api/chat", json={"conversation_id": cid, "message": "你好"})
            r = await c.get(f"/api/conversations/{cid}/export", params={"format": "json"})
            data = r.json()
            assert data["meta"]["id"] == cid
            assert any(m.get("role") == "user" for m in data["messages"])

    run(go())


def test_web_export_text(tmp_path: Path):
    """导出纯文本:可读的【用户】/【助手】转写。"""
    session = make_client_session(tmp_path, [("你好", [])])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            await c.post("/api/chat", json={"conversation_id": cid, "message": "你好"})
            r = await c.get(f"/api/conversations/{cid}/export", params={"format": "text"})
            assert "【用户】你好" in r.text

    run(go())


def test_web_export_404(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.get("/api/conversations/none/export", params={"format": "markdown"})
            assert r.status_code == 404

    run(go())


def test_web_export_bad_format(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            r = await c.get(f"/api/conversations/{cid}/export", params={"format": "pdf"})
            assert r.status_code == 400

    run(go())


def test_web_import_roundtrip(tmp_path: Path):
    """导出 → 删除 → 导入:新会话保留标题与三种 role 的消息。"""
    session = make_client_session(tmp_path, [
        ("我来读文件。", [ToolCall(id="1", name="ReadFile", arguments={"path": "a.py"})]),
        ("读好了。", []),
    ])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={"title": "原始标题"})).json()["id"]
            await c.post("/api/chat", json={"conversation_id": cid, "message": "请读取 a.py"})
            exported = (await c.get(f"/api/conversations/{cid}/export", params={"format": "json"})).json()
            assert await c.delete(f"/api/conversations/{cid}") is not None

            new_meta = (await c.post("/api/conversations/import", json=exported)).json()
            assert new_meta["id"] != cid
            assert new_meta["title"] == "原始标题"
            got = (await c.get(f"/api/conversations/{new_meta['id']}")).json()
            roles = [m["role"] for m in got["messages"]]
            assert "user" in roles and "assistant" in roles and "tool" in roles
            assert got["messages"][0]["content"] == "请读取 a.py"
            assert got["messages"][1]["tool_calls"][0]["function"]["name"] == "ReadFile"

    run(go())


def test_web_import_raw_history(tmp_path: Path):
    """无 meta 的 {messages:[...]}:标题回退到首条用户消息。"""
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            payload = {"messages": [
                {"role": "user", "content": "帮我写一个 hello"},
                {"role": "assistant", "content": "好的。"},
            ]}
            meta = (await c.post("/api/conversations/import", json=payload)).json()
            assert meta["title"] == "帮我写一个 hello"
            got = (await c.get(f"/api/conversations/{meta['id']}")).json()
            assert len(got["messages"]) == 2

    run(go())


def test_web_import_invalid_json(tmp_path: Path):
    """body 不是对象(数组) → 400。"""
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.post("/api/conversations/import", json=[])
            assert r.status_code == 400

    run(go())


def test_web_import_missing_messages(tmp_path: Path):
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.post("/api/conversations/import", json={"foo": 1})
            assert r.status_code == 400
            assert "messages" in r.text

    run(go())


def test_web_import_empty_messages(tmp_path: Path):
    """空数组 / 只含 system → 400「没有可导入的消息」。"""
    session = make_client_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            assert (await c.post("/api/conversations/import", json={"messages": []})).status_code == 400
            r = await c.post("/api/conversations/import",
                             json={"messages": [{"role": "system", "content": "x"}]})
            assert r.status_code == 400
            assert "没有可导入" in r.text

    run(go())


def test_web_ask_permission_allow(tmp_path: Path):
    """interactive 模式下 WriteFile 需确认:ask → 允许 → 工具执行、流正常收尾。"""
    import codingagent.ui.web as webmod
    session = make_ask_session(tmp_path, [
        ("写文件。", [ToolCall(id="1", name="WriteFile",
                               arguments={"path": "out.txt", "content": "ask ok"})]),
        ("写好了。", []),
    ])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            body = await chat_with_ask(c, cid, "写 out.txt", True)
            assert "event: ask" in body and "event: done" in body
            assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "ask ok"
            assert cid not in webmod._ASKS  # ask 完成后注册表已清空

    run(go())


def test_web_ask_permission_deny(tmp_path: Path):
    """interactive 模式下 WriteFile 需确认:ask → 拒绝 → 工具不执行。"""
    import codingagent.ui.web as webmod
    session = make_ask_session(tmp_path, [
        ("写文件。", [ToolCall(id="1", name="WriteFile",
                               arguments={"path": "out.txt", "content": "ask ok"})]),
        ("写好了。", []),
    ])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = (await c.post("/api/conversations", json={})).json()["id"]
            body = await chat_with_ask(c, cid, "写 out.txt", False)
            assert "event: ask" in body and "event: done" in body
            assert not (tmp_path / "out.txt").exists()
            assert cid not in webmod._ASKS

    run(go())


def test_web_respond_unknown(tmp_path: Path):
    """/api/respond 指向不存在的确认 → ok False。"""
    session = make_ask_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            r = await c.post("/api/respond", json={"conversation_id": "x", "id": "nope", "allow": True})
            assert r.json() == {"ok": False}

    run(go())


def test_web_stop_clears_pending_asks(tmp_path: Path):
    """/api/stop 解除并清理该会话所有待审批阻塞。"""
    import threading
    import codingagent.ui.web as webmod
    session = make_ask_session(tmp_path, [])
    app = create_app(session)

    async def go():
        async with client(app) as c:
            cid = "fakeask"
            ev = threading.Event()
            webmod._ASKS[cid] = {"q1": {"event": ev, "answer": None}}
            try:
                r = await c.post("/api/stop", json={"conversation_id": cid})
                assert r.json()["ok"] is False  # 无进行中的任务,但待审批已清理
                assert ev.is_set()
                assert cid not in webmod._ASKS
            finally:
                webmod._ASKS.pop(cid, None)

    run(go())
