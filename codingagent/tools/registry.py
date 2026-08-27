"""工具注册表:注册/查询/序列化,供 Agent 循环与 LLM 使用。"""

from __future__ import annotations

from typing import Any, Optional

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_ci(self, name: str) -> Optional[Tool]:
        """大小写不敏感查找。"""
        t = self.get(name)
        if t:
            return t
        lower = name.lower()
        for k, v in self._tools.items():
            if k.lower() == lower:
                return v
        return None

    def has(self, name: str) -> bool:
        return self.get_ci(name) is not None

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_function() for t in self._tools.values()]

    def describe(self) -> str:
        lines = [f"- {t.summary()}" for t in self._tools.values()]
        return "\n".join(lines) if lines else "(无可用工具)"
