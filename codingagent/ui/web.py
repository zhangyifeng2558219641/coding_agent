"""网页端(FastAPI + SSE):对话管理 + 流式输出,非终端交互方式。

单进程单工作区;会话列表与会话历史持久化到 .coding_agent/sessions/。
POST /api/chat 以 SSE 流式返回事件:start / text / tool_call / tool_result /
status / compact / turn_end / error / done。
"""

from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..agent.loop import UISink
from ..session import Session
from .export import conversation_to_markdown, conversation_to_text


# ---------------------------------------------------------------------------
# 进行中的任务注册表(供 /api/stop 中断)
# conversation_id → {"agent": AgentLoop 或 None, "stop_event": threading.Event}
# ---------------------------------------------------------------------------

_RUNNING: dict[str, dict[str, Any]] = {}

# 待审批确认注册表(供 /api/respond 回填答案)
# conversation_id -> {qid: {"event": threading.Event, "answer": bool|None}}
_ASKS: dict[str, dict[str, dict[str, Any]]] = {}
# ask 超时(秒):超时未响应按拒绝处理,避免 worker 线程永久挂起
_ASK_TIMEOUT = 600

# 待用户选择注册表(供 /api/choose 回填答案)
# conversation_id -> {qid: {"event": threading.Event, "answer": int|str|None}}
_CHOOSES: dict[str, dict[str, dict[str, Any]]] = {}
_CHOOSE_TIMEOUT = 600


# ---------------------------------------------------------------------------
# 会话存储
# ---------------------------------------------------------------------------

class ChatBody(BaseModel):
    conversation_id: str
    message: str
    permission_mode: Optional[str] = None
    model: Optional[str] = None
    # 编辑重发:截断到该历史索引(丢弃其及之后的消息)再追加新消息
    resend_at: Optional[int] = None


