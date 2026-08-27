"""子任务分发工具:主 Agent 把子任务委派给独立子 Agent,复杂任务并行加速。"""

from __future__ import annotations

from typing import Any, Optional

from .base import Tool, ToolContext
from ..types import ToolResult


class DispatchTask(Tool):
    name = "DispatchTask"
    description = (
        "把子任务委派给独立的子 Agent 执行并返回其结果。"
        "传单个 task 串行执行;传 tasks 数组则并行执行多个子任务,大幅加速。"
        "适合把大任务拆成互不依赖的小块。子 Agent 使用独立上下文,互不干扰。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "单个子任务描述"},
            "tasks": {"type": "array", "items": {"type": "string"},
                      "description": "多个并行子任务(与 task 二选一)"},
            "output_path": {"type": "string", "description": "子 Agent 工作目录(可选,默认主工作区)"},
            "allow_tools": {"type": "array", "items": {"type": "string"},
                            "description": "允许子 Agent 使用的工具白名单(可选)"},
        },
    }
    category = "agent"

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if not (ctx.llm and ctx.registry):
            return ToolResult(name=self.name, success=False, error="当前上下文不支持子任务")
        task = kwargs.get("task")
        tasks = kwargs.get("tasks") or []
        if not task and not tasks:
            return ToolResult(name=self.name, success=False, error="需要提供 task 或 tasks")
        tasks = [task] if task else list(tasks)
        workspace = ctx.resolve(kwargs["output_path"]) if kwargs.get("output_path") else ctx.workspace

        from ..agent.subagent import run_subagents_parallel

        try:
            results = run_subagents_parallel(
                ctx.config, workspace, ctx.llm, ctx.registry, tasks,
                name_prefix="worker",
                allow_tools=kwargs.get("allow_tools"),
                max_workers=min(5, len(tasks)),
            )
        except Exception as e:
            return ToolResult(name=self.name, success=False, error=f"子任务分发失败: {e}")

        blocks = []
        for r in results:
            status = "成功" if r.success else f"失败({r.error})"
            blocks.append(f"【子任务: {r.task} - {status}】\n{r.text}")
        combined = "\n\n".join(blocks)
        return ToolResult(name=self.name, success=all(r.success for r in results),
                          output=combined[:20000])
