"""工具基类与工具上下文。

- Tool:工具约定(名称/描述/JSON-schema 参数/run),全部工具都实现该接口;
- ToolContext:传递给 run 的运行时上下文(工作区、权限、回调、内存等),
  保证工具与 UI/权限解耦,同一套工具在 CLI 与 Web 下行为一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..types import ToolResult


@dataclass
class ToolContext:
    workspace: Path = field(default_factory=lambda: Path.cwd())
    cwd: Path = field(default_factory=lambda: Path.cwd())
    config: Any = None
    permissions: Any = None
    memory: Any = None
    llm: Any = None
    registry: Any = None
    # 交互回调:ask(question) -> bool;emit(event, data) 用于 Web/CLI 事件推送
    ask: Optional[Callable[[str], bool]] = None
    emit: Optional[Callable[[str, dict], None]] = None

    def resolve(self, p: str | Path) -> Path:
        """把相对路径解析为相对当前工作目录的绝对路径。"""
        path = Path(str(p)).expanduser()
        if not path.is_absolute():
            path = (self.cwd or Path.cwd()) / path
        return path.resolve()

    def relative(self, p: str | Path) -> str:
        """返回相对工作区的显示路径(尽量短,便于模型阅读)。"""
        path = self.resolve(p)
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(path)


class Tool:
    """所有工具的基础接口。子类只需定义 name/description/parameters 并实现 run。"""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    category: str = "general"
    # 是否需要对文件/目录等路径参数做沙箱与敏感路径检查
    path_sensitive: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name:
            cls.name = cls.__name__.lower()

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    # -- 供 registry / LLM 使用 ----------------------------------------------
    def to_openai_function(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def summary(self) -> str:
        return f"{self.name}: {self.description}"
