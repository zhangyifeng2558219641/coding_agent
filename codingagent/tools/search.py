"""搜索类工具:Glob(文件名模式) / Grep(内容正则)。均为本地实现,不依赖 grep 命令。"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext
from .files import _is_binary
from ..types import ToolResult

MAX_RESULTS = 100
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".venv", "venv"}


def _iter_text_files(base: Path) -> list[Path]:
    files: list[Path] = []
    if not base.is_dir():
        return files
    for root, dirs, names in base.walk():
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            p = Path(root) / n
            if p.suffix in {".pyc", ".pyo"}:
                continue
            if p.stat().st_size > 2 * 1024 * 1024:  # 跳过 >2MB
                continue
            if not _is_binary(p):
                files.append(p)
    return files


class Glob(Tool):
    name = "Glob"
    description = (
        "按文件名模式查找文件(如 '**/*.py'、'src/*.tsx')。"
        "支持 ** 递归;返回相对路径列表。用于定位文件,不读内容。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式,支持 ** 递归"},
            "path": {"type": "string", "description": "搜索根目录(可选,默认工作区)"},
        },
        "required": ["pattern"],
    }
    category = "search"
    read_only = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        base = ctx.resolve(kwargs.get("path") or ".")
        if not pattern:
            return ToolResult(name=self.name, success=False, error="pattern 为空")
        if not base.is_dir():
            return ToolResult(name=self.name, success=False, error=f"目录不存在: {base}")

        matches: list[str] = []
        for p in base.glob(pattern):
            if p.is_file() and ".git" not in p.parts:
                try:
                    matches.append(p.relative_to(ctx.workspace).as_posix())
                except ValueError:
                    matches.append(str(p))
        matches.sort()
        total = len(matches)
        if total > MAX_RESULTS:
            matches = matches[:MAX_RESULTS]
        head = f"在 {ctx.relative(base)} 下匹配 '{pattern}' 的文件: {total} 个"
        body = "\n".join(matches) if matches else "(无匹配)"
        if total > MAX_RESULTS:
            body += f"\n(仅显示前 {MAX_RESULTS} 个)"
        return ToolResult(name=self.name, success=True, output=f"{head}\n{body}")


class Grep(Tool):
    name = "Grep"
    description = (
        "在文本文件中用正则搜索内容,返回 文件:行号:内容。"
        "可用 glob 限定文件类型、context 显示上下文行。用于找函数/字符串定义处。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则(或 fixed_strings=true 时的字面量)"},
            "path": {"type": "string", "description": "搜索根目录(可选,默认工作区)"},
            "glob": {"type": "string", "description": "只搜匹配此 glob 的文件,如 '*.py'"},
            "ignore_case": {"type": "boolean", "description": "忽略大小写,默认 false"},
            "fixed_strings": {"type": "boolean", "description": "按字面量匹配而非正则,默认 false"},
            "line_number": {"type": "boolean", "description": "显示行号,默认 true"},
            "context": {"type": "integer", "description": "每处匹配显示的上下文行数,默认 0"},
            "max_results": {"type": "integer", "description": "最多返回条数,默认 100"},
        },
        "required": ["pattern"],
    }
    category = "search"
    read_only = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        base = ctx.resolve(kwargs.get("path") or ".")
        glob = kwargs.get("glob")
        flags = re.IGNORECASE if kwargs.get("ignore_case") else 0
        fixed = bool(kwargs.get("fixed_strings", False))
        show_line = bool(kwargs.get("line_number", True))
        context = int(kwargs.get("context") or 0)
        limit = int(kwargs.get("max_results") or MAX_RESULTS)

        if not pattern:
            return ToolResult(name=self.name, success=False, error="pattern 为空")
        try:
            matcher = re.compile(re.escape(pattern), flags) if fixed else re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(name=self.name, success=False, error=f"正则错误: {e}")

        results: list[str] = []
        matched_any = False
        for p in _iter_text_files(base):
            if glob and not fnmatch.fnmatch(p.name, glob) and not fnmatch.fnmatch(str(p), glob):
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if matcher.search(line):
                    matched_any = True
                    rel = p.relative_to(ctx.workspace).as_posix() if ctx.workspace else str(p)
                    for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                        marker = "->" if j == i else "  "
                        prefix = f"{rel}:{j + 1}:{marker} " if show_line else ""
                        results.append(prefix + lines[j])
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        total_hint = "" if matched_any else "(无匹配)"
        if len(results) >= limit:
            total_hint = f"(结果较多,已截断到 {limit} 条)"
        body = "\n".join(results) if results else "(无匹配)"
        return ToolResult(name=self.name, success=True,
                          output=f"搜索 '{pattern}' @ {ctx.relative(base)}: {body}\n{total_hint}".rstrip())
