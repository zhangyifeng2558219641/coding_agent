"""自写的 OpenAI 兼容聊天客户端(重要逻辑全部自行实现)。

- 用 requests 直连任意 OpenAI 兼容网关(/chat/completions),不依赖 openai 包;
- 手写 SSE 流式解析,边收边吐文本 delta;
- 手写 tool calling 累积:按 index 增量拼接 id/name/arguments;
- 指数退避重试、超时、错误响应解析;
- 完整实现模型输出解析与错误处理(任务要求的核心部分之一)。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import requests

from ..types import ToolCall, Usage
from .tokens import estimate_tokens

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """LLM 调用失败(网络、鉴权、格式错误等)。"""


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class StreamEvent:
    """流式事件。type: text | tool_calls | finish | error"""
    type: str
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    reason: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    message: str = ""


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 120,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
        include_usage: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.include_usage = include_usage

    # ------------------------------------------------------------------ 基础
    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(self, messages: list[dict], tools: list[dict] | None, stream: bool,
                 **kw: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": kw.pop("model", self.model),
            "messages": messages,
            "temperature": kw.pop("temperature", self.temperature),
            "max_tokens": kw.pop("max_tokens", self.max_tokens),
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stream and self.include_usage:
            payload["stream_options"] = {"include_usage": True}
        payload.update(kw)
        return payload

    # ------------------------------------------------------------------ 请求
    def _do_request(self, messages, tools, stream, **kw) -> requests.Response:
        """发一次请求;成功返回 Response,失败抛 LLMError。"""
        if not self.api_key:
            raise LLMError(
                "未检测到 API key。请在 .env 或环境变量中设置 DEEPSEEK_API_KEY 等凭据"
                "(参见 .env.example 与《项目使用方式说明.md》)。"
            )
        url = self._endpoint()
        payload = self._payload(messages, tools, stream, **kw)
        last_err: Exception = LLMError("unknown error")

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, headers=self._headers(), json=payload,
                                     stream=stream, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = LLMError(f"网络请求失败: {e}")
                time.sleep(self.retry_backoff * (2 ** attempt))
                continue

            if resp.status_code == 200:
                return resp

            body = resp.text[:500]
            # include_usage 不受支持时,去掉 stream_options 重试一次
            if (resp.status_code == 400 and self.include_usage
                    and "stream_options" in payload):
                payload.pop("stream_options", None)
                last_err = LLMError(f"400 {body}")
                time.sleep(0.3)
                continue

            detail = ""
            try:
                j = resp.json()
                detail = j.get("error", {}).get("message", "") or str(j)[:200]
            except Exception:
                detail = body
            if resp.status_code in (401, 403):
                raise LLMError(f"鉴权失败({resp.status_code}): {detail}")
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                last_err = LLMError(f"HTTP {resp.status_code}: {detail}")
                time.sleep(self.retry_backoff * (2 ** attempt))
                continue
            raise LLMError(f"HTTP {resp.status_code}: {detail}")

        raise last_err

    # ------------------------------------------------------------------ 解析
    @staticmethod
    def _parse_tool_calls(raw: Any) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tc in raw or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments") or ""
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
                if not isinstance(args, dict):
                    args = {"value": args}
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""),
                                  arguments=args, raw_arguments=raw_args))
        return calls

    def _parse_usage(self, raw: Any) -> Usage:
        if raw:
            return Usage(int(raw.get("prompt_tokens", 0) or 0),
                         int(raw.get("completion_tokens", 0) or 0))
        return Usage()

    # ------------------------------------------------------------------ 非流式
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             **kw: Any) -> ChatResponse:
        resp = self._do_request(messages, tools, stream=False, **kw)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise LLMError("模型返回了非 JSON 内容")
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise LLMError(f"响应缺少 choices: {str(data)[:300]}")
        content = msg.get("content") or ""
        calls = self._parse_tool_calls(msg.get("tool_calls"))
        usage = self._parse_usage(data.get("usage"))
        if not content and not calls:
            raise LLMError("模型返回了空响应")
        return ChatResponse(content=content, tool_calls=calls,
                            finish_reason=data["choices"][0].get("finish_reason"),
                            usage=usage)

    # ------------------------------------------------------------------ 流式
    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    **kw: Any) -> Iterator[StreamEvent]:
        """边收边吐:文本 delta 实时 yield,整轮结束前补发 tool_calls/finish。"""
        resp = self._do_request(messages, tools, stream=True, **kw)
        pending: dict[int, dict[str, str]] = {}
        usage_raw: Optional[dict[str, int]] = None
        finish_reason: Optional[str] = None

        try:
            for raw in self._iter_sse(resp):
                if raw is None:
                    continue
                if raw.get("usage"):
                    usage_raw = raw["usage"]
                for choice in raw.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield StreamEvent(type="text", text=text)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = pending.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
        except requests.RequestException as e:
            yield StreamEvent(type="error", message=f"流式中断: {e}")
            return

        calls = []
        for slot in sorted(pending.values()):
            raw_args = slot["arguments"]
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
                if not isinstance(args, dict):
                    args = {"value": args}
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            calls.append(ToolCall(id=slot["id"], name=slot["name"],
                                  arguments=args, raw_arguments=raw_args))

        usage = self._parse_usage(usage_raw)
        if not usage.total and calls:
            usage = self._estimate(messages, calls)

        if calls:
            yield StreamEvent(type="tool_calls", calls=calls)
        yield StreamEvent(type="finish", reason=finish_reason, usage=usage)

    @staticmethod
    def _iter_sse(resp: requests.Response) -> Iterator[Optional[dict[str, Any]]]:
        """手写 SSE 解析:识别 data: 行与 [DONE]。"""
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith(":"):  # 心跳注释行
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue

    def _estimate(self, messages: list[dict], calls: list[ToolCall]) -> Usage:
        """流式拿不到 usage 时,用启发式估算。"""
        prompt = sum(estimate_tokens(str(m.get("content") or "")) for m in messages)
        for c in calls:
            prompt += estimate_tokens(c.name) + estimate_tokens(c.raw_arguments)
        completion = 0
        return Usage(prompt_tokens=prompt, completion_tokens=completion)


def client_from_config(config) -> ChatClient:
    """根据 Config 构造客户端。"""
    p = config.provider
    return ChatClient(
        base_url=p.get("base_url", "https://api.deepseek.com"),
        api_key=config.api_key(),
        model=p.get("model", "deepseek-chat"),
        temperature=p.get("temperature", 0.3),
        max_tokens=p.get("max_tokens", 8192),
        timeout=p.get("timeout", 120),
        max_retries=p.get("max_retries", 3),
        retry_backoff=p.get("retry_backoff", 2.0),
        include_usage=bool(p.get("include_usage", True)),
    )
