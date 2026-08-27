"""Hook 生命周期钩子:在关键节点挂自定义逻辑,自动化更彻底。

支持的事件:
  session_start / session_end
  agent_start   / agent_end
  pre_tool_call / post_tool_call
  pre_message   / post_message

钩子形式(config.yaml):
  hooks:
    pre_tool_call:
      - command: "python notify.py --tool=$TOOL_NAME"   # shell 命令,注入环境变量
      - callable: "myhooks.on_tool_call"                 # 点分路径导入的函数
pre_tool_call 的钩子若返回失败(shell 退出码非 0 / 函数返回 False),会 veto 该工具调用。
钩子失败默认不致命,只记录。
"""

from __future__ import annotations

import importlib
import os
import subprocess
from typing import Any, Callable, Optional

EVENTS = ["session_start", "session_end", "agent_start", "agent_end",
          "pre_tool_call", "post_tool_call", "pre_message", "post_message"]


def _import_callable(path: str) -> Optional[Callable]:
    mod_path, _, fn = path.rpartition(".")
    if not mod_path or not fn:
        return None
    try:
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn)
    except (ImportError, AttributeError):
        return None


class HookManager:
    def __init__(self, hooks_config: Optional[dict[str, Any]] = None):
        hooks_config = hooks_config or {}
        self._hooks: dict[str, list[dict[str, Any]]] = {}
        for event in EVENTS:
            self._hooks[event] = []
        for event, items in hooks_config.items():
            if event not in self._hooks:
                continue
            for item in items or []:
                if isinstance(item, str):
                    item = {"command": item}
                if isinstance(item, dict) and ("command" in item or "callable" in item):
                    self._hooks[event].append(item)

    def _env(self, event: str, **ctx: Any) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"HOOK_EVENT": event, "WORKSPACE": str(ctx.get("workspace", ""))})
        if "tool_name" in ctx:
            env["TOOL_NAME"] = str(ctx["tool_name"])
        if "tool_error" in ctx:
            env["TOOL_ERROR"] = str(ctx["tool_error"])
        return env

    def _run_one(self, hook: dict[str, Any], event: str, **ctx: Any) -> bool:
        """返回 True 表示放行;pre_tool_call 时 False = veto。"""
        if "command" in hook:
            cmd = str(hook["command"])
            try:
                r = subprocess.run(cmd, shell=True, env=self._env(event, **ctx),
                                   capture_output=True, text=True, timeout=30,
                                   encoding="utf-8", errors="replace")
                return r.returncode == 0
            except Exception:
                return True
        if "callable" in hook:
            fn = _import_callable(str(hook["callable"]))
            if fn is None:
                return True
            try:
                return fn(event=event, **ctx) is not False
            except Exception:
                return True
        return True

    def fire(self, event: str, **ctx: Any) -> None:
        """触发一次性事件;任何失败只记录,不中断主流程。"""
        for hook in self._hooks.get(event, []):
            try:
                self._run_one(hook, event, **ctx)
            except Exception:
                continue

    def fire_pre_tool(self, tool_name: str, arguments: dict, tool=None) -> bool:
        """pre_tool_call 钩子;任一 veto(False/非0)则拦截。"""
        ctx = {"tool_name": tool_name, "arguments": arguments, "tool": tool}
        ok = True
        for hook in self._hooks.get("pre_tool_call", []):
            if not self._run_one(hook, "pre_tool_call", **ctx):
                ok = False
        return ok

    def fire_post_tool(self, tool_name: str, result) -> None:
        self.fire("post_tool_call", tool_name=tool_name,
                  tool_success=result.success, tool_error=result.error)

    def summary(self) -> str:
        lines = []
        for event in EVENTS:
            n = len(self._hooks.get(event, []))
            if n:
                lines.append(f"- {event}: {n} 个钩子")
        return "\n".join(lines) or "(未配置钩子)"
