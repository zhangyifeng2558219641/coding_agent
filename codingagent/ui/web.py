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
            # 斜杠命令(尤其 /team 这类长任务)也在 worker 线程执行并实时下发队列事件,
            # 否则会阻塞事件循环,直到整个命令跑完才一次性吐出结果(看起来"卡住后一大串")。
            slash_holder: dict[str, Any] = {}

            def slash_work() -> None:
                try:
                    agent = session.make_agent(history=history, ui=ui,
                                               permission_mode=body.permission_mode)
                    ctx = session.context(agent)
                    slash_holder["resp"] = session.slash.run(
                        body.message[1:].partition(" ")[0],
                        body.message[1:].partition(" ")[2].strip(), ctx)
                except Exception as e:  # pragma: no cover
                    slash_holder["error"] = str(e)

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
  .msg.user .bubble { background:var(--accent); color:var(--on-accent); display:inline-block; text-align:left; }
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
  #inputBar { display:flex; gap:10px; padding:14px 20px; border-top:1px solid var(--border); }
  #input { flex:1; background:var(--panel2); border:1px solid var(--border); border-radius:10px;
           color:var(--text); padding:12px 14px; font-size:14px; outline:none; resize:none; height:50px; }
  #input:focus { border-color:var(--accent); }
  #send { width:70px; border:none; border-radius:10px; background:var(--accent); color:var(--on-accent); cursor:pointer; }
  #send:disabled { opacity:.5; cursor:not-allowed; }
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
  .msg.assistant .bubble pre.code .code-head { padding:4px 10px; font-size:11px; color:var(--dim); background:var(--panel); border-bottom:1px solid var(--border); }
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
async function openConv(id) {
  state.cur = id;
  refreshList();
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

// ---- 自写 Markdown 渲染 + 代码高亮(零外部依赖;所有文本先转义,杜绝注入) ----
function mdEscape(s){ return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
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
      const esc = mdEscape(codeBuf.join("\\n"));
      html.push('<pre class="code"><div class="code-head">' + mdEscape(codeLang || tag) + '</div><code>' + mdHighlight(esc, codeLang) + '</code></pre>');
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

function addMsg(role, text) {
  const m = document.createElement("div");
  m.className = "msg " + role;
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
  $("input").value = ""; state.busy = true; $("send").disabled = true;
  addMsg("user", text);
  currentMsg = null; currentBubble = null; roundStart = false;
  pendingBubble = null;
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
    ensureAssistantBubble(); currentBubble._md += "\\n请求失败: " + e.message; scheduleFlush();
  }
  clearCursor(); state.busy = false; $("send").disabled = false;
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
    case "error": ensureAssistantBubble(); currentBubble._md += "\\n✗ " + (d.message || ""); break;
    case "done": refreshList(); break;
  }
  scheduleFlush();
}

$("send").onclick = send;
$("input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("newBtn").onclick = newConv;
$("clearBtn").onclick = async () => { await sendSlash("/clear"); };
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
