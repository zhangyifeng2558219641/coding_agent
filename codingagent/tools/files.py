"""文件类工具:ReadFile / WriteFile / EditFile。

EditFile 采用"严格旧文本匹配"的差异编辑:old_string 必须唯一命中,
否则宁可报错也不猜测 —— 避免静默改错位置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolContext
from ..types import ToolResult

_BINARY_PROBE = 8000


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(_BINARY_PROBE)
        return b"\x00" in head
    except OSError:
        return False


class ReadFile(Tool):
    name = "ReadFile"
    description = (
        "读取指定文件的内容。可选 offset 起始行(1 基)与 limit 行数读取局部。"
        "返回带行号的内容;适合先读文件再精准编辑。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径(相对或绝对)"},
            "offset": {"type": "integer", "description": "从第几行开始(1 基),默认从头"},
            "limit": {"type": "integer", "description": "最多读取多少行"},
            "line_numbers": {"type": "boolean", "description": "是否显示行号,默认 true"},
        },
        "required": ["path"],
    }
    category = "file"
    path_sensitive = True
    read_only = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        path = ctx.resolve(kwargs["path"])
        offset = kwargs.get("offset") or None
        limit = kwargs.get("limit") or None
        with_numbers = bool(kwargs.get("line_numbers", True))

        if not path.exists():
            return ToolResult(name=self.name, success=False, error=f"文件不存在: {path}")
        if path.is_dir():
            return ToolResult(name=self.name, success=False, error=f"是目录而非文件: {path}")
        if _is_binary(path):
            return ToolResult(name=self.name, success=False,
                              error=f"文件是二进制(不可按文本读取): {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(name=self.name, success=False, error=f"读取失败: {e}")

        lines = text.splitlines()
        total = len(lines)
        start = (offset - 1) if offset and offset > 0 else 0
        end = total if not limit else min(start + limit, total)
        if start >= total:
            return ToolResult(name=self.name, success=True,
                              output=f"(文件 {path.name} 共 {total} 行,起始行 {offset} 超出范围)")
        chunk = lines[start:end]

        if with_numbers:
            width = len(str(end))
            body = "\n".join(f"{i + 1:>{width}} | {ln}" for i, ln in enumerate(chunk, start))
        else:
            body = "\n".join(chunk)

        meta = f"文件: {ctx.relative(path)}  共 {total} 行,本次显示 {len(chunk)} 行"
        if start > 0 or end < total:
            meta += f"(第 {start + 1}-{end} 行)"
        return ToolResult(name=self.name, success=True, output=f"{meta}\n{body}")


class WriteFile(Tool):
    name = "WriteFile"
    description = (
        "把 content 整体写入(覆盖)指定文件;文件不存在则新建,自动创建父目录。"
        "注意:这是覆盖写,如需局部修改请用 EditFile。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    }
    category = "file"
    path_sensitive = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        path = ctx.resolve(kwargs["path"])
        content = str(kwargs.get("content") or "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            return ToolResult(name=self.name, success=False, error=f"写入失败: {e}")
        existed = "已存在,已覆盖" if path.exists() else "新建"
        return ToolResult(
            name=self.name, success=True,
            output=f"已写入 {ctx.relative(path)}({existed}):{content.count(chr(10)) + 1} 行,{len(content)} 字符",
        )


class EditFile(Tool):
    name = "EditFile"
    description = (
        "在文件中做精确替换。old_string 必须与文件中的一段原文逐字完全一致,"
        "且只出现一次,否则报错(不会猜测)。一次只改一处;多处修改请多次调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "old_string": {"type": "string", "description": "要替换的原文(须唯一匹配)"},
            "new_string": {"type": "string", "description": "替换成的新文本"},
            "replace_all": {"type": "boolean", "description": "允许替换所有出现处,默认 false"},
        },
        "required": ["path", "old_string", "new_string"],
    }
    category = "file"
    path_sensitive = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        path = ctx.resolve(kwargs["path"])
        old = kwargs.get("old_string", "")
        new = kwargs.get("new_string", "")
        replace_all = bool(kwargs.get("replace_all", False))

        if not old:
            return ToolResult(name=self.name, success=False, error="old_string 不能为空")
        if not path.exists():
            return ToolResult(name=self.name, success=False, error=f"文件不存在: {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(name=self.name, success=False, error=f"读取失败: {e}")

        count = text.count(old)
        if count == 0:
            return ToolResult(
                name=self.name, success=False,
                error="未找到待替换的旧文本。请提供与文件中逐字一致(含缩进/换行)的精确原文。",
            )
        if count > 1 and not replace_all:
            return ToolResult(
                name=self.name, success=False,
                error=f"old_string 在文件中出现 {count} 次,无法确定改哪处。"
                      "请补充更多上下文使文本唯一,或设置 replace_all=true 全部替换。",
            )
        new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError as e:
            return ToolResult(name=self.name, success=False, error=f"写入失败: {e}")

        return ToolResult(
            name=self.name, success=True,
            output=f"已修改 {ctx.relative(path)}:{'替换全部' if replace_all else '替换'} {count} 处",
        )
