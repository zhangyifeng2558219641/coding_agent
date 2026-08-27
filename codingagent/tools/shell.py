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
from typing import Any

from .base import Tool, ToolContext
from ..types import ToolResult, truncate

MAX_OUTPUT = 20000


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), 9)
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

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["WORKSPACE"] = str(ctx.workspace)
        env["CWD"] = str(cwd)

        bash = shutil.which("bash")
        if bash:
            argv = [bash, "-c", command]
            start_new_session = True
        else:
            argv = command
            start_new_session = False

        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout, shell=not bash,
                start_new_session=start_new_session,
            )
            rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as e:
            if e.stdout:
                stdout = e.stdout.decode("utf-8", "replace")
            else:
                stdout = ""
            stderr = f"(命令执行超过 {timeout}s,已终止)"
            rc = 124
        except OSError as e:
            return ToolResult(name=self.name, success=False, error=f"无法执行命令: {e}")

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
