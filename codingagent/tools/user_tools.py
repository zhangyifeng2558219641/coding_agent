"""用户交互工具:让 Agent 向用户提问并给出选项,等用户拍板后继续。

选择经 ToolContext.choose 路由到当前 UI(CLI 编号列表 / Web 选项条),
返回值回写为工具结果,模型据此继续——对应 Claude Code 的 AskUserQuestion。
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext
from ..types import ToolResult

_MAX_OPTIONS = 6


class AskUser(Tool):
    name = "ask_user"
    description = (
        "当任务存在歧义、多个可行方向或需要用户决定取舍时,向用户提出一个问题并"
        "给出 2-6 个选项,用户点选(或自定义输入)后按其选择继续。"
        "仅在确实需要用户拍板时才调用,不要用它做简单确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "要向用户提出的问题",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 6,
                "description": "候选选项(2-6 个),用户选择或自定义输入",
            },
        },
        "required": ["prompt", "options"],
    }
    category = "general"
    read_only = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        prompt = str(kwargs.get("prompt") or "").strip() or "请选择一个方向"
        opts = [o for o in (kwargs.get("options") or [])
                if isinstance(o, str) and o.strip()]
        if not opts:
            return ToolResult(name=self.name, success=False,
                              error="ask_user 需要至少一个选项")
        opts = opts[:_MAX_OPTIONS]

        ans = ctx.choose(prompt, opts) if ctx.choose else None
        if ans is None:
            return ToolResult(name=self.name, success=False,
                              error="当前界面不支持交互选择,请按最合理的方案自行继续")
        if ans == -1 or not isinstance(ans, (int, str)):
            return ToolResult(name=self.name, success=True,
                              output="用户取消了本次选择,可自行决定或按最合理方案继续")
        if isinstance(ans, str):
            return ToolResult(name=self.name, success=True,
                              output=f"用户选择了「其他/自定义」:{ans}")
        if 0 <= ans < len(opts):
            return ToolResult(name=self.name, success=True,
                              output=f"用户从选项中选择:{opts[ans]}")
        return ToolResult(name=self.name, success=True,
                          output="用户取消了本次选择,可自行决定或按最合理方案继续")
