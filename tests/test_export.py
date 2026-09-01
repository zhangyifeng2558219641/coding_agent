"""会话导出纯函数测试:Markdown / 纯文本对消息历史的排版。"""

from __future__ import annotations

from codingagent.ui.export import conversation_to_markdown, conversation_to_text

META = {"id": "abc", "title": "测试会话", "created_at": "2026-09-01T10:00:00"}


def _sample_messages():
    return [
        {"role": "user", "content": "请读取 a.py"},
        {"role": "assistant", "content": "我先读取文件。", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "ReadFile", "arguments": '{"path": "a.py"}'}}]},
        {"role": "tool", "content": "def foo():\n    return 1\n", "name": "ReadFile", "tool_call_id": "1"},
        {"role": "assistant", "content": "读完了,内容是 def foo。"},
    ]


def test_markdown_renders_roles_and_tools():
    md = conversation_to_markdown(META, _sample_messages())
    assert md.startswith("# 测试会话")
    assert "创建时间:2026-09-01T10:00:00" in md
    assert "## 用户" in md and "请读取 a.py" in md
    assert "## 助手" in md and "我先读取文件。" in md
    assert "**调用的工具:**" in md
    assert "ReadFile" in md and '"path": "a.py"' in md
    assert "**工具结果(ReadFile):**" in md
    assert "def foo()" in md
    assert "读完了" in md


def test_text_renders_roles_and_tools():
    txt = conversation_to_text(META, _sample_messages())
    assert txt.startswith("会话: 测试会话")
    assert "【用户】请读取 a.py" in txt
    assert "【助手】我先读取文件。" in txt
    assert "[调用工具] ReadFile" in txt
    assert "[工具结果(ReadFile)]" in txt
    assert "def foo()" in txt


def test_empty_and_unknown_roles_safe():
    msgs = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "", "name": "Bash"},
    ]
    md = conversation_to_markdown(META, msgs)
    assert "_（空消息）_" in md and "工具结果(Bash)" in md
    txt = conversation_to_text(META, msgs)
    assert "【用户】" in txt and "[工具结果(Bash)] (空)" in txt


def test_output_ends_with_newline():
    md = conversation_to_markdown(META, _sample_messages())
    txt = conversation_to_text(META, _sample_messages())
    assert md.endswith("\n") and txt.endswith("\n")
    assert not md.endswith("\n\n")
