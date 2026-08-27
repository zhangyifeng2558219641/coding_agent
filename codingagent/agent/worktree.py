"""Git Worktree 并行隔离:多个 Agent 同时改代码时放进不同工作树,互不打架。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class WorktreeError(Exception):
    pass


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head: str
    bare: bool = False


class WorktreeManager:
    def __init__(self, repo_root: Path):
        self.repo = repo_root.resolve()

    def _git(self, *args: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(self.repo), *args],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30)
        except FileNotFoundError:
            raise WorktreeError("未找到 git 命令")
        if r.returncode != 0:
            raise WorktreeError(f"git {' '.join(args)} 失败: {r.stderr.strip()}")
        return r.stdout

    def is_repo(self) -> bool:
        try:
            self._git("rev-parse", "--is-inside-work-tree")
            return True
        except WorktreeError:
            return False

    def create(self, branch: Optional[str] = None, path: Optional[Path] = None) -> WorktreeInfo:
        """创建一个新工作树;branch 缺省则从当前分支切出新分支。"""
        if not self.is_repo():
            raise WorktreeError(f"{self.repo} 不是 git 仓库,无法创建 worktree")
        branch = branch or f"agent-worktree-{Path(self.repo).name}"
        path = path or self.repo.parent / f"{self.repo.name}.{branch.split('/')[-1]}"
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._git("worktree", "add", "-b", branch, str(path))
        except WorktreeError:
            # 分支可能已存在,改用已有分支
            self._git("worktree", "add", str(path), branch)
        return WorktreeInfo(path=path, branch=branch,
                            head=self._git("rev-parse", "--short", branch).strip())

    def list(self) -> list[WorktreeInfo]:
        out = self._git("worktree", "list", "--porcelain")
        infos: list[WorktreeInfo] = []
        cur: dict[str, Any] = {}
        for line in out.splitlines():
            if not line.strip():
                continue
            if line.startswith("worktree "):
                if cur:
                    infos.append(WorktreeInfo(**cur))
                cur = {"path": Path(line.split(" ", 1)[1])}
            elif line.startswith("branch "):
                cur["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                cur["head"] = line.split(" ", 1)[1]
            elif line.startswith("bare"):
                cur["bare"] = True
        if cur:
            cur.setdefault("branch", "(detached)")
            cur.setdefault("head", "")
            infos.append(WorktreeInfo(**cur))
        return infos

    def remove(self, path: Path) -> bool:
        p = path.resolve()
        infos = self.list()
        if not any(i.path.resolve() == p for i in infos):
            raise WorktreeError(f"不是注册的 worktree: {p}")
        # 默认清理后直接删除目录(交给调用方确认)
        self._git("worktree", "remove", "--force", str(p))
        return True
