"""5 层纵深权限防御:让 Agent 有能力但不失控。

策略逐层裁决,返回 ALLOW / ASK / DENY:

  层1  工具级规则:deny_tools > allow_tools > ask_tools(最优先)
  层2  敏感路径拦截:命中敏感目录/密钥文件名 → 直接拒绝
  层3  工作区沙箱:路径/目录越出工作区 → 需确认(或拒绝)
  层4  危险命令确认:命中 dangerous_commands 正则 → 需确认
  层5  兜底:白名单命令放行;未匹配操作按审批模式(mode)裁决

mode 语义:
  interactive  —— 未知操作逐次询问用户
  auto-approve —— 未知操作自动放行(需用户明确开启)
  deny         —— 未知操作一律拒绝
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PermissionDecision:
    decision: Decision
    reason: str = ""
    layer: int = 0


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class PermissionPolicy:
    def __init__(self, cfg: dict[str, Any], workspace: Path):
        self.mode = cfg.get("mode", "interactive")
        self.sandbox = bool(cfg.get("sandbox", True))
        self.workspace = workspace.resolve()
        self.allow_tools = set(cfg.get("allow_tools", []) or [])
        self.deny_tools = set(cfg.get("deny_tools", []) or [])
        self.ask_tools = set(cfg.get("ask_tools", []) or [])
        self.allow_commands = [re.compile(p) for p in cfg.get("allow_commands", []) or []]
        self.dangerous_commands = [re.compile(p) for p in cfg.get("dangerous_commands", []) or []]
        self.sensitive_paths = cfg.get("sensitive_paths", []) or []
        self.sensitive_files = cfg.get("sensitive_file_names", []) or []

    # ------------------------------------------------------------- 子检查
    def _check_sensitive_path(self, path: Path) -> bool:
        """命中敏感路径或敏感文件名即 True(应拒绝)。"""
        try:
            parts = path.resolve().parts
        except OSError:
            parts = Path(str(path)).parts
        joined = "/".join(parts)
        name = path.name
        for pat in self.sensitive_paths:
            if "/" in pat and pat in joined:
                return True
            if "/" not in pat and any(pat == part or pat in part for part in parts):
                return True
        for fpat in self.sensitive_files:
            if fnmatch.fnmatch(name, fpat) or fnmatch.fnmatch(joined, fpat):
                return True
        return False

    def _check_sandbox(self, path: Path) -> bool:
        """是否越出工作区沙箱(True = 越界)。"""
        if not self.sandbox:
            return False
        try:
            return not _is_within(path, self.workspace)
        except OSError:
            return True

    def _command_match(self, command: str, regexes: list[re.Pattern]) -> bool:
        return any(r.search(command) for r in regexes)

    # ------------------------------------------------------------- 裁决入口
    def decide(self, tool_name: str, args: Optional[dict[str, Any]] = None,
               tool=None) -> PermissionDecision:
        args = args or {}
        name = tool_name

        # 层1:工具级规则(显式 deny 名单优先)
        if name in self.deny_tools:
            return PermissionDecision(Decision.DENY, f"工具 {name} 在拒绝名单中", 1)
        # ask_user 是用户交互通道,其余一律放行,避免 interactive 模式自我确认
        if name == "ask_user":
            return PermissionDecision(Decision.ALLOW, "ask_user 为交互选择工具,始终放行", 0)
        if name in self.allow_tools:
            return PermissionDecision(Decision.ALLOW, f"工具 {name} 在白名单中", 1)
        if name in self.ask_tools:
            return PermissionDecision(Decision.ASK, f"工具 {name} 被配置为需确认", 1)

        # 工具声明的路径参数(ReadFile/WriteFile/EditFile/Glob/Grep 等)
        path_args = ["path"]
        if name == "Bash":
            path_args = ["cwd"]

        for pk in path_args:
            if pk in args and args[pk]:
                path = Path(str(args[pk])).expanduser()
                # 相对路径以工作区为基准解析,保证沙箱判断正确
                if not path.is_absolute():
                    path = self.workspace / path
                # 层2:敏感路径拦截
                if self._check_sensitive_path(path):
                    return PermissionDecision(Decision.DENY,
                                              f"目标路径命中敏感目录/文件: {path}", 2)
                # 层3:工作区沙箱
                if self._check_sandbox(path):
                    return self._by_mode(
                        f"路径越出工作区沙箱: {path}", f"越界路径 {path}", layer=3)

        # 层4:危险命令确认(仅 Bash)
        if name == "Bash":
            command = str(args.get("command") or "")
            if self._command_match(command, self.dangerous_commands):
                return self._by_mode(f"命令危险,请确认: {command}",
                                     f"危险命令: {command}", layer=4)

        # 层5:兜底 —— 白名单命令放行;其余按模式
        if name == "Bash":
            command = str(args.get("command") or "")
            if self._command_match(command, self.allow_commands):
                return PermissionDecision(Decision.ALLOW, "命令命中白名单", 5)

        if self.mode == "auto-approve":
            return PermissionDecision(Decision.ALLOW, f"模式=auto-approve,放行 {name}", 5)
        if self.mode == "deny":
            return PermissionDecision(Decision.DENY, f"模式=deny,未知操作 {name} 被拒绝", 5)
        return PermissionDecision(Decision.ASK, f"请确认是否允许调用工具 {name}", 5)

    def _by_mode(self, ask_msg: str, deny_msg: str, layer: int) -> PermissionDecision:
        if self.mode == "interactive":
            return PermissionDecision(Decision.ASK, ask_msg, layer)
        if self.mode == "deny":
            return PermissionDecision(Decision.DENY, deny_msg, layer)
        return PermissionDecision(Decision.ALLOW, "auto-approve 放行", layer)

    # ------------------------------------------------------------- 展示
    def describe(self) -> str:
        lines = [
            f"审批模式: {self.mode}",
            f"工作区沙箱: {'开' if self.sandbox else '关'}(根={self.workspace})",
            f"白名单工具: {', '.join(sorted(self.allow_tools)) or '(无)'}",
            f"拒绝名单工具: {', '.join(sorted(self.deny_tools)) or '(无)'}",
            f"强制确认工具: {', '.join(sorted(self.ask_tools)) or '(无)'}",
            f"敏感路径: {', '.join(self.sensitive_paths) or '(无)'}",
        ]
        return "\n".join(lines)
