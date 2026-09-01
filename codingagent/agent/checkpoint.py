"""文件检查点 / 回滚。

Agent 每回合通过 WriteFile/EditFile 改文件时,自动快照 before/after,
按会话持久化为有序检查点;可查看每文件差异,并一键回滚工作区到某个检查点。

回滚语义:"恢复到检查点 N 之后"的状态 ——
- 对每个被跟踪文件,取 ≤N 的最后一个触及它的检查点的 after 覆盖之;
- 仅删除"首个触及即为创建(before==None)"且只在 >N 触及的文件;
- 对"N 之后才首次被改、但文件本就存在(不可重建)"的文件保留并警告,绝不误删。
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .permissions import _is_within


class CheckpointStore:
    """按会话存储检查点;path=None 时纯内存(测试 / 裸 AgentLoop 的默认)。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}  # relpath -> {before, after}
        self._checkpoints: list[dict[str, Any]] = []
        if self.path is not None:
            self._checkpoints = self._load()

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return list(data.get("checkpoints", []))
        except Exception:
            return []

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"checkpoints": self._checkpoints}, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass  # 检查点落盘失败不致命,不影响主流程

    # ------------------------------------------------------------------ 捕获
    def begin_turn(self) -> None:
        """新回合开始,清空上一回合未 finalize 的 pending(CLI 跨轮复用 agent)。"""
        self._pending = {}

    def snapshot_before(self, workspace: Path, relpath: str) -> None:
        with self._lock:
            if relpath in self._pending:
                return  # 同一回合多次写同一文件,保留首个 before
            self._pending[relpath] = {"before": self._read(workspace, relpath), "after": None}

    def snapshot_after(self, workspace: Path, relpath: str) -> None:
        with self._lock:
            if relpath not in self._pending:
                return
            self._pending[relpath]["after"] = self._read(workspace, relpath)

    def discard(self, relpath: str) -> None:
        """写盘失败时移除 pending 项,避免记录未成功的写入。"""
        with self._lock:
            self._pending.pop(relpath, None)

    @staticmethod
    def _read(workspace: Path, relpath: str) -> Optional[str]:
        try:
            return (workspace / relpath).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None  # 文件缺失(创建场景)或读取失败 → before=None

    def finalize(self) -> Optional[dict[str, Any]]:
        """回合结束:把 pending 写盘为一条检查点,返回该检查点(或 None)。"""
        with self._lock:
            pending = self._pending
            self._pending = {}
            if not pending:
                return None
            # 过滤:写被打断(after 缺失)或内容未变(before==after)都不构成有效变更
            files = {rp: d for rp, d in pending.items()
                     if d.get("after") is not None and d.get("after") != d.get("before")}
            if not files:
                return None  # 无有效变更,不落检查点
            seq = self._checkpoints[-1]["seq"] + 1 if self._checkpoints else 1
            cp = {
                "seq": seq,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": {rp: {"before": files[rp]["before"], "after": files[rp]["after"]}
                          for rp in files},
            }
            self._checkpoints.append(cp)
            self._save()
            return copy.deepcopy(cp)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._checkpoints)

    # ------------------------------------------------------------------ 回滚
    @staticmethod
    def safe_join(workspace: Path, relpath: str) -> Optional[Path]:
        """把相对路径安全解析到工作区内;绝对路径或越出沙箱 → None。"""
        p = Path(relpath)
        if p.is_absolute():
            return None
        try:
            full = (workspace / p).resolve()
        except OSError:
            return None
        if not _is_within(full, workspace):
            return None
        return full

    def rollback(self, seq: int, workspace: Path) -> dict[str, Any]:
        """回滚工作区到检查点 seq 之后的状态。

        返回 {"restored":[], "deleted":[], "left_unchanged":[], "errors":[]}。
        """
        with self._lock:
            cps = self._checkpoints
            if not (1 <= seq <= len(cps)):
                return {"error": f"检查点序号 {seq} 越界(共 {len(cps)} 个)"}
            workspace = workspace.resolve()

            # pass1:按 seq 序遍历,记 first-touch 是否创建 + last(≤seq) + touched_after
            first_touch_before: dict[str, Optional[str]] = {}
            last: dict[str, dict[str, Any]] = {}
            touched_after: set[str] = set()
            for cp in cps:
                for rp, d in cp.get("files", {}).items():
                    if rp not in first_touch_before:
                        first_touch_before[rp] = d.get("before")
                    if cp["seq"] <= seq:
                        last[rp] = d
                    else:
                        touched_after.add(rp)

            # pass2:恢复 ≤seq 最后一次触及的 after
            restored: list[str] = []
            errors: list[str] = []
            for rp, d in last.items():
                full = self.safe_join(workspace, rp)
                if full is None:
                    errors.append(rp)
                    continue
                try:
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(d["after"], encoding="utf-8")
                    restored.append(rp)
                except OSError:
                    errors.append(rp)

            # pass3:仅在 >seq 触及的文件 —— 创建的可删;既存的不可重建,保留并警告
            deleted: list[str] = []
            left_unchanged: list[str] = []
            for rp in touched_after:
                if rp in last:
                    continue
                if first_touch_before.get(rp) is None:
                    full = self.safe_join(workspace, rp)
                    if full is None:
                        errors.append(rp)
                        continue
                    try:
                        full.unlink(missing_ok=True)
                        deleted.append(rp)
                    except OSError:
                        errors.append(rp)
                else:
                    left_unchanged.append(rp)

            return {"restored": restored, "deleted": deleted,
                    "left_unchanged": left_unchanged, "errors": errors}
