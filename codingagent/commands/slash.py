"""Slash Command 命令框架:内置 + 用户自定义的斜杠命令,常用操作一键触发。

内置命令在 CLI/Web 会话层注册(它们需要访问会话对象);
自定义命令放到 <workspace>/.coding_agent/commands/*.md:
  首行 "# 名称 - 一句话说明",其余为发送给 Agent 的 prompt 模板,
  模板里 {args} 会被替换成命令参数,一键复用常用流程。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional


class SlashExit(Exception):
    """抛出后结束会话(用于 /exit 等)。"""


class SlashCommand:
    def __init__(self, name: str, description: str,
                 handler: Callable[["SlashSession", str], Optional[str]],
                 aliases: tuple[str, ...] = (), hidden: bool = False):
        self.name = name.lstrip("/")
        self.description = description
        self.handler = handler
        self.aliases = aliases
        self.hidden = hidden

    def matches(self, name: str) -> bool:
        name = name.lstrip("/").lower()
        return name == self.name.lower() or name in tuple(a.lower() for a in self.aliases)


class SlashRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, cmd: SlashCommand) -> None:
        self._commands[cmd.name] = cmd

    def get(self, name: str) -> Optional[SlashCommand]:
        name = name.lstrip("/")
        for cmd in self._commands.values():
            if cmd.matches(name):
                return cmd
        return None

    def list(self, include_hidden: bool = False) -> list[SlashCommand]:
        return [c for c in self._commands.values() if include_hidden or not c.hidden]

    def run(self, name: str, args: str, session: "SlashSession") -> Optional[str]:
        cmd = self.get(name)
        if cmd is None:
            return f"未知命令 /{name.lstrip('/')},输入 /help 查看可用命令"
        return cmd.handler(session, args)

    # ------------------------------------------------------------------ 自定义
    def load_custom(self, commands_dir: str | Path) -> int:
        """加载 .coding_agent/commands/*.md 为自定义命令,返回加载数量。"""
        d = Path(commands_dir).expanduser()
        if not d.is_dir():
            return 0
        n = 0
        for md in d.glob("*.md"):
            try:
                lines = md.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            if not lines:
                continue
            first = lines[0].strip().lstrip("#").strip()
            name, _, desc = first.partition("-")
            name = name.strip()
            if not name:
                continue
            template = "\n".join(lines[1:]).strip()
            self.register(SlashCommand(name, desc.strip() or "自定义命令",
                                       _make_custom_handler(template)))
            n += 1
        return n


def _make_custom_handler(template: str):
    def handler(session: "SlashSession", args: str) -> str:
        prompt = template.replace("{args}", args).strip()
        if not prompt:
            return "(自定义命令模板为空)"
        result = session.agent.run(prompt)
        return result.text
    return handler
