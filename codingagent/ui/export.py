"""会话导出:把一段会话历史转成可读的 Markdown / 纯文本。

消息结构沿用 History 的持久化格式(见 llm/history.py):
  user       {"role": "user", "content": ...}
  assistant  {"role": "assistant", "content": ..., "tool_calls": [{"function": {"name", "arguments"}}]}
  tool       {"role": "tool", "content": ..., "name": ...}

导出只做展示/备份:不丢内容,也不做任何转义(原文即用户所见)。
"""

from __future__ import annotations

from typing import Any


def _tool_calls_list(m: dict[str, Any]) -> list[dict[str, Any]]:
    return m.get("tool_calls") or []


def _tool_names(messages: list[dict[str, Any]]) -> dict[str, str]:
    """tool_call_id → 工具名(历史里的 tool 消息不存 name,需向前在 assistant 的 tool_calls 里找)。"""
    names: dict[str, str] = {}
    for m in messages:
        for tc in _tool_calls_list(m):
            fn = tc.get("function") or {}
            cid = tc.get("id") or tc.get("tool_call_id")
            if cid:
                names[str(cid)] = fn.get("name") or "工具"
    return names


def _tool_name(m: dict[str, Any], names: dict[str, str]) -> str:
    return names.get(str(m.get("tool_call_id") or ""), m.get("name") or "工具")


def conversation_to_markdown(meta: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    """整段会话 → 可读 Markdown 转写(标题 + 时间 + 分节消息)。"""
    names = _tool_names(messages)
    out: list[str] = [f"# {meta.get('title') or '未命名会话'}", ""]
    if meta.get("created_at"):
        out.append(f"- 创建时间:{meta['created_at']}")
    if meta.get("updated_at"):
        out.append(f"- 更新时间:{meta['updated_at']}")
    out.append("")

    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "user":
            out += ["## 用户", "", content or "_（空消息）_", ""]
        elif role == "assistant":
            calls = _tool_calls_list(m)
            if content:
                out += ["## 助手", "", content, ""]
            if calls:
                out += ["**调用的工具:**", ""]
                for tc in calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or "工具"
                    args = fn.get("arguments") or "{}"
                    out.append(f"- ⚙ `{name}({args})`")
        elif role == "tool":
            name = _tool_name(m, names)
            out += ["", f"**工具结果({name}):**", "", "```", content or "(空)", "```", ""]

    return "\n".join(out).rstrip() + "\n"


def conversation_to_text(meta: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    """整段会话 → 无格式纯文本转写(便于直接粘贴到聊天/邮件)。"""
    names = _tool_names(messages)
    out: list[str] = [f"会话: {meta.get('title') or '未命名会话'}"]
    if meta.get("created_at"):
        out.append(f"创建:{meta['created_at']}")
    out.append("=" * 24)
    out.append("")

    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "user":
            out += [f"【用户】{content}" if content else "【用户】", ""]
        elif role == "assistant":
            if content:
                out += [f"【助手】{content}", ""]
            for tc in _tool_calls_list(m):
                fn = tc.get("function") or {}
                name = fn.get("name") or "工具"
                args = fn.get("arguments") or "{}"
                out.append(f"  [调用工具] {name}({args})")
        elif role == "tool":
            name = _tool_name(m, names)
            out += [f"  [工具结果({name})] {content or '(空)'}", ""]

    return "\n".join(out).rstrip() + "\n"
