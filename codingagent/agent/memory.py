"""跨会话记忆系统:项目级 + 用户级。

- 项目记忆:   <workspace>/.coding_agent/memory/project.md(gitignore)
- 用户记忆:   ~/.coding_agent/memory/user.md
- 会话开始时把记忆注入 system 提示;Agent 可用 MemorySave/MemoryRecall 持续读写,
  使多次会话之间累积对项目和用户的了解。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..types import truncate


class MemoryStore:
    def __init__(self, config, workspace: Path):
        mem_cfg = (config.get("memory") or {}) if config else {}
        self.enabled = bool(mem_cfg.get("enabled", True))
        project_rel = mem_cfg.get("project_file", ".coding_agent/memory/project.md")
        user_rel = mem_cfg.get("user_file", "~/.coding_agent/memory/user.md")
        p = Path(project_rel)
        if not p.is_absolute():
            p = workspace / p
        self.project_file = p
        self.user_file = Path(user_rel).expanduser()

    # ------------------------------------------------------------------ 读写
    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            return ""

    def _write(self, path: Path, content: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError:
            pass

    def load_project(self) -> str:
        return self._read(self.project_file)

    def load_user(self) -> str:
        return self._read(self.user_file)

    def load_all(self) -> str:
        if not self.enabled:
            return ""
        parts = []
        user = self.load_user()
        project = self.load_project()
        if user.strip():
            parts.append(f"【关于用户】\n{user.strip()}")
        if project.strip():
            parts.append(f"【关于本项目】\n{project.strip()}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ 操作
    def append(self, scope: str, entry: str) -> None:
        """追加一条带时间的记忆条目。scope: project | user。"""
        if not self.enabled:
            return
        path = self.project_file if scope == "project" else self.user_file
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        text = self._read(path)
        text = (text.rstrip() + "\n" if text.strip() else "") + f"- [{ts}] {entry}\n"
        self._write(path, text)

    def save(self, scope: str, content: str) -> None:
        """整体覆盖某范围记忆。"""
        if not self.enabled:
            return
        path = self.project_file if scope == "project" else self.user_file
        self._write(path, content)

    def clear(self, scope: Optional[str] = None) -> None:
        paths = [self.project_file] if scope in (None, "project") else []
        if scope in (None, "user"):
            paths.append(self.user_file)
        for p in paths:
            self._write(p, "")

    def recall(self, query: Optional[str] = None) -> str:
        """返回全部记忆(截断);query 预留做关键词过滤。"""
        return truncate(self.load_all(), 8000)