class ConversationStore:
    def __init__(self, store_dir: Path):
        self.dir = store_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_file = self.dir / "_conversations.json"
        self._meta: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self.meta_file.write_text(json.dumps(self._meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        except OSError:
            pass

    def create(self, title: str = "新会话") -> dict[str, Any]:
        cid = uuid.uuid4().hex[:12]
        # 微秒精度:同秒内连续操作也能区分先后(置顶排序依赖)
        now = datetime.now().isoformat(timespec="microseconds")
        meta = {"id": cid, "title": title, "created_at": now, "updated_at": now}
        self._meta[cid] = meta
        self._save()
        return meta

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._meta.values(), key=lambda m: m["updated_at"], reverse=True)

    def get(self, cid: str) -> Optional[dict[str, Any]]:
        return self._meta.get(cid)

    def touch(self, cid: str, title: Optional[str] = None) -> None:
        if cid in self._meta:
            self._meta[cid]["updated_at"] = datetime.now().isoformat(timespec="microseconds")
            if title:
                self._meta[cid]["title"] = title
            self._save()

    def delete(self, cid: str) -> bool:
        if cid not in self._meta:
            return False
        del self._meta[cid]
        self._save()
        try:
            (self.dir / f"{cid}.json").unlink(missing_ok=True)
        except OSError:
            pass
        return True

    def history_path(self, cid: str) -> Path:
        return self.dir / f"{cid}.json"


# ---------------------------------------------------------------------------
# SSE UI 适配器
# ---------------------------------------------------------------------------

class SSEUI(UISink):
    def __init__(self, emit, cid: Optional[str] = None,
                 stop_event: Optional[threading.Event] = None):
        self._emit = emit  # (type, data) -> None,线程安全
        self._cid = cid
        self._stop_event = stop_event

    def event(self, type: str, data: dict[str, Any]) -> None:
        self._emit(type, data)

    def ask(self, question: str) -> bool:
        """交互式审批:发出 ask 事件后阻塞等待用户经 /api/respond 回答。

        无 cid(未接 Web 通道)或停止/超时一律按拒绝(False)处理。
        """
        if not self._cid:
            return False
        qid = uuid.uuid4().hex[:8]
        entry = {"event": threading.Event(), "answer": None}
        _ASKS.setdefault(self._cid, {})[qid] = entry
        self._emit("ask", {"id": qid, "question": question})
        try:
            deadline = time.monotonic() + _ASK_TIMEOUT
            while not entry["event"].wait(0.2):
                if self._stop_event is not None and self._stop_event.is_set():
                    return False
                if time.monotonic() >= deadline:
                    return False
            return bool(entry["answer"])
        finally:
            bucket = _ASKS.get(self._cid)
            if bucket:
                bucket.pop(qid, None)
                if not bucket:
                    _ASKS.pop(self._cid, None)

    def choose(self, prompt: str, options: list[str]) -> Optional[int | str]:
        """交互选择:发出 choose 事件后阻塞等待用户经 /api/choose 回答。

        返回选中索引(>=0)、-1(取消/超时/停止)或用户自定义文本;
        无 cid(未接 Web 通道)返回 None。
        """
        if not self._cid:
            return None
        qid = uuid.uuid4().hex[:8]
        entry = {"event": threading.Event(), "answer": None}
        _CHOOSES.setdefault(self._cid, {})[qid] = entry
        self._emit("choose", {"id": qid, "prompt": prompt, "options": list(options)})
        try:
            deadline = time.monotonic() + _CHOOSE_TIMEOUT
            while not entry["event"].wait(0.2):
                if self._stop_event is not None and self._stop_event.is_set():
                    return -1
                if time.monotonic() >= deadline:
                    return -1
            return entry["answer"]
        finally:
            bucket = _CHOOSES.get(self._cid)
            if bucket:
                bucket.pop(qid, None)
                if not bucket:
                    _CHOOSES.pop(self._cid, None)


def _sse(type: str, data: dict[str, Any]) -> str:
    return f"event: {type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _coalesce(queue: asyncio.Queue, alive) -> Any:
    """消费队列并实时产出 (type, data);相邻 text 增量按小时间窗合并成一条,
    降低事件密度 —— 6 成员并行流式时 LLM 逐 token 的 delta 会成千上万条,
    不合并会让浏览器逐条渲染、被拖到卡死。非 text 事件(工具/状态等)到即发。"""
    loop = asyncio.get_event_loop()
    pending: list[str] = []
    last_flush = loop.time()
    while alive() or not queue.empty():
        try:
            t, d = await asyncio.wait_for(queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            t, d = None, None
        if t == "text":
            pending.append(d.get("delta", ""))
        elif t is not None:
            if pending:
                yield "text", {"delta": "".join(pending)}
                pending.clear()
            yield t, d
        now = loop.time()
        if pending and now - last_flush >= 0.1:
            yield "text", {"delta": "".join(pending)}
            pending.clear()
            last_flush = now
    if pending:
        yield "text", {"delta": "".join(pending)}


_TITLE_PREFIXES = [
    "请帮我写", "请帮我", "请给我", "麻烦你", "请你帮我",
    "帮我写", "帮我生成", "帮我实现", "帮我修复", "帮我做", "帮我看看",
    "帮我读", "帮我改", "帮我找", "帮我查", "帮我解释", "帮我总结", "帮我分析", "帮我检查", "帮我",
    "请你", "麻烦", "请",
    "能不能", "能否", "可否", "你能", "你可以",
    "我需要", "我想", "我要", "我想要",
    "写一个", "写个", "写一段", "写一份",
    "实现一个", "生成一个", "创建一个", "做一个", "实现", "生成", "创建", "做",
    "阅读", "读取", "读一下", "看看", "查看", "检查", "分析", "总结", "解释一下", "解释",
    "修复一下", "修复", "添加", "新增", "优化", "重构", "测试", "调试", "删除", "移除", "修改",
    "把", "给", "让", "将",
    "一个", "这个", "那个",
]


def _default_title(message: str) -> str:
    """从首条消息提取核心内容作标题:去祈使前缀/代码块、按句读断句、限长。"""
    msg = (message or "").strip()
    if not msg:
        return "新会话"
    # 代码块:取第一行非空内容(代码保留括号/引号,不做标点剥离)
    if msg.startswith("```"):
        lines = [l.strip() for l in msg.splitlines()
                 if l.strip() and not l.strip().startswith("```")]
        msg = lines[0] if lines else "代码片段"
        from_code = True
    else:
        msg = msg.replace("\n", " ").strip()
        from_code = False
    # 反复剥离祈使前缀(长前缀优先,直到不再变化)
    changed = True
    while changed and msg:
        changed = False
        low = msg.lower()
        for p in _TITLE_PREFIXES:
            if low.startswith(p):
                msg = msg[len(p):].strip()
                changed = True
                break
    # 去掉首尾标点/中文引号(代码内容原样保留)
    if not from_code:
        msg = msg.strip(" \t“”‘’「」『』〈〉《》()（）[]【】,，。！？!?;；:：、")
    # 优先取第一个句末标点前的完整分句
    for sep in "。！？!?\n":
        if sep in msg:
            msg = msg.split(sep, 1)[0]
            break
    # 超长时优先在逗号处断,否则按字截断
    if len(msg) > 24:
        cut = msg.find("，")
        if 0 < cut <= 24:
            msg = msg[:cut]
    if len(msg) > 24:
        msg = msg[:24].rstrip() + "…"
    return msg or "新会话"


_TITLE_SYSTEM = (
    "把下面的用户消息概括成一个不超过20字的简短中文标题,只输出标题本身,"
    "不要引号、不要多余标点。"
)


def _llm_title(client, message: str) -> str:
    """用模型把首条消息总结成标题;任何失败/非法输出都返回空串(回退启发式)。"""
    try:
        resp = client.chat([
            {"role": "system", "content": _TITLE_SYSTEM},
            {"role": "user", "content": (message or "")[:500]},
        ])
        title = (resp.content or "").strip().strip("“”\"'《》。，, ")
        if not title or len(title) > 24:
            return ""
        return title
    except Exception:
        return ""


def _title_client(session) -> Any:
    """标题精修用的轻量客户端:短超时、单次重试、小 max_tokens。"""
    from ..llm import ChatClient
    p = session.config.provider
    return ChatClient(
        base_url=p.get("base_url", "https://api.deepseek.com"),
        api_key=session.config.api_key(),
        model=p.get("model", "deepseek-chat"),
        temperature=0.3,
        max_tokens=256,
        timeout=10,
        max_retries=1,
        include_usage=False,
    )


def _refine_title(store, client, cid: str, message: str, auto_title: Optional[str]) -> None:
    """首条消息完成后,用模型把自动标题精修为核心内容;用户已改过则不覆盖。"""
    if not auto_title:
        return
    title = _llm_title(client, message)
    if not title:
        return
    cur = store.get(cid)
    if cur and cur["title"] == auto_title:
        store.touch(cid, title)


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

def create_app(session: Session) -> FastAPI:
    store = ConversationStore(session.config.session_store_path())
    app = FastAPI(title="coding_agent web")

    @app.get("/api/config")
    def api_config():
        cfg = session.config.public_dict()
        cfg["tools"] = sorted(session.registry.names())
        cfg["skills"] = [s.to_summary() for s in session.skills.list()]
        cfg["slash_commands"] = [f"/{c.name} - {c.description}" for c in session.slash.list()]
        cfg["mcp_servers"] = session.mcp.list_servers()
        return cfg

    @app.get("/api/conversations")
    def list_conversations():
        return store.list()

    @app.post("/api/conversations")
    def create_conversation(payload: dict):
        title = (payload or {}).get("title") or "新会话"
        return store.create(title)

    @app.get("/api/conversations/{cid}/export")
    def export_conversation(cid: str, format: str = "markdown"):
        """把会话导出为文件下载:markdown(可读记录)/ json(原始历史)/ text(纯文本)。"""
        meta = store.get(cid)
        if not meta:
            raise HTTPException(404, "会话不存在")
        history_dict: dict[str, Any] = {}
        hist_path = store.history_path(cid)
        if hist_path.exists():
            try:
                history_dict = json.loads(hist_path.read_text(encoding="utf-8"))
            except Exception:
                history_dict = {}
        messages = history_dict.get("messages", [])

        if format == "json":
            content = json.dumps({"meta": meta, **history_dict}, ensure_ascii=False, indent=2)
            media, ext = "application/json; charset=utf-8", "json"
        elif format == "markdown":
            content = conversation_to_markdown(meta, messages)
            media, ext = "text/markdown; charset=utf-8", "md"
        elif format == "text":
            content = conversation_to_text(meta, messages)
            media, ext = "text/plain; charset=utf-8", "txt"
        else:
            raise HTTPException(400, f"未知导出格式: {format}")

        safe_title = re.sub(r'[\\/:*?"<>|]', "_", meta.get("title") or "会话")
        filename = f"{safe_title}.{ext}"
        return Response(
            content, media_type=media,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    @app.post("/api/conversations/import")
    def import_conversation(payload: Any = Body(...)):
        """把导出的 JSON(或同构的 {messages:[...]})恢复为一个全新会话。"""
        if not isinstance(payload, dict):
            raise HTTPException(400, "导入内容必须是 JSON 对象")
        raw = payload.get("messages")
        if not isinstance(raw, list):
            raise HTTPException(400, "缺少 messages 数组")
        messages: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise HTTPException(400, f"messages[{i}] 不是对象")
            role = item.get("role")
            if role not in ("user", "assistant", "tool"):
                continue  # 丢弃 system 等不可渲染角色
            content = "" if item.get("content") is None else str(item.get("content"))
            m: dict[str, Any] = {"role": role, "content": content}
            if role == "assistant":
                calls = []
                for tc in (item.get("tool_calls") or []):
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") or {}
                    calls.append({"id": str(tc.get("id") or tc.get("tool_call_id") or ""),
                                  "function": {"name": str(fn.get("name") or "工具"),
                                               "arguments": str(fn.get("arguments") or "{}")}})
                if calls:
                    m["tool_calls"] = calls
            elif role == "tool" and item.get("tool_call_id"):
                m["tool_call_id"] = str(item.get("tool_call_id"))
            messages.append(m)
        if not messages:
            raise HTTPException(400, "没有可导入的消息")

        # 标题:导入的 meta.title → 首条用户消息 → 兜底
        imported_meta = payload.get("meta") or {}
        title = imported_meta.get("title") or ""
        if not title:
            first_user = next((x["content"] for x in messages if x["role"] == "user"), "")
            title = _default_title(first_user) if first_user else "导入的会话"

        meta = store.create(title)
        history_dict = {"messages": messages,
                        "summary": payload.get("summary", "") or "",
                        "compact_count": int(payload.get("compact_count", 0) or 0),
                        "usage": payload.get("usage") or {}}
        try:
            store.history_path(meta["id"]).write_text(
                json.dumps(history_dict, ensure_ascii=False), encoding="utf-8")
        except OSError:
            raise HTTPException(500, "写入会话历史失败")
        return meta  # 前端用它 openConv

    @app.get("/api/conversations/{cid}")
    def get_conversation(cid: str):
        meta = store.get(cid)
        if not meta:
            raise HTTPException(404, "会话不存在")
        hist_path = store.history_path(cid)
        messages = []
        if hist_path.exists():
            try:
                messages = json.loads(hist_path.read_text(encoding="utf-8")).get("messages", [])
            except Exception:
                messages = []
        return {"meta": meta, "messages": messages}

    @app.delete("/api/conversations/{cid}")
    def delete_conversation(cid: str):
        return {"ok": store.delete(cid)}

    @app.post("/api/conversations/{cid}/rename")
    def rename_conversation(cid: str, payload: dict):
        if store.get(cid) is None:
            raise HTTPException(404, "会话不存在")
        title = ((payload or {}).get("title") or "").strip()
        if not title:
            return {"ok": False, "error": "标题为空"}
        store.touch(cid, title)
        return {"ok": True}

    @app.post("/api/chat")
    async def chat(body: ChatBody):
        if not body.message.strip():
            raise HTTPException(400, "消息为空")
        meta = store.get(body.conversation_id)
        if not meta:
            meta = store.create()
        auto_title = None
        if not meta["title"] or meta["title"] == "新会话":
            auto_title = _default_title(body.message)
            store.touch(body.conversation_id, auto_title)
        else:
            # 每次发消息都刷新"最近活跃",让该会话置顶
            store.touch(body.conversation_id)

        # 装载/恢复该会话的独立历史(新会话新建,互不共享)
        history = session.load_history(body.conversation_id)
        if history is None:
            from ..llm import History
            history = History(
                budget_tokens=session.config.context.get("budget_tokens", 64000),
                max_tool_output=session.config.context.get("max_tool_output", 30000),
            )

        # 编辑重发:截断到该历史索引(丢弃被编辑消息及其之后),再追加新消息
        if body.resend_at is not None and 0 <= body.resend_at < len(history.messages):
            history.messages = history.messages[:body.resend_at]

        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        # 每个请求独立停止信号;agent 创建后挂上去,Web「停止生成」/跳转页面都会中止
        stop_event = threading.Event()
        _RUNNING[body.conversation_id] = {"agent": None, "stop_event": stop_event}
        ui = SSEUI(lambda t, d: loop.call_soon_threadsafe(q.put_nowait, (t, d)),
                   cid=body.conversation_id, stop_event=stop_event)

        if body.message.startswith("/"):
            # 斜杠命令(尤其 /team 这类长任务)也在 worker 线程执行并实时下发队列事件,
            # 否则会阻塞事件循环,直到整个命令跑完才一次性吐出结果(看起来"卡住后一大串")。
            slash_holder: dict[str, Any] = {}

            def slash_work() -> None:
                # 内置命令(如 /team、/status)不写历史,记录输入输出,刷新后不丢失;
                # 自定义命令经 agent.run 已自行追加、/clear|compact|resume 亦已改动历史,
                # 以消息数是否变化为判据,避免重复记录或误写。
                before = len(history.messages)
                try:
                    agent = session.make_agent(history=history, ui=ui,
                                               permission_mode=body.permission_mode)
                    agent.stop_event = stop_event
                    _RUNNING[body.conversation_id]["agent"] = agent
                    ctx = session.context(agent)
                    slash_holder["resp"] = session.slash.run(
                        body.message[1:].partition(" ")[0],
                        body.message[1:].partition(" ")[2].strip(), ctx)
                except Exception as e:  # pragma: no cover
                    slash_holder["error"] = str(e)
                finally:
                    _RUNNING.pop(body.conversation_id, None)
                if len(history.messages) == before:
                    resp = slash_holder.get("error") and f"命令执行失败: {slash_holder['error']}" \
                        or slash_holder.get("resp") or "(无输出)"
                    history.append({"role": "user", "content": body.message})
                    history.append({"role": "assistant", "content": resp})
                    session.save_history(history, body.conversation_id)

            async def slash_stream():
                yield _sse("meta", {"type": "slash", "command": body.message})
                thread = threading.Thread(target=slash_work, daemon=True)
                thread.start()
                async for t, d in _coalesce(q, thread.is_alive):
                    yield _sse(t, d)
                if "error" in slash_holder:
                    resp = f"命令执行失败: {slash_holder['error']}"
                else:
                    resp = slash_holder.get("resp") or "(无输出)"
                yield _sse("text", {"delta": resp})
                yield _sse("done", {"conversation_id": body.conversation_id})
            return StreamingResponse(slash_stream(), media_type="text/event-stream")

        result_holder: dict[str, Any] = {}

        def work() -> None:
            try:
                agent = session.make_agent(history=history, ui=ui,
                                           permission_mode=body.permission_mode)
                agent.stop_event = stop_event
                _RUNNING[body.conversation_id]["agent"] = agent
                if body.model:
                    agent.client.model = body.model
                result_holder["result"] = agent.run(body.message)
                session.save_history(history, body.conversation_id)
                # 首条消息自动标题:用模型精修为核心内容(无 key/离线时保持启发式标题)
                if auto_title:
                    _refine_title(store, _title_client(session), body.conversation_id,
                                  body.message, auto_title)
            except Exception as e:  # pragma: no cover
                result_holder["error"] = str(e)
            finally:
                _RUNNING.pop(body.conversation_id, None)

        async def stream():
            yield _sse("start", {"conversation_id": body.conversation_id})
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            async for t, d in _coalesce(q, thread.is_alive):
                yield _sse(t, d)
            if "error" in result_holder:
                yield _sse("error", {"message": result_holder["error"]})
            result = result_holder.get("result")
            yield _sse("done", {
                "conversation_id": body.conversation_id,
                "final_text": result.text if result else "",
                "success": result.success if result else False,
                "error": (result.error if result else result_holder.get("error", "")) or "",
            })

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/stop")
    def stop(body: dict[str, Any]):
        """中断指定会话进行中的生成(agent.interrupt() → stop_event 置位),并解除待审批阻塞。"""
        cid = (body or {}).get("conversation_id", "")
        for entry in _ASKS.pop(cid, {}).values():
            entry["answer"] = False
            entry["event"].set()
        for entry in _CHOOSES.pop(cid, {}).values():
            entry["answer"] = -1
            entry["event"].set()
        entry = _RUNNING.get(cid)
        if not entry or entry.get("agent") is None:
            return {"ok": False, "reason": "无进行中的任务"}
        try:
            entry["agent"].interrupt()
            return {"ok": True}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "reason": str(e)}

    @app.post("/api/respond")
    def respond(body: dict[str, Any]):
        """回填某个待审批确认的答案(Web 输入框「允许/拒绝」)。"""
        cid = (body or {}).get("conversation_id", "")
        qid = (body or {}).get("id", "")
        entry = _ASKS.get(cid, {}).get(qid)
        if not entry:
            return {"ok": False}
        entry["answer"] = bool((body or {}).get("allow", False))
        entry["event"].set()
        return {"ok": True}

    @app.post("/api/choose")
    def choose(body: dict[str, Any]):
        """回填某个待用户选择问题的答案(Web 输入框上方的选项条)。"""
        cid = (body or {}).get("conversation_id", "")
        qid = (body or {}).get("id", "")
        entry = _CHOOSES.get(cid, {}).get(qid)
        if not entry:
            return {"ok": False}
        if "index" in body:
            entry["answer"] = int(body["index"])
        elif body.get("text") is not None:
            entry["answer"] = str(body["text"])
        else:
            entry["answer"] = -1
        entry["event"].set()
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_INDEX_HTML)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# 前端(单文件,无构建步骤)
# ---------------------------------------------------------------------------

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>coding_agent · 编程智能体</title>
<style>
  :root { --bg:#0f1117; --panel:#171a23; --panel2:#1d212e; --text:#e6e8ef;
          --dim:#8a90a3; --accent:#5b8cff; --border:#2a2f3d; --ok:#3ddc84; --err:#ff6b6b;
          --on-accent:#ffffff; }
  /* 整体颜色风格:工具栏「主题」下拉即时切换,选择存 localStorage */
  html[data-theme="light"] { --bg:#f5f7fa; --panel:#ffffff; --panel2:#eef1f6; --text:#1f2933;
          --dim:#66707c; --accent:#2563eb; --border:#d5dbe3; --ok:#16a34a; --err:#dc2626;
          --on-accent:#ffffff; }
  html[data-theme="warm"] { --bg:#fbf6ec; --panel:#fffdf5; --panel2:#f2ead7; --text:#3d3a34;
          --dim:#8a8378; --accent:#8a6d3b; --border:#e3d8c0; --ok:#5f8a3b; --err:#c0563b;
          --on-accent:#ffffff; }
  html[data-theme="nord"] { --bg:#1b1e27; --panel:#232a3b; --panel2:#2c3547; --text:#d8dee9;
          --dim:#8294ad; --accent:#88c0d0; --border:#3a4458; --ok:#a3be8c; --err:#bf616a;
          --on-accent:#11141c; }
  /* 南大紫:官方标准色 C50 M100 Y0 K40 → RGB(106,0,95) #6A005F 的暗色系变体 */
  html[data-theme="purple"] { --bg:#170e23; --panel:#201431; --panel2:#2a1b41; --text:#f0eaf8;
          --dim:#a48fc0; --accent:#c14eb0; --border:#3d2a58; --ok:#3ddc84; --err:#ff6b6b;
          --on-accent:#ffffff; }
  /* 软件蓝:软件学院院名字标的蓝色 #7091C7,深色导航背景上配深蓝文字 */
  html[data-theme="blue"] { --bg:#0b1322; --panel:#121a2e; --panel2:#182340; --text:#e9eef9;
          --dim:#8d9cb8; --accent:#7091c7; --border:#24324f; --ok:#3ddc84; --err:#ff6b6b;
          --on-accent:#0b1322; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:"Segoe UI", system-ui, "Microsoft YaHei", sans-serif;
         display:flex; height:100vh; overflow:hidden; }
  #sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border);
             display:flex; flex-direction:column; flex-shrink:0; }
  #sidebar h1 { font-size:15px; padding:16px 14px; letter-spacing:.5px; }
  #sidebar h1 span { color:var(--accent); }
  #newBtn { margin:0 12px 10px; padding:9px; background:var(--accent); border:none; border-radius:8px;
            color:var(--on-accent); font-size:13px; cursor:pointer; }
  #search { margin:0 12px 10px; padding:8px 10px; background:var(--panel2); color:var(--text);
            border:1px solid var(--border); border-radius:8px; font-size:12px; outline:none; box-sizing:border-box; }
  #search:focus { border-color:var(--accent); }
  #search::placeholder { color:var(--dim); }
  .rename-input { width:100%; box-sizing:border-box; padding:2px 6px; font-size:12px; color:var(--text);
                  background:var(--panel2); border:1px solid var(--accent); border-radius:4px; outline:none; }
  #convList { flex:1; overflow-y:auto; }
  .conv { padding:10px 14px; cursor:pointer; border-bottom:1px solid var(--border); font-size:13px;
          color:var(--dim); display:flex; justify-content:space-between; align-items:center; }
  .conv:hover { background:var(--panel2); }
  .conv.active { background:var(--panel2); color:var(--text); }
  .conv .del { opacity:0; border:none; background:none; color:var(--err); cursor:pointer; font-size:14px; }
  .conv:hover .del { opacity:1; }
  #footer { padding:10px 14px; font-size:11px; color:var(--dim); border-top:1px solid var(--border); }
  #main { flex:1; display:flex; flex-direction:column; min-width:0; }
  #toolbar { padding:10px 18px; border-bottom:1px solid var(--border); font-size:12px; color:var(--dim);
             display:flex; gap:16px; align-items:center; }
  #toolbar select, #toolbar button { background:var(--panel2); color:var(--text); border:1px solid var(--border);
             border-radius:6px; padding:4px 8px; font-size:12px; }
  #messages { flex:1; overflow-y:auto; padding:20px 24px; }
  .msg { margin-bottom:16px; max-width:100%; }
  .msg .bubble { padding:10px 14px; border-radius:10px; white-space:pre-wrap; word-break:break-word;
                 font-size:14px; line-height:1.55; }
  .msg.user { display:flex; justify-content:flex-end; align-items:center; gap:6px; }
  .msg.user .bubble { background:var(--accent); color:var(--on-accent); display:inline-block; text-align:left; }
  .ubtn { border:none; background:none; color:var(--dim); cursor:pointer; font-size:12px; opacity:0; padding:4px; flex-shrink:0; }
  .msg.user:hover .ubtn { opacity:1; }
  .ubtn:hover { color:var(--accent); }
  .msg.assistant .bubble { background:var(--panel); border:1px solid var(--border); white-space:normal; }
  .msg.system .bubble { background:transparent; color:var(--dim); text-align:center; font-size:12px; }
  .toolcard { margin-top:8px; border:1px solid var(--border); border-left:3px solid var(--accent);
              border-radius:8px; overflow:hidden; font-size:12px; }
  .toolcard .th { padding:6px 10px; background:var(--panel2); color:var(--dim);
                  cursor:pointer; user-select:none; display:flex; justify-content:space-between; }
  .toolcard .tb { padding:8px 10px; background:var(--panel); display:none; white-space:pre-wrap;
                  word-break:break-word; color:var(--dim); font-family:Consolas, monospace; }
  .toolcard.open .tb { display:block; }
  .toolcard.ok { border-left-color:var(--ok); } .toolcard.err { border-left-color:var(--err); }
  .cursor { display:inline-block; width:8px; height:16px; background:var(--text);
            vertical-align:-2px; animation:blink 1s infinite; }
  @keyframes blink { 50% { opacity:0; } }
  #inputBar { display:flex; flex-direction:column; gap:8px; padding:10px 20px 14px; border-top:1px solid var(--border); }
  #inputRow { display:flex; gap:10px; }
  #input { flex:1; background:var(--panel2); border:1px solid var(--border); border-radius:10px;
           color:var(--text); padding:12px 14px; font-size:14px; outline:none; resize:none; height:50px; }
  #input:focus { border-color:var(--accent); }
  #send { width:70px; border:none; border-radius:10px; background:var(--accent); color:var(--on-accent); cursor:pointer; }
  #send:disabled { opacity:.5; cursor:not-allowed; }
  #stop { width:70px; border:none; border-radius:10px; background:rgba(255,107,107,.15); color:var(--err); cursor:pointer; }
  #stop:hover:not(:disabled) { background:rgba(255,107,107,.28); }
  #stop:disabled { opacity:.5; cursor:not-allowed; }
  #stop.hidden { display:none; }
  /* ---- 输入框上方的权限审批条 ---- */
  #askBar { display:flex; align-items:center; gap:10px; background:var(--panel2);
            border:1px solid var(--accent); border-radius:8px; padding:8px 12px; font-size:12px; }
  #askBar.hidden { display:none; }
  #askText { flex:1; color:var(--text); word-break:break-all; white-space:pre-wrap; }
  #askAllow, #askDeny { border:none; border-radius:6px; padding:6px 14px; font-size:12px;
                        cursor:pointer; color:var(--on-accent); flex-shrink:0; }
  #askAllow { background:var(--ok); }
  #askDeny { background:var(--err); }
  /* ---- 输入框上方的选项条(ask_user 交互选择) ---- */
  #chooseBar { background:var(--panel2); border:1px solid var(--accent); border-radius:8px;
               padding:8px 12px; font-size:12px; display:flex; flex-direction:column; gap:8px; }
  #chooseBar.hidden { display:none; }
  #choosePrompt { color:var(--text); word-break:break-all; white-space:pre-wrap; }
  #chooseOptions { display:flex; flex-wrap:wrap; gap:6px; }
  #chooseOptions .co { border:1px solid var(--border); background:var(--panel); color:var(--text);
                       border-radius:6px; padding:5px 12px; font-size:12px; cursor:pointer; }
  #chooseOptions .co:hover { border-color:var(--accent); background:var(--accent); color:var(--on-accent); }
  #chooseOther { display:flex; gap:8px; align-items:center; }
  #chooseText { flex:1; background:var(--panel); border:1px solid var(--border); color:var(--text);
                border-radius:6px; padding:5px 10px; font-size:12px; outline:none; }
  #chooseText:focus { border-color:var(--accent); }
  #chooseSubmit, #chooseCancel { border:none; border-radius:6px; padding:5px 12px; font-size:12px;
                                 cursor:pointer; color:var(--on-accent); flex-shrink:0; }
  #chooseSubmit { background:var(--accent); }
  #chooseCancel { background:var(--err); }
  /* ---- 斜杠命令自动补全 ---- */
  #slashMenu { background:var(--panel); border:1px solid var(--border); border-radius:8px;
               max-height:220px; overflow-y:auto; font-size:12px; }
  #slashMenu.hidden { display:none; }
  #slashMenu .si { padding:6px 12px; cursor:pointer; display:flex; justify-content:space-between;
                   gap:16px; color:var(--text); }
  #slashMenu .si:hover, #slashMenu .si.sel { background:var(--accent); color:var(--on-accent); }
  #slashMenu .sd { color:var(--dim); }
  #slashMenu .si.sel .sd { color:var(--on-accent); opacity:.8; }
  .badge { padding:2px 8px; border-radius:10px; font-size:11px; }
  .badge.ok { background:rgba(61,220,132,.15); color:var(--ok); }
  .badge.err { background:rgba(255,107,107,.15); color:var(--err); }
  /* ---- Markdown 渲染(assistant 气泡)+ 代码高亮 ---- */
  .msg.assistant .bubble p { margin:0 0 8px; } .msg.assistant .bubble p:last-child { margin-bottom:0; }
  .msg.assistant .bubble h1,.msg.assistant .bubble h2,.msg.assistant .bubble h3,.msg.assistant .bubble h4 { margin:10px 0 6px; line-height:1.3; }
  .msg.assistant .bubble ul,.msg.assistant .bubble ol { margin:0 0 8px 20px; }
  .msg.assistant .bubble li { margin:2px 0; }
  .msg.assistant .bubble blockquote { margin:6px 0; padding:2px 10px; border-left:3px solid var(--accent); color:var(--dim); }
  .msg.assistant .bubble a { color:var(--accent); text-decoration:none; } .msg.assistant .bubble a:hover { text-decoration:underline; }
  .msg.assistant .bubble hr { border:none; border-top:1px solid var(--border); margin:10px 0; }
  .msg.assistant .bubble code { font-family:Consolas,"Courier New",monospace; }
  .msg.assistant .bubble :not(pre) > code { background:var(--panel2); border:1px solid var(--border); border-radius:4px; padding:1px 5px; font-size:12.5px; color:var(--accent); }
  .msg.assistant .bubble pre.code { background:var(--panel2); border:1px solid var(--border); border-radius:8px; margin:8px 0; overflow:hidden; }
  .msg.assistant .bubble pre.code .code-head { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:4px 10px; font-size:11px; color:var(--dim); background:var(--panel); border-bottom:1px solid var(--border); }
  .msg.assistant .bubble pre.code .code-head span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .copy-code { border:1px solid var(--border); border-radius:4px; padding:1px 8px; font-size:11px; color:var(--dim); background:var(--panel2); cursor:pointer; flex-shrink:0; }
  .copy-code:hover { color:var(--accent); border-color:var(--accent); }
  .copy-code.ok { color:#fff; background:var(--accent); border-color:var(--accent); }
  .msg.assistant .bubble pre.code code { display:block; padding:10px 12px; overflow-x:auto; font-family:Consolas,"Courier New",monospace; font-size:12.5px; line-height:1.55; white-space:pre; }
  .tok-kw{color:#c678dd;} .tok-s{color:#98c379;} .tok-n{color:#d19a66;} .tok-c{color:#7a8194;font-style:italic;} .tok-fn{color:#61afef;} .tok-de{color:#e5c07b;}
  html[data-theme="light"] .tok-kw{color:#8250df;} html[data-theme="light"] .tok-s{color:#1a7f37;}
  html[data-theme="light"] .tok-n{color:#9a6700;} html[data-theme="light"] .tok-c{color:#6e7781;}
  html[data-theme="light"] .tok-fn{color:#0550ae;} html[data-theme="light"] .tok-de{color:#953800;}
  html[data-theme="warm"] .tok-kw{color:#7a3d8f;} html[data-theme="warm"] .tok-s{color:#3f6d2e;}
  html[data-theme="warm"] .tok-n{color:#8a5a1a;} html[data-theme="warm"] .tok-c{color:#8a8378;}
</style>
</head>
<body>
<div id="sidebar">
  <h1>coding_agent <span>编程智能体</span></h1>
  <button id="newBtn">＋ 新建会话</button>
  <input id="search" type="text" placeholder="搜索会话标题…" autocomplete="off">
  <div id="convList"></div>
  <div id="footer"></div>
</div>
<div id="main">
  <div id="toolbar">
    <span id="modelLabel"></span>
    <span id="permLabel"></span>
    <select id="permSelect">
      <option value="interactive">权限:交互(Web 下未知操作默认拒绝)</option>
      <option value="auto-approve">权限:自动放行</option>
      <option value="deny">权限:严格拒绝</option>
    </select>
    <select id="themeSelect" title="切换整体颜色风格">
      <option value="dark">主题:深色</option>
      <option value="light">主题:浅色</option>
      <option value="warm">主题:暖色护眼</option>
      <option value="nord">主题:夜间蓝</option>
      <option value="purple">主题:南大紫</option>
      <option value="blue">主题:软件蓝</option>
    </select>
    <select id="exportSel" title="导出当前会话为文件">
      <option value="">导出会话…</option>
      <option value="markdown">导出为 Markdown</option>
      <option value="json">导出为 JSON(原始历史)</option>
      <option value="text">导出为纯文本</option>
    </select>
    <button id="importBtn" title="从 JSON 文件恢复会话">导入会话</button>
    <input type="file" id="importFile" accept=".json,application/json" style="display:none">
    <button id="clearBtn">清空当前会话</button>
  </div>
  <div id="messages"></div>
  <div id="inputBar">
    <div id="askBar" class="hidden">
      <span id="askText"></span>
      <button id="askAllow">允许</button>
      <button id="askDeny">拒绝</button>
    </div>
    <div id="chooseBar" class="hidden">
      <span id="choosePrompt"></span>
      <div id="chooseOptions"></div>
      <div id="chooseOther">
        <input id="chooseText" placeholder="其他 / 自定义输入,回车提交"/>
        <button id="chooseSubmit">提交</button>
        <button id="chooseCancel">取消</button>
      </div>
    </div>
    <div id="slashMenu" class="hidden"></div>
    <div id="inputRow">
      <textarea id="input" placeholder="输入任务,回车发送;Shift+Enter 换行;输入 / 弹出命令"/></textarea>
      <button id="send">发送</button>
      <button id="stop" class="hidden">停止</button>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let state = { convs: [], cur: null, busy: false, permMode: "interactive", search: "",
              resendAt: null, turnOk: false, isSlash: false, renamingId: null };
let aborter = null; // 当前请求的 AbortController;「停止生成」中止 fetch 并 POST /api/stop
let slashCommands = [], slashOpen = false, slashIndex = 0, slashItems = [];
let askQueue = [];  // 待审批确认的 FIFO 队列(团队并行可能多个 pending)
let chooseQueue = [];  // 待用户选择的 FIFO 队列(团队并行可能多个 pending)

async function api(path, opts={}) {
  const r = await fetch(path, Object.assign({headers:{"Content-Type":"application/json"}}, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function refreshConfig() {
  try {
    const c = await api("/api/config");
    $("modelLabel").textContent = `模型: ${c.provider.model} · ${c.provider.base_url}`;
    $("footer").textContent = `工作区: ${c.workspace} | 工具: ${(c.tools||[]).length} 个`;
    slashCommands = parseSlashCmds(c.slash_commands);
  } catch(e) {}
}
async function refreshList() {
  state.convs = await api("/api/conversations");
  renderConvList();
}
function renderConvList() {
  if (state.renamingId) return;  // 重命名中不重建列表,避免内联输入框被刷新抹掉
  const list = $("convList"); list.innerHTML = "";
  const q = (state.search || "").trim().toLowerCase();
  state.convs.filter(c => !q || (c.title || "").toLowerCase().includes(q)).forEach(c => {
    const div = document.createElement("div");
    div.className = "conv" + (c.id === state.cur ? " active" : "");
    div.dataset.id = c.id;
    div.innerHTML = `<span class="t">${esc(c.title)}</span><button class="del">✕</button>`;
    div.onclick = () => openConv(c.id);
    div.querySelector(".del").onclick = async e => {
      e.stopPropagation();
      await api("/api/conversations/" + c.id, {method:"DELETE"});
      if (state.cur === c.id) { state.cur = null; $("messages").innerHTML = ""; }
      refreshList();
    };
    list.appendChild(div);
  });
}
function startRename(cid, convEl) {
  const t = convEl.querySelector(".t");
  if (!t) return;
  const input = document.createElement("input");
  input.className = "rename-input"; input.type = "text";
  input.value = t.textContent;
  t.replaceWith(input);
  state.renamingId = cid;
  input.focus(); input.select();
  let done = false;
  const finish = async save => {
    if (done) return; done = true;
    state.renamingId = null;
    const val = input.value.trim();
    if (save && val) {
      try { await api(`/api/conversations/${cid}/rename`,
                      {method:"POST", body: JSON.stringify({title: val})}); } catch(e) {}
    }
    refreshList();
  };
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}
async function openConv(id) {
  state.cur = id;
  state.resendAt = null; state.turnOk = false; state.isSlash = false;
  refreshList();
  clearAskBar(); clearChooseBar(); closeSlashMenu();
  currentMsg = null; currentBubble = null; roundStart = false;
  try {
    const data = await api("/api/conversations/" + id);
    $("messages").innerHTML = "";
    renderMessages(data.messages);
  } catch(e) {
    $("messages").innerHTML = "";
    addMsg("system", "加载会话失败: " + (e.message || e));
  }
}
async function newConv() {
  const c = await api("/api/conversations", {method:"POST", body: JSON.stringify({title:"新会话"})});
  await openConv(c.id);
}
function esc(s){ return (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

// ---- 斜杠命令自动补全(数据来自 /api/config 的 slash_commands) ----
function parseSlashCmds(list) {
  return (list || []).map(s => {
    const sp = s.indexOf(" - ");
    return { cmd: sp > 0 ? s.slice(1, sp) : s.slice(1),
             desc: sp > 0 ? s.slice(sp + 3) : "" };
  });
}
function slashAt(value, caret) {
  const before = value.slice(0, caret);
  const sp = Math.max(before.lastIndexOf(" "), before.lastIndexOf("\\n"));
  const token = before.slice(sp + 1);
  if (!token.startsWith("/")) return null;
  return { start: sp + 1, text: token.slice(1).toLowerCase() };
}
function renderSlashMenu() {
  const menu = $("slashMenu");
  if (!slashItems.length) { closeSlashMenu(); return; }
  menu.innerHTML = slashItems.map((c, i) =>
    `<div class="si${i === slashIndex ? " sel" : ""}" data-i="${i}"><span>/${esc(c.cmd)}</span><span class="sd">${esc(c.desc)}</span></div>`).join("");
  menu.classList.remove("hidden");
}
function openSlashMenu(tok) {
  slashItems = slashCommands.filter(c => !tok || c.cmd.startsWith(tok));
  slashIndex = 0;
  slashOpen = true;
  renderSlashMenu();
}
function closeSlashMenu() {
  slashOpen = false; slashItems = [];
  $("slashMenu").classList.add("hidden");
}
function selectSlash(i) {
  const item = slashItems[i];
  const input = $("input");
  const at = slashAt(input.value, input.selectionStart);
  if (!at || !item) { closeSlashMenu(); return; }
  const value = input.value;
  input.value = value.slice(0, at.start) + "/" + item.cmd + " " + value.slice(input.selectionStart);
  const pos = at.start + item.cmd.length + 2;
  input.setSelectionRange(pos, pos);
  closeSlashMenu();
  input.focus();
}

// ---- 权限审批条(agent 在 interactive 模式下请求确认时弹出) ----
function renderAskBar() {
  const bar = $("askBar");
  if (!askQueue.length) { bar.classList.add("hidden"); return; }
  $("askText").textContent = askQueue[0].question;
  bar.classList.remove("hidden");
}
function clearAskBar() {
  askQueue = [];
  renderAskBar();
}
async function respondAsk(allow) {
  if (!askQueue.length) return;
  const q = askQueue.shift();
  try {
    await api("/api/respond", {method:"POST",
      body: JSON.stringify({conversation_id: state.cur, id: q.id, allow})});
  } catch(e) {}
  renderAskBar();
}

// ---- 选项条(agent 调用 ask_user 让用户选择方向时弹出) ----
function renderChooseBar() {
  const bar = $("chooseBar");
  if (!chooseQueue.length) { bar.classList.add("hidden"); return; }
  const q = chooseQueue[0];
  $("choosePrompt").textContent = q.prompt;
  const box = $("chooseOptions"); box.innerHTML = "";
  (q.options || []).forEach((opt, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "co"; b.textContent = opt;
    b.onclick = () => respondChoose(i, null);
    box.appendChild(b);
  });
  $("chooseText").value = "";
  bar.classList.remove("hidden");
}
function clearChooseBar() {
  chooseQueue = [];
  renderChooseBar();
}
async function respondChoose(index, text) {
  if (!chooseQueue.length) return;
  const q = chooseQueue.shift();
  const body = {conversation_id: state.cur, id: q.id};
  if (index !== null && index !== undefined && index >= 0) body.index = index;
  else if (text !== null && text !== undefined && text !== "") body.text = text;
  else body.index = -1;
  try {
    await api("/api/choose", {method:"POST", body: JSON.stringify(body)});
  } catch(e) {}
  renderChooseBar();
}

// ---- 自写 Markdown 渲染 + 代码高亮(零外部依赖;所有文本先转义,杜绝注入) ----
function mdEscape(s){ return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function mdAttr(s){ return mdEscape(s).replace(/"/g,"&quot;"); }
const MD_LANG_TAGS = { python:"py", py:"py", javascript:"js", js:"js", typescript:"ts", ts:"ts",
  json:"json", yaml:"yaml", yml:"yaml", bash:"bash", sh:"bash", shell:"bash",
  sql:"sql", html:"html", xml:"html", css:"css", diff:"diff", text:"text", plaintext:"text" };
const MD_KEYWORDS = new Set(["def","class","import","from","return","if","elif","else","for","while",
  "try","except","finally","with","as","pass","break","continue","lambda","yield","global","nonlocal",
  "assert","raise","async","await","function","const","let","var","new","typeof","instanceof",
  "true","false","null","undefined","and","or","not","in","is","None","True","False","this","self",
  "export","default","interface","type","extends","implements","enum","switch","case","do","void",
  "public","private","protected","static","final","int","float","double","bool","str","list","dict",
  "tuple","set","print","declare","namespace","using"]);
function mdHighlight(codeEsc, lang) {
  if (!MD_LANG_TAGS[lang]) return codeEsc;
  const out = []; let i = 0, n = codeEsc.length;
  const isId = ch => /[A-Za-z0-9_]/.test(ch);
  while (i < n) {
    const c = codeEsc[i];
    if (c === '#') {
      let j = i; while (j < n && codeEsc[j] !== "\\n") j++;
      out.push('<span class="tok-c">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (codeEsc.startsWith('//', i)) {
      let j = i; while (j < n && codeEsc[j] !== "\\n") j++;
      out.push('<span class="tok-c">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (codeEsc.startsWith('/*', i)) {
      let j = codeEsc.indexOf('*/', i + 2); if (j < 0) j = n; else j += 2;
      out.push('<span class="tok-c">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      let j = i + 1; while (j < n && codeEsc[j] !== c && codeEsc[j] !== "\\n") j++;
      if (j < n && codeEsc[j] === c) j++;
      out.push('<span class="tok-s">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (c === '@') {
      let j = i + 1; while (j < n && isId(codeEsc[j])) j++;
      out.push('<span class="tok-de">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (c >= '0' && c <= '9') {
      let j = i; while (j < n && /[0-9A-Fa-f_.xX]/.test(codeEsc[j])) j++;
      out.push('<span class="tok-n">' + codeEsc.slice(i, j) + '</span>'); i = j; continue;
    }
    if (isId(c)) {
      let j = i; while (j < n && isId(codeEsc[j])) j++;
      const word = codeEsc.slice(i, j);
      if (MD_KEYWORDS.has(word)) out.push('<span class="tok-kw">' + word + '</span>');
      else if (codeEsc[j] === '(') out.push('<span class="tok-fn">' + word + '</span>');
      else out.push(word);
      i = j; continue;
    }
    out.push(c); i++;
  }
  return out.join('');
}
function mdInline(s) {
  const esc = mdEscape(s);
  const parts = esc.split(/`([^`\\n]+)`/);
  return parts.map((p, i) => {
    if (i % 2 === 1) return '<code>' + p + '</code>';
    p = p.replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, (m, txt, url) => {
      const u = url.replace(/["'<>]/g, "");
      if (!/^(https?:|mailto:|#)/i.test(u)) return m;
      return '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + mdEscape(txt) + '</a>';
    });
    p = p.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
    p = p.replace(/(^|[^\\w*])\\*([^*\\n]+)\\*(?=[^\\w*]|$)/g, '$1<em>$2</em>');
    return p;
  }).join('');
}
function mdRender(text) {
  const src = String(text || "").replace(/\\r\\n/g, "\\n");
  const lines = src.split("\\n");
  const html = [];
  let inCode = false, codeLang = "", codeBuf = [], para = [], listType = "", listBuf = [];
  const flushList = () => {
    if (listBuf.length) {
      const tag = listType === "ol" ? "ol" : "ul";
      html.push("<" + tag + ">" + listBuf.map(x => "<li>" + x + "</li>").join("") + "</" + tag + ">");
      listBuf = []; listType = "";
    }
  };
  const flushPara = () => {
    if (para.length) { html.push("<p>" + para.map(mdInline).join("<br>") + "</p>"); para = []; }
  };
  const flushCode = () => {
    if (inCode) {
      const tag = MD_LANG_TAGS[codeLang] || "text";
      const raw = codeBuf.join("\\n");
      const esc = mdEscape(raw);
      html.push('<pre class="code" data-code="' + mdAttr(raw) + '">' +
        '<div class="code-head"><span>' + mdEscape(codeLang || tag) + '</span>' +
        '<button class="copy-code" type="button">复制</button></div>' +
        '<code>' + mdHighlight(esc, codeLang) + '</code></pre>');
      codeBuf = []; codeLang = ""; inCode = false;
    }
  };
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const fence = line.match(/^\\s*(`{3,}|~{3,})\\s*([\\w+-]*)\\s*$/);
    if (fence) {
      if (!inCode) { flushPara(); flushList(); inCode = true; codeLang = fence[2]; codeBuf = []; }
      else { flushCode(); }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    const trimmed = line.trim();
    if (!trimmed) { flushPara(); flushList(); continue; }
    const h = line.match(/^(#{1,4})\\s+(.*)$/);
    if (h) { flushPara(); flushList(); const lvl = h[1].length; html.push("<h" + lvl + ">" + mdInline(h[2]) + "</h" + lvl + ">"); continue; }
    if (/^(-{3,}|\\*{3,}|_{3,})$/.test(trimmed)) { flushPara(); flushList(); html.push("<hr>"); continue; }
    if (trimmed.startsWith(">")) {
      flushPara(); flushList();
      html.push("<blockquote>" + mdInline(line.replace(/^\\s*>\\s?/, "")) + "</blockquote>");
      continue;
    }
    const li = line.match(/^\\s*([-*+]|\\d+\\.)\\s+(.*)$/);
    if (li) {
      const typ = li[1].match(/\\d+/) ? "ol" : "ul";
      if (listType !== typ) { flushList(); listType = typ; }
      listBuf.push(mdInline(li[2]));
      continue;
    }
    flushList();
    para.push(line);
  }
  flushCode(); flushPara(); flushList();
  return html.join("\\n");
}

function addMsg(role, text, idx) {
  const m = document.createElement("div");
  m.className = "msg " + role;
  if (idx != null) m.dataset.idx = idx;
  if (role === "user") {
    const u = document.createElement("button");
    u.className = "ubtn"; u.title = "编辑并重发"; u.type = "button"; u.textContent = "✎";
    u.onclick = () => editMessage(m);
    m.appendChild(u);
  }
  const b = document.createElement("div"); b.className = "bubble";
  if (role === "assistant") b.innerHTML = mdRender(text);
  else b.textContent = text;
  m.appendChild(b);
  $("messages").appendChild(m);
  $("messages").scrollTop = $("messages").scrollHeight;
  return m;
}
function addToolCard(parent, name, args, output, status) {
  const card = document.createElement("div");
  card.className = "toolcard open";
  card.innerHTML = `<div class="th"><span>⚙ ${esc(name)}</span><span class="badge ${status==="err"?"err":"ok"}">${esc(status||"ok")}</span></div>
                    <div class="tb">${esc(args)}${output ? "\\n\\n" + esc(output) : ""}</div>`;
  card.querySelector(".th").onclick = () => card.classList.toggle("open");
  (parent || $("messages")).appendChild(card);
  $("messages").scrollTop = $("messages").scrollHeight;
  return card;
}
function renderMessages(messages) {
  const wrap = $("messages"); wrap.innerHTML = "";
  let i = 0;
  (messages||[]).forEach(m => {
    if (m.role === "system") return;
    const idx = i++;
    if (m.role === "user") addMsg("user", m.content || "", idx);
    else if (m.role === "assistant") {
      const hasTools = !!(m.tool_calls && m.tool_calls.length);
      const msg = addMsg("assistant", m.content || (hasTools ? "(调用工具)" : ""), idx);
      if (hasTools) m.tool_calls.forEach(tc => addToolCard(msg, tc.function.name, tc.function.arguments, "", ""));
    } else if (m.role === "tool") {
      const last = wrap.querySelector(".toolcard:last-of-type");
      if (last) { last.classList.add(m.content.includes("失败") ? "err":"ok");
                  last.querySelector(".tb").textContent += "\\n\\n" + m.content; }
    }
  });
}

function editMessage(m) {
  const idx = +m.dataset.idx;
  if (Number.isNaN(idx) || state.busy) return;
  state.resendAt = idx;
  const bubble = m.querySelector(".bubble");
  const input = $("input");
  input.value = (bubble ? bubble.textContent : "");
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

async function reloadMessages() {
  if (!state.cur) return;
  try {
    const data = await api("/api/conversations/" + state.cur);
    $("messages").innerHTML = "";
    renderMessages(data.messages);
  } catch(e) {}
}

function copyCode(btn) {
  const pre = btn.closest("pre.code");
  const text = pre ? (pre.dataset.code || "") : "";
  const ok = () => {
    const old = btn.textContent;
    btn.textContent = "已复制"; btn.classList.add("ok");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("ok"); }, 1200);
  };
  const fallback = () => {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); ok(); } catch(e) {}
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(ok, fallback);
  } else fallback();
}

function parseSSE(data) {
  const out = []; let cur = null;
  for (const line of data.split("\\n")) {
    if (line.startsWith("event:")) cur = {event: line.slice(6).trim(), data: []};
    else if (line.startsWith("data:") && cur) cur.data.push(line.slice(5).trim());
    else if (!line && cur) { out.push({event: cur.event, data: cur.data.join("\\n")}); cur = null; }
  }
  if (cur) out.push({event: cur.event, data: cur.data.join("\\n")});
  return out;
}

// ---- 流式渲染:按"轮"归组,一段文本和紧随其后的工具调用放入同一消息块 ----
// 用 status("第 N 轮推理…") 作为轮次边界:每轮开头强制新消息块,
// 轮内的多个(并行)工具调用归入同一块。
// 关键:文本增量先攒进 pending,用 requestAnimationFrame 每帧批量刷一次 DOM 并滚动,
// 否则团队并行流式时逐 token 渲染会把页面拖死(浏览器提示"页面无响应")。
let currentMsg = null, currentBubble = null, roundStart = false;
let pendingBubble = null, flushScheduled = false;
function clearCursor() {
  if (currentBubble) { const c = currentBubble.querySelector(".cursor"); if (c) c.remove(); }
}
function ensureAssistantBubble(forceNew) {
  if (forceNew || !currentBubble || roundStart) {
    clearCursor();
    currentMsg = addMsg("assistant", "");
    currentBubble = currentMsg.querySelector(".bubble");
    currentBubble._md = "";
    roundStart = false;
  }
  return currentBubble;
}
function scheduleFlush() {
  if (flushScheduled) return;
  flushScheduled = true;
  requestAnimationFrame(flushPending);
}
function flushPending() {
  flushScheduled = false;
  if (pendingBubble) {
    const c = pendingBubble.querySelector(".cursor"); if (c) c.remove();
    // 流式下每帧对累积原文整体重渲染 Markdown,保证代码块/标题等随增量实时成形
    pendingBubble.innerHTML = mdRender(pendingBubble._md || "");
    const cursor = document.createElement("span"); cursor.className="cursor"; pendingBubble.appendChild(cursor);
    pendingBubble = null;
  }
  const wrap = $("messages");
  wrap.scrollTop = wrap.scrollHeight;
}

async function send() {
  const text = $("input").value.trim();
  if (!text || state.busy) return;
  if (!state.cur) await newConv();
  // 编辑重发:先把被编辑消息及其后所有已持久化节点从 DOM 移除
  if (state.resendAt != null) {
    [...$("messages").children].forEach(n => {
      const i = n.dataset.idx !== undefined ? +n.dataset.idx : -1;
      if (i >= state.resendAt) n.remove();
    });
  }
  const resend_at = state.resendAt;
  state.resendAt = null; state.isSlash = false; state.turnOk = false;
  $("input").value = ""; state.busy = true; $("send").disabled = true;
  $("stop").disabled = false; $("stop").textContent = "停止";
  $("stop").classList.remove("hidden");
  addMsg("user", text);
  currentMsg = null; currentBubble = null; roundStart = false;
  pendingBubble = null;
  const wrap = $("messages");
  let buf = "";
  aborter = new AbortController();
  try {
    const resp = await fetch("/api/chat", {method:"POST",
      headers:{"Content-Type":"application/json"},
      signal: aborter.signal,
      body: JSON.stringify({conversation_id: state.cur, message: text, permission_mode: state.permMode,
                            resend_at: resend_at})});
    const reader = resp.body.getReader(); const dec = new TextDecoder();
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let idx;
      while ((idx = buf.indexOf("\\n\\n")) !== -1) {
        const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
        for (const ev of parseSSE(block)) handleEvent(ev, wrap);
      }
    }
  } catch(e) {
    if (e.name === "AbortError") {
      ensureAssistantBubble(); currentBubble._md += "\\n⏹ 已停止生成"; scheduleFlush();
    } else {
      ensureAssistantBubble(); currentBubble._md += "\\n请求失败: " + e.message; scheduleFlush();
    }
  }
  clearCursor(); state.busy = false; $("send").disabled = false;
  $("stop").classList.add("hidden");
  aborter = null;
}

function handleEvent(ev, wrap) {
  let d; try { d = JSON.parse(ev.data); } catch { d = {}; }
  switch (ev.event) {
    case "text": {
      pendingBubble = ensureAssistantBubble();
      pendingBubble._md += (d.delta || "");
      scheduleFlush();
      break; }
    case "tool_call":
      ensureAssistantBubble();
      if (!currentBubble._md.trim()) currentBubble._md = "(调用工具)";
      addToolCard(currentMsg, d.name, JSON.stringify(d.arguments||{}), "", d.status);
      clearCursor();
      break;
    case "tool_result": {
      const cards = currentMsg ? currentMsg.querySelectorAll(".toolcard") : [];
      const last = cards[cards.length-1];
      if (last) { last.classList.add(d.success ? "ok" : "err");
                  last.querySelector(".tb").textContent += "\\n\\n" + (d.output || d.error || ""); }
      break; }
    case "status": { roundStart = true;
                     const s = document.createElement("div");
                     s.className="msg system"; s.innerHTML=`<div class="bubble">${esc(d.message||"")}</div>`;
                     wrap.appendChild(s); wrap.scrollTop = wrap.scrollHeight; break; }
    case "ask":
      askQueue.push({id: d.id, question: d.question});
      renderAskBar();
      break;
    case "choose":
      chooseQueue.push({id: d.id, prompt: d.prompt, options: d.options});
      renderChooseBar();
      break;
    case "meta":
      if (d.type === "slash") state.isSlash = true;
      break;
    case "turn_end":
      state.turnOk = !!d.success;
      break;
    case "error": clearAskBar(); clearChooseBar(); ensureAssistantBubble(); currentBubble._md += "\\n✗ " + (d.message || ""); break;
    case "done":
      clearAskBar(); clearChooseBar();
      // 成功回合 → 从持久化历史整体重渲染,让消息节点带真实索引(编辑重发依赖)
      // 斜杠命令输入输出现已持久化,同样重渲染以便立即呈现(而非等下次刷新)
      if (state.turnOk || state.isSlash) reloadMessages();
      refreshList();
      break;
  }
  scheduleFlush();
}

async function stopGenerate() {
  if (!aborter) return;
  $("stop").disabled = true; $("stop").textContent = "停止中…";
  clearAskBar(); clearChooseBar();
  // 先让后端 agent 尽快中断(置位 stop_event),再中止前端 fetch,双保险
  try { await api("/api/stop", {method:"POST", body: JSON.stringify({conversation_id: state.cur})}); }
  catch(e) {}
  if (aborter) aborter.abort();
}
$("stop").onclick = stopGenerate;
$("messages").addEventListener("click", e => {
  const b = e.target.closest(".copy-code");
  if (b) copyCode(b);
});
$("send").onclick = send;
$("input").addEventListener("keydown", e => {
  if (slashOpen) {
    if (e.key === "ArrowDown") { e.preventDefault(); slashIndex = (slashIndex + 1) % slashItems.length; renderSlashMenu(); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); slashIndex = (slashIndex - 1 + slashItems.length) % slashItems.length; renderSlashMenu(); return; }
    if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); selectSlash(slashIndex); return; }
    if (e.key === "Escape") { e.preventDefault(); closeSlashMenu(); return; }
  }
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("input").addEventListener("input", e => {
  const at = slashAt($("input").value, $("input").selectionStart);
  if (at !== null) openSlashMenu(at.text);
  else closeSlashMenu();
});
$("input").addEventListener("blur", () => setTimeout(closeSlashMenu, 150));
$("slashMenu").onclick = e => {
  const div = e.target.closest(".si");
  if (div) selectSlash(+div.dataset.i);
};
$("askAllow").onclick = () => respondAsk(true);
$("askDeny").onclick = () => respondAsk(false);
$("chooseSubmit").onclick = () => respondChoose(null, $("chooseText").value.trim());
$("chooseCancel").onclick = () => respondChoose(-1, null);
$("chooseText").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); respondChoose(null, $("chooseText").value.trim()); }
});
$("search").addEventListener("input", e => {
  state.search = e.target.value;
  renderConvList();
});
$("convList").addEventListener("dblclick", e => {
  if (e.target.closest(".del")) return;
  const conv = e.target.closest(".conv");
  if (conv) startRename(conv.dataset.id, conv);
});
$("newBtn").onclick = newConv;
$("clearBtn").onclick = async () => { await sendSlash("/clear"); };
$("exportSel").onchange = e => {
  const f = e.target.value;
  if (f && state.cur) {
    const a = document.createElement("a");
    a.href = `/api/conversations/${state.cur}/export?format=${f}`;
    document.body.appendChild(a); a.click(); a.remove();
  }
  e.target.value = "";
};
$("importBtn").onclick = () => $("importFile").click();
$("importFile").onchange = async e => {
  const f = e.target.files[0];
  e.target.value = "";               // 允许再次选择同一文件
  if (!f) return;
  try {
    const text = await f.text();
    const meta = await api("/api/conversations/import", {method:"POST", body: text});
    await refreshList();
    await openConv(meta.id);
    addMsg("system", "已导入会话: " + meta.title);
  } catch(err) {
    addMsg("system", "导入失败: " + (err.message || err));
  }
};
$("permSelect").onchange = e => state.permMode = e.target.value;
const THEMES = {dark:"深色", light:"浅色", warm:"暖色护眼", nord:"夜间蓝", purple:"南大紫", blue:"软件蓝"};
function applyTheme(name) {
  if (!THEMES[name]) name = "dark";
  document.documentElement.dataset.theme = name;
  if ($("themeSelect").value !== name) $("themeSelect").value = name;
  try { localStorage.setItem("coding_agent_theme", name); } catch(e) {}
}
$("themeSelect").onchange = e => applyTheme(e.target.value);
async function sendSlash(cmd) {
  if (!state.cur) await newConv();
  addMsg("user", cmd);
  const msg = addMsg("assistant", "");
  const bub = msg.querySelector(".bubble"); bub._md = "";
  const r = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({conversation_id: state.cur, message: cmd})});
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf="";
  while (true) { const {done,value}=await reader.read(); if(done) break;
    buf += dec.decode(value,{stream:true}); let i;
    while((i=buf.indexOf("\\n\\n"))!==-1){const bl=buf.slice(0,i);buf=buf.slice(i+2);
      for(const ev of parseSSE(bl)){if(ev.event==="text"){let d=JSON.parse(ev.data);bub._md+=d.delta||"";bub.innerHTML=mdRender(bub._md);}}} }
}
async function init() {
  let saved = "dark";
  try { saved = localStorage.getItem("coding_agent_theme") || "dark"; } catch(e) {}
  applyTheme(saved);
  await refreshConfig(); await refreshList();
  const convs = state.convs;
  if (convs.length) await openConv(convs[0].id);
}
init();
</script>
</body>
</html>
"""
