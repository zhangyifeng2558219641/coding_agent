"""LLM 客户端 SSE 解析测试:重点覆盖"单次响应多个并行 tool_calls"的累积。

真实网关在流式返回多个工具调用时,各调用的 id/name/arguments 分片交错到达,
必须按 index 归并,而不能对 dict 排序(此前 bug:TypeError dict < dict)。
"""

from __future__ import annotations

import threading

from codingagent.agent import AgentLoop, PermissionPolicy
from codingagent.llm import ChatResponse, ChatClient, StreamEvent
from codingagent.tools import default_registry
from codingagent.types import ToolCall, Usage
from conftest import make_config


class FakeResp:
    """模拟 requests.Response 的流式读取(SSE 逐行)。"""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode: bool = True):
        yield from self._lines

    def close(self):
        self.closed = True


def _make_client(fake: FakeResp) -> ChatClient:
    client = ChatClient(base_url="https://mock", api_key="k", model="mock")
    client._do_request = lambda *a, **k: fake  # 拦截真实网络
    return client


def test_client_stream_stop_event_before_call():
    """stop_event 预先置位:不发请求,直接以 error 事件收尾(Web「停止生成」尽早中断)。"""
    seen = {"do_request": False}
    client = ChatClient(base_url="https://mock", api_key="k", model="mock")
    def fake_do_request(*a, **k):
        seen["do_request"] = True
        return FakeResp([])
    client._do_request = fake_do_request
    ev = threading.Event(); ev.set()
    events = list(client.chat_stream([], [], stop_event=ev))
    assert not seen["do_request"]
    assert [e.type for e in events] == ["error"]
    assert events[0].message == "用户中断"


def test_client_stream_aborts_mid_stream_on_stop():
    """流式中途置位 stop_event:关闭连接、立即以 error 收尾,不再拉取剩余内容。"""
    lines = [
        'data: {"choices":[{"index":0,"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"index":0,"delta":{"content":"世界"}}]}',
        'data: {"choices":[{"index":0,"delta":{"content":"。"}}]}',
        'data: [DONE]',
    ]
    resp = FakeResp(lines)
    client = ChatClient(base_url="https://mock", api_key="k", model="mock")
    client._do_request = lambda *a, **k: resp
    ev = threading.Event()
    gen = client.chat_stream([], [], stop_event=ev)
    first = next(gen)
    assert first.type == "text" and first.text == "你好"
    ev.set()
    rest = list(gen)
    assert resp.closed                       # 底层连接被关闭
    assert [e.type for e in rest] == ["error"]
    assert rest[0].message == "用户中断"


def test_two_parallel_tool_calls_interleaved():
    """两个工具调用分片交错到达,应按 index 归并且不抛错。"""
    lines = [
        'data: {"id":"1","choices":[{"index":0,"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"c0",'
        '"function":{"name":"Glob","arguments":"{\\"pat"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"c1",'
        '"function":{"name":"ReadFile","arguments":"{\\"pa"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"tern\\":\\"*.py\\"}"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":1,'
        '"function":{"arguments":"th\\":\\"a.py\\"}"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        'data: [DONE]',
    ]
    client = _make_client(FakeResp(lines))

    calls: list[ToolCall] = []
    for ev in client.chat_stream([], []):
        if ev.type == "tool_calls":
            calls = ev.calls

    assert len(calls) == 2
    assert [c.name for c in calls] == ["Glob", "ReadFile"]
    assert calls[0].arguments == {"pattern": "*.py"}
    assert calls[1].arguments == {"path": "a.py"}


class ParallelClient(ChatClient):
    """第一轮返回两个并行工具调用,后续轮返回最终答复(模拟真实流式)。"""

    def __init__(self):
        super().__init__(base_url="https://mock", api_key="k", model="mock")
        self._round = 0

    def chat_stream(self, messages, tools=None, **kw):
        self._round += 1
        if self._round == 1:
            yield StreamEvent(type="text", text="先看目录和文件。")
            yield StreamEvent(type="tool_calls", calls=[
                ToolCall(id="c0", name="Glob", arguments={"pattern": "*.py"}),
                ToolCall(id="c1", name="ReadFile", arguments={"path": "a.py"}),
            ])
            yield StreamEvent(type="finish", reason="tool_calls")
        else:
            yield StreamEvent(type="text", text="已看完目录与文件。")
            yield StreamEvent(type="finish", reason="stop")

    def chat(self, messages, **kw):
        return ChatResponse(content="(mock)", usage=Usage())


def test_loop_executes_parallel_tool_calls(workspace):
    """Agent 循环单轮收到多个并行工具调用,应逐一执行而不崩溃。"""
    config = make_config(workspace)
    reg = default_registry(with_memory=True, with_agent_tools=False)
    agent = AgentLoop(config, workspace, ParallelClient(), reg,
                      permissions=PermissionPolicy(
                          {**config.permissions, "mode": "auto-approve"}, workspace))
    result = agent.run("先看目录和文件")

    assert result.success
    assert len(result.tool_history) == 2
    assert {h["name"] for h in result.tool_history} == {"Glob", "ReadFile"}


def test_tool_messages_carry_matching_tool_call_id(workspace):
    """发给模型的 tool 消息必须带与 assistant tool_calls 对应的 tool_call_id。

    回归:此前工具返回的 ToolResult 不带 call_id,导致 tool_call_id 为空串,
    DeepSeek 会回 HTTP 400(\"must be followed by tool messages responding to
    each tool_call_id\"),回合静默终止且无报错。
    """
    from conftest import make_agent
    from codingagent.types import ToolCall

    config = make_config(workspace)
    agent = make_agent(config, workspace, [
        ("先找文件。", [
            ToolCall(id="t0", name="Glob", arguments={"pattern": "*.py"}),
            ToolCall(id="t1", name="ReadFile", arguments={"path": "a.py"}),
        ]),
        ("已看完。", []),
    ])
    result = agent.run("找文件并读取")

    assert result.success
    msgs = agent.conversation_messages
    assistant_ids = []
    for m in msgs:
        for tc in (m.get("tool_calls") or []):
            assistant_ids.append(tc["id"])
    tool_ids = [m["tool_call_id"] for m in msgs if m.get("role") == "tool"]

    assert assistant_ids == ["t0", "t1"]
    assert tool_ids == ["t0", "t1"]       # 必须一一对应,且不能是空串
    assert all(tid for tid in tool_ids)
