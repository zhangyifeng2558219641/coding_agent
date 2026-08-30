"""Shell 工具:Bash —— 在本地沙箱执行命令并返回结果。

- 优先用 bash -c(若系统存在 bash),否则退化为系统默认 shell(cmd/PowerShell);
- 超时强制终止(Windows 下用 taskkill 杀进程树);
- 输出截断,避免巨型输出打爆上下文。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext
from ..types import ToolResult, truncate

MAX_OUTPUT = 20000


# System32\bash.exe 是 WSL 启动器、WindowsApps\bash.exe 是应用别名,
# 都不是真正的独立 bash,无法正确处理 Windows 路径,必须排除。
_BAD_BASH_MARKERS = ("system32", "windowsapps")


def _git_bash_paths(bash: str) -> list[str]:
    """非交互 bash -c 不会 source 配置文件,可能找不到 ls/grep 等 coreutils。
    若 bash 位于 <Git>\\usr\\bin,补上 mingw64\\bin 等 Git 自带 bin 目录。"""
    bdir = os.path.dirname(bash)
    paths = [bdir]
    if os.path.basename(bdir) == "bin":
        parent = os.path.dirname(bdir)
        git_root = os.path.dirname(parent) if os.path.basename(parent) == "usr" else parent
        for sub in ("mingw64\\bin", "usr\\local\\bin"):
            p = os.path.join(git_root, sub)
            if os.path.isdir(p):
                paths.append(p)
    return paths


def _find_bash() -> Optional[str]:
    """定位可用的真 bash。

    Windows 的 PATH 常常只含 Git\\cmd 而不含 Git\\usr\\bin,导致 bash/ls/grep
    找不到;且 System32\\bash.exe 是 WSL 启动器,WindowsApps\\bash.exe 是应用别名,
    二者都不可用。故先查已知 Git 安装位置,再退化为 PATH 里非伪装的 bash。
    """
    for candidate in (
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    found = shutil.which("bash")
    if found and not any(m in found.lower() for m in _BAD_BASH_MARKERS):
        return found
    return None


def _kill_tree(proc: subprocess.Popen) -> None:
    """整树终止:taskkill /T(Windows)或按进程组 kill(POSIX)。

    不要用 proc.poll() 提前返回:超时清理时,直接子进程可能已退出但孙进程
    (后台任务/curl)仍持有管道,照样需要连根清除。
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            # start_new_session=True 使直接子进程成为新会话组长(组号=其 pid);
            # 组长已退出时按组号仍可清掉残留孙进程。
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except ProcessLookupError:
                os.killpg(proc.pid, 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class Bash(Tool):
    name = "Bash"
    description = (
        "在本地 shell 中执行命令(可用管道/重定向,可调用 python/node/git 等)。"
        "返回退出码、stdout 与 stderr。用于构建、测试、运行脚本等。"
        "工作目录默认是当前工作区;命令必须安全、可撤回。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "cwd": {"type": "string", "description": "执行目录(可选,默认当前)"},
            "timeout": {"type": "integer", "description": "超时秒数,默认 120"},
        },
        "required": ["command"],
    }
    category = "shell"

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return ToolResult(name=self.name, success=False, error="command 为空")
        cwd = ctx.resolve(kwargs["cwd"]) if kwargs.get("cwd") else (ctx.cwd or ctx.workspace)
        timeout = int(kwargs.get("timeout") or 120)

        bash = _find_bash()

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["WORKSPACE"] = str(ctx.workspace)
        env["CWD"] = str(cwd)
        if bash:
            extra = _git_bash_paths(bash)
            if extra:
                env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])

        if bash:
            argv = [bash, "-c", command]
            start_new_session = True
        else:
            argv = command
            start_new_session = False

        # stdout/stderr 落到临时文件而非捕获管道:Windows 下用管道时,后台任务
        # /孙进程(curl、后台 server 等)会继承管道写端,读端永远等不到 EOF,
        # 导致 communicate() 永久阻塞(subprocess.run 的经典死锁,工具随之卡死)。
        # 改为临时文件后父进程只 proc.wait(超时),不依赖管道 EOF,天然免疫该问题。
        with tempfile.TemporaryDirectory(prefix="coding_agent_",
                                         ignore_cleanup_errors=True) as td:
            out_path = os.path.join(td, "stdout.txt")
            err_path = os.path.join(td, "stderr.txt")
            try:
                with open(out_path, "w", encoding="utf-8", errors="replace") as fo, \
                     open(err_path, "w", encoding="utf-8", errors="replace") as fe:
                    proc = subprocess.Popen(
                        argv, cwd=str(cwd), env=env,
                        stdin=subprocess.DEVNULL, stdout=fo, stderr=fe,
                        shell=not bash,
                        start_new_session=start_new_session,
                    )
            except OSError as e:
                return ToolResult(name=self.name, success=False, error=f"无法执行命令: {e}")

            try:
                rc = proc.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                _kill_tree(proc)  # 超时:整树终止,不留后台进程/孙进程占资源
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                rc = 124
                timed_out = True

            def _read(p: str) -> str:
                try:
                    return Path(p).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return ""

            stdout, stderr = _read(out_path), _read(err_path)
            if timed_out:
                stderr = f"(命令执行超过 {timeout}s,已终止)\n{stderr}".strip()

        output = ""
        if stdout:
            output += stdout
        if stderr:
            output += ("\n" if output else "") + f"[stderr]\n{stderr}"
        output = truncate(output, MAX_OUTPUT)
        head = f"$ {command}"
        body = f"{head}\n退出码: {rc}"
        if output:
            body += f"\n{output}"
        return ToolResult(name=self.name, success=(rc == 0), output=body,
                          error="" if rc == 0 else f"退出码 {rc}")
