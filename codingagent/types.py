"""共享数据类型。

消息统一采用 OpenAI Chat Completions 的 dict 结构,便于模型原生 tool calling:
    {"role": "system"|"user"|"assistant"|"tool",
     "content": str,
     "tool_calls": [ToolCall-as-dict],        # assistant 消息,可选
     "tool_call_id": str}                      # tool 消息,可选
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """一次由模型发起的工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"ToolCall({self.name}({self.raw_arguments[:80]}))"


@dataclass
class ToolResult:
    """一次工具执行的返回。"""

    name: str
    call_id: Optional[str] = None
    success: bool = True
    output: str = ""
    error: str = ""

    @property
    def content(self) -> str:
        if self.success:
            return self.output
        # 失败时也带上实际输出(stdout/stderr),否则模型和用户都看不到失败原因
        if self.output:
            return f"[工具执行失败: {self.error}]\n{self.output}"
        return f"[工具执行失败: {self.error}]"

    def to_message(self) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": self.call_id or "", "content": self.content}


@dataclass
class Usage:
    """一轮请求的 token 用量(无官方数据时用估算值)。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens,
                     self.completion_tokens + other.completion_tokens)


@dataclass
class FinalResult:
    """一次完整 agent 任务(可能多轮工具调用)的最终产物。"""

    text: str
    success: bool = True
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0


def now_ms() -> int:
    return int(time.time() * 1000)


def truncate(text: str, limit: int = 30000, head_ratio: float = 0.6) -> str:
    """截断长文本:保留头部与尾部,中间用省略标记。

    用于控制进入上下文的工具输出长度,避免 token 爆炸。
    """
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    head = int(limit * head_ratio)
    tail = limit - head
    return text[:head] + f"\n...[中间省略 {len(text) - head - tail} 字符]...\n" + text[-tail:]
