"""网页端(FastAPI + SSE):对话管理 + 流式输出,非终端交互方式。

单进程单工作区;会话列表与会话历史持久化到 .coding_agent/sessions/。
POST /api/chat 以 SSE 流式返回事件:start / text / tool_call / tool_result /
status / compact / turn_end / error / done。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..agent.loop import UISink
from ..session import Session


# ---------------------------------------------------------------------------
# 会话存储
# ---------------------------------------------------------------------------

class ChatBody(BaseModel):
    conversation_id: str
    message: str
    permission_mode: Optional[str] = None
    model: Optional[str] = None


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
        now = datetime.now().isoformat(timespec="seconds")
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
            self._meta[cid]["updated_at"] = datetime.now().isoformat(timespec="seconds")
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
    def __init__(self, emit):
        self._emit = emit  # (type, data) -> None,线程安全

    def event(self, type: str, data: dict[str, Any]) -> None:
        self._emit(type, data)

    def ask(self, question: str) -> bool:
        # Web 无交互确认能力:由权限策略(mode)决定,ASL 一律拒绝
        return False


def _sse(type: str, data: dict[str, Any]) -> str:
    return f"event: {type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _default_title(message: str) -> str:
    msg = message.strip().replace("\n", " ")
    return msg[:24] + ("…" if len(msg) > 24 else "")


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

    @app.post("/api/chat")
    async def chat(body: ChatBody):
        if not body.message.strip():
            raise HTTPException(400, "消息为空")
        meta = store.get(body.conversation_id)
        if not meta:
            meta = store.create()
        if not meta["title"] or meta["title"] == "新会话":
            store.touch(body.conversation_id, _default_title(body.message))

        # 装载/恢复该会话的独立历史(新会话新建,互不共享)
        history = session.load_history(body.conversation_id)
        if history is None:
            from ..llm import History
            history = History(
                budget_tokens=session.config.context.get("budget_tokens", 64000),
                max_tool_output=session.config.context.get("max_tool_output", 30000),
            )

        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        ui = SSEUI(lambda t, d: loop.call_soon_threadsafe(q.put_nowait, (t, d)))

        if body.message.startswith("/"):
            async def slash_stream():
                yield _sse("meta", {"type": "slash", "command": body.message})
                agent = session.make_agent(history=history, ui=ui,
                                           permission_mode=body.permission_mode)
                ctx = session.context(agent)
                try:
                    resp = session.slash.run(body.message[1:].partition(" ")[0],
                                             body.message[1:].partition(" ")[2].strip(), ctx)
                except Exception as e:
                    resp = f"命令执行失败: {e}"
                yield _sse("text", {"delta": resp or "(无输出)"})
                yield _sse("done", {"conversation_id": body.conversation_id})
            return StreamingResponse(slash_stream(), media_type="text/event-stream")

        result_holder: dict[str, Any] = {}

        def work() -> None:
            try:
                agent = session.make_agent(history=history, ui=ui,
                                           permission_mode=body.permission_mode)
                if body.model:
                    agent.client.model = body.model
                result_holder["result"] = agent.run(body.message)
                session.save_history(history, body.conversation_id)
            except Exception as e:  # pragma: no cover
                result_holder["error"] = str(e)

        async def stream():
            yield _sse("start", {"conversation_id": body.conversation_id})
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            while thread.is_alive() or not q.empty():
                try:
                    t, d = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                yield _sse(t, d)
            while not q.empty():
                t, d = q.get_nowait()
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
          --dim:#8a90a3; --accent:#5b8cff; --border:#2a2f3d; --ok:#3ddc84; --err:#ff6b6b; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:"Segoe UI", system-ui, "Microsoft YaHei", sans-serif;
         display:flex; height:100vh; overflow:hidden; }
  #sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border);
             display:flex; flex-direction:column; flex-shrink:0; }
  #sidebar h1 { font-size:15px; padding:16px 14px; letter-spacing:.5px; }
  #sidebar h1 span { color:var(--accent); }
  #newBtn { margin:0 12px 10px; padding:9px; background:var(--accent); border:none; border-radius:8px;
            color:#fff; font-size:13px; cursor:pointer; }
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
  .msg.user { text-align:right; }
  .msg.user .bubble { background:var(--accent); color:#fff; display:inline-block; text-align:left; }
  .msg.assistant .bubble { background:var(--panel); border:1px solid var(--border); }
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
  #inputBar { display:flex; gap:10px; padding:14px 20px; border-top:1px solid var(--border); }
  #input { flex:1; background:var(--panel2); border:1px solid var(--border); border-radius:10px;
           color:var(--text); padding:12px 14px; font-size:14px; outline:none; resize:none; height:50px; }
  #input:focus { border-color:var(--accent); }
  #send { width:70px; border:none; border-radius:10px; background:var(--accent); color:#fff; cursor:pointer; }
  #send:disabled { opacity:.5; cursor:not-allowed; }
  .badge { padding:2px 8px; border-radius:10px; font-size:11px; }
  .badge.ok { background:rgba(61,220,132,.15); color:var(--ok); }
  .badge.err { background:rgba(255,107,107,.15); color:var(--err); }
</style>
</head>
<body>
<div id="sidebar">
  <h1>coding_agent <span>编程智能体</span></h1>
  <button id="newBtn">＋ 新建会话</button>
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
    <button id="clearBtn">清空当前会话</button>
  </div>
  <div id="messages"></div>
  <div id="inputBar">
    <textarea id="input" placeholder="输入任务,回车发送;Shift+Enter 换行;/help 查看命令"></textarea>
    <button id="send">发送</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let state = { convs: [], cur: null, busy: false, permMode: "interactive" };

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
  } catch(e) {}
}
async function refreshList() {
  state.convs = await api("/api/conversations");
  const list = $("convList"); list.innerHTML = "";
  state.convs.forEach(c => {
    const div = document.createElement("div");
    div.className = "conv" + (c.id === state.cur ? " active" : "");
    div.innerHTML = `<span class="t">${esc(c.title)}</span><button class="del">✕</button>`;
    div.querySelector(".t").onclick = () => openConv(c.id);
    div.querySelector(".del").onclick = async e => {
      e.stopPropagation();
      await api("/api/conversations/" + c.id, {method:"DELETE"});
      if (state.cur === c.id) { state.cur = null; $("messages").innerHTML = ""; }
      refreshList();
    };
    list.appendChild(div);
  });
}
async function openConv(id) {
  state.cur = id;
  refreshList();
  const data = await api("/api/conversations/" + id);
  $("messages").innerHTML = "";
  renderMessages(data.messages);
}
async function newConv() {
  const c = await api("/api/conversations", {method:"POST", body: JSON.stringify({title:"新会话"})});
  await openConv(c.id);
}
function esc(s){ return (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

function addMsg(role, text) {
  const m = document.createElement("div");
  m.className = "msg " + role;
  const b = document.createElement("div"); b.className = "bubble";
  b.textContent = text; m.appendChild(b);
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
  (messages||[]).forEach(m => {
    if (m.role === "user") addMsg("user", m.content || "");
    else if (m.role === "assistant") {
      const hasTools = !!(m.tool_calls && m.tool_calls.length);
      const msg = addMsg("assistant", m.content || (hasTools ? "(调用工具)" : ""));
      if (hasTools) m.tool_calls.forEach(tc => addToolCard(msg, tc.function.name, tc.function.arguments, "", ""));
    } else if (m.role === "tool") {
      const last = wrap.querySelector(".toolcard:last-of-type");
      if (last) { last.classList.add(m.content.includes("失败") ? "err":"ok");
                  last.querySelector(".tb").textContent += "\\n\\n" + m.content; }
    }
  });
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
let currentMsg = null, currentBubble = null, roundStart = false;
function clearCursor() {
  if (currentBubble) { const c = currentBubble.querySelector(".cursor"); if (c) c.remove(); }
}
function ensureAssistantBubble(forceNew) {
  if (forceNew || !currentBubble || roundStart) {
    clearCursor();
    currentMsg = addMsg("assistant", "");
    currentBubble = currentMsg.querySelector(".bubble");
    roundStart = false;
  }
  return currentBubble;
}

async function send() {
  const text = $("input").value.trim();
  if (!text || state.busy) return;
  if (!state.cur) await newConv();
  $("input").value = ""; state.busy = true; $("send").disabled = true;
  addMsg("user", text);
  currentMsg = null; currentBubble = null; roundStart = false;
  const wrap = $("messages");
  let buf = "";
  try {
    const resp = await fetch("/api/chat", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({conversation_id: state.cur, message: text, permission_mode: state.permMode})});
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
    ensureAssistantBubble().textContent += "\\n请求失败: " + e.message;
  }
  clearCursor(); state.busy = false; $("send").disabled = false;
}

function handleEvent(ev, wrap) {
  let d; try { d = JSON.parse(ev.data); } catch { d = {}; }
  switch (ev.event) {
    case "text": {
      const b = ensureAssistantBubble();
      clearCursor();
      b.textContent += (d.delta || "");
      const cursor = document.createElement("span"); cursor.className="cursor"; b.appendChild(cursor);
      break; }
    case "tool_call":
      ensureAssistantBubble();
      if (!currentBubble.textContent.trim()) currentBubble.textContent = "(调用工具)";
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
    case "error": ensureAssistantBubble().textContent += "\\n✗ " + (d.message || ""); break;
    case "done": refreshList(); break;
  }
  wrap.scrollTop = wrap.scrollHeight;
}

$("send").onclick = send;
$("input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("newBtn").onclick = newConv;
$("clearBtn").onclick = async () => { await sendSlash("/clear"); };
$("permSelect").onchange = e => state.permMode = e.target.value;
async function sendSlash(cmd) {
  if (!state.cur) await newConv();
  addMsg("user", cmd);
  const bubble = addMsg("assistant", "");
  const r = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({conversation_id: state.cur, message: cmd})});
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf="";
  while (true) { const {done,value}=await reader.read(); if(done) break;
    buf += dec.decode(value,{stream:true}); let i;
    while((i=buf.indexOf("\\n\\n"))!==-1){const bl=buf.slice(0,i);buf=buf.slice(i+2);
      for(const ev of parseSSE(bl)){if(ev.event==="text"){let d=JSON.parse(ev.data);bubble.textContent+=d.delta||"";}}} }
}
async function init() {
  await refreshConfig(); await refreshList();
  const convs = state.convs;
  if (convs.length) await openConv(convs[0].id);
}
init();
</script>
</body>
</html>
"""
