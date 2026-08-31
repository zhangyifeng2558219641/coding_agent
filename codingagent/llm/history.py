"""对话历史与上下文管理(任务要求的核心部分之一)。

- 维护 OpenAI 结构消息列表;
- system 提示由多段可插拔内容(基础提示/记忆/技能/摘要)动态拼装;
- 超长工具输出自动截断;
- 超预算时调用 summarize() 把旧消息压成一段摘要,保留最近消息原文,
  从而在不丢关键信息的前提下省 token —— 即"上下文压缩 + Token 管理"。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..types import Usage, truncate
from .tokens import estimate_messages_tokens

# 压缩时保留最近 N 条消息不压缩,防止把正在进行的工作也摘要掉
KEEP_RECENT = 12


class History:
    def __init__(
        self,
        budget_tokens: int = 64000,
        compact_ratio: float = 0.5,
        max_tool_output: int = 30000,
    ):
        self.messages: list[dict[str, Any]] = []
        self._system_parts: list[tuple[str, str]] = []   # (key, text),保持插入顺序
        self.budget_tokens = budget_tokens
        self.compact_ratio = compact_ratio
        self.max_tool_output = max_tool_output
        self.compact_count = 0
        self.summary = ""
        self.usage = Usage()

    # ------------------------------------------------------------------ 系统提示
    def add_system_part(self, key: str, text: str) -> None:
        if not text:
            return
        for i, (k, _) in enumerate(self._system_parts):
            if k == key:
                self._system_parts[i] = (key, text)
                return
        self._system_parts.append((key, text))

    def remove_system_part(self, key: str) -> None:
        self._system_parts = [(k, t) for k, t in self._system_parts if k != key]

    def set_summary(self, text: str) -> None:
        self.summary = text

    def system_prompt(self) -> str:
        parts: list[str] = []
        if self.summary:
            parts.append("【历史对话摘要】\n" + self.summary)
        parts += [t for _, t in self._system_parts]
        return "\n\n".join(p for p in parts if p.strip())

    # ------------------------------------------------------------------ 消息操作
    def append(self, msg: dict[str, Any]) -> None:
        """追加一条消息;工具消息超长时自动截断。"""
        if msg.get("role") == "tool":
            content = msg.get("content") or ""
            msg = dict(msg)
            msg["content"] = truncate(content, self.max_tool_output)
        self.messages.append(msg)

    def clear(self) -> None:
        self.messages.clear()

    # ------------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        """持久化消息与摘要状态(不含 system parts,由会话层重建)。"""
        return {"messages": self.messages, "summary": self.summary,
                "compact_count": self.compact_count,
                "usage": {"prompt_tokens": self.usage.prompt_tokens,
                          "completion_tokens": self.usage.completion_tokens}}

    def load_dict(self, data: dict[str, Any]) -> None:
        self.messages = list(data.get("messages", []) or [])
        self.summary = data.get("summary", "") or ""
        self.compact_count = int(data.get("compact_count", 0) or 0)
        u = data.get("usage") or {}
        self.usage = Usage(int(u.get("prompt_tokens", 0) or 0),
                           int(u.get("completion_tokens", 0) or 0))

    def count(self) -> int:
        return len(self.messages)

    # ------------------------------------------------------------------ 组装/预算
    def to_api(self) -> list[dict[str, Any]]:
        """生成发送给模型的消息:第一条为 system。"""
        return [{"role": "system", "content": self.system_prompt()}, *self.messages]

    def estimate_tokens(self) -> int:
        return estimate_messages_tokens(self.to_api())

    def should_compact(self) -> bool:
        if self.budget_tokens <= 0:
            return False
        return self.estimate_tokens() > self.budget_tokens

    # ------------------------------------------------------------------ 压缩
    def compact(self, summarize: Callable[[str], str]) -> bool:
        """把旧消息压缩为摘要;返回是否发生了压缩。

        summarize 形如 summarize(messages_json: str) -> str,由外部绑定 LLM。
        摘要只保留工作相关的关键事实(目标、改动、结论),不保留过程噪音。
        """
        if len(self.messages) <= KEEP_RECENT:
            return False
        old = self.messages[:-KEEP_RECENT]
        self.messages = self.messages[-KEEP_RECENT:]

        payload = json.dumps(old, ensure_ascii=False)[:30000]
        instruction = (
            "下面是一段 AI 编程助手与其用户的对话历史。请压缩成一段简洁的上下文摘要,"
            "保留:任务目标、已完成的关键改动、文件路径、结论与待办。"
            "忽略寒暄与过程性噪音。使用中文,300 字以内。不要虚构没有的信息。\n\n"
            f"对话历史:\n{payload}"
        )
        try:
            summary = summarize(instruction)
        except Exception as e:
            # 摘要失败:恢复消息,宁可多用 token 也不丢上下文
            self.messages = old + self.messages
            return False

        self.summary = (self.summary + "\n" if self.summary else "") + f"第{self.compact_count + 1}次压缩: {summary}"
        self.compact_count += 1
        return True
