"""启发式 token 估算。

不引入 tiktoken 等重量级依赖;对主流中文/英文混排的代码与文本足够接近,
用于上下文预算管理。规则:
- 中文字符(含全角标点)≈ 1 token/字符
- 其它字符(ASCII、数字、符号)≈ 1 token/4 字符
- 空行/空白额外少量计入
"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯—‘’“”…]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    # 代码行/空白也占 token,给一点系数
    lines = text.count("\n")
    return int(cjk + other / 4 + lines * 0.3) + 1


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算一组消息(OpenAI 结构)的 token 数。"""
    total = 0
    for m in messages:
        total += estimate_tokens(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("name", ""))
            total += estimate_tokens(fn.get("arguments", ""))
    return total
