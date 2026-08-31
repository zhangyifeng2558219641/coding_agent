from .base import Tool, ToolContext
from .registry import ToolRegistry
from .files import ReadFile, WriteFile, EditFile
from .shell import Bash
from .search import Glob, Grep
from .websearch import WebSearch
from .memory_tools import MemoryRecall, MemorySave
from .subagent_tool import DispatchTask
from .mcp import MCPClient, MCPToolAdapter, MCPManager, MCPError

CORE_TOOLS: list[type[Tool]] = [ReadFile, WriteFile, EditFile, Bash, Glob, Grep, WebSearch]
MEMORY_TOOLS: list[type[Tool]] = [MemoryRecall, MemorySave]
AGENT_TOOLS: list[type[Tool]] = [DispatchTask]


def default_registry(with_memory: bool = True, with_agent_tools: bool = True) -> ToolRegistry:
    """构造注册表:核心工具(含 WebSearch)+ 可选记忆/子任务工具。"""
    reg = ToolRegistry()
    for cls in CORE_TOOLS:
        reg.register(cls())
    if with_memory:
        for cls in MEMORY_TOOLS:
            reg.register(cls())
    if with_agent_tools:
        for cls in AGENT_TOOLS:
            reg.register(cls())
    return reg


__all__ = ["Tool", "ToolContext", "ToolRegistry", "ReadFile", "WriteFile",
           "EditFile", "Bash", "Glob", "Grep", "WebSearch", "MemoryRecall",
           "MemorySave", "DispatchTask", "MCPClient", "MCPToolAdapter",
           "MCPManager", "MCPError", "default_registry"]
