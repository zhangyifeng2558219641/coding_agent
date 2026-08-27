"""记忆读写工具:让 Agent 自己把重要事实存进跨会话记忆。"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext
from ..types import ToolResult


class MemoryRecall(Tool):
    name = "MemoryRecall"
    description = (
        "读取跨会话记忆(项目级 + 用户级)。适合在开始任务前回忆用户偏好、"
        "项目约束与历史结论。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string", "enum": ["all", "project", "user"],
                "description": "记忆范围,默认 all",
            },
        },
    }
    category = "memory"

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        scope = kwargs.get("scope", "all")
        if not ctx.memory or not ctx.memory.enabled:
            return ToolResult(name=self.name, success=False, error="记忆系统未启用")
        if scope == "project":
            content = ctx.memory.load_project()
        elif scope == "user":
            content = ctx.memory.load_user()
        else:
            content = ctx.memory.load_all()
        if not content.strip():
            return ToolResult(name=self.name, success=True, output="(暂无记忆)")
        return ToolResult(name=self.name, success=True, output=content)


class MemorySave(Tool):
    name = "MemorySave"
    description = (
        "把一条事实写入跨会话记忆。project=关于本项目的事实(架构决策、约定、进展);"
        "user=关于用户的偏好。只记关键、长期有用的事实,不要记一次性过程。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "要记住的事实,一句话"},
            "scope": {
                "type": "string", "enum": ["project", "user"],
                "description": "写入范围,默认 project",
            },
        },
        "required": ["entry"],
    }
    category = "memory"

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        entry = kwargs.get("entry", "")
        scope = kwargs.get("scope", "project")
        if not entry.strip():
            return ToolResult(name=self.name, success=False, error="entry 为空")
        if not ctx.memory or not ctx.memory.enabled:
            return ToolResult(name=self.name, success=False, error="记忆系统未启用")
        ctx.memory.append(scope, entry.strip())
        return ToolResult(name=self.name, success=True,
                          output=f"已记住({scope}): {entry.strip()}")
