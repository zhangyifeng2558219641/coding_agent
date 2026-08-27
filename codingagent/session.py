"""会话上下文:把 config/client/registry/memory/hooks/skills/mcp 组装起来,
CLI 与 Web 共用同一套装配逻辑,并提供 agent 工厂。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .agent import AgentLoop, MemoryStore, PermissionPolicy
from .hooks import HookManager
from .agent.loop import UISink
from .commands import SlashRegistry
from .commands.builtins import register_builtin_commands
from .config import Config
from .llm import ChatClient, History, client_from_config
from .skills import SkillManager
from .tools import MCPManager, ToolRegistry, default_registry


@dataclass
class SessionContext:
    """传给斜杠命令处理器的最小上下文。"""

    agent: Any
    config: Any
    workspace: Path
    registry: ToolRegistry
    memory: Any
    skills: Any
    mcp: Any
    slash: Any
    ui: Any
    cli_running: bool = True


class Session:
    def __init__(self, config: Config, ui: Optional[UISink] = None):
        self.config = config
        self.workspace = config.workspace
        self.ui = ui or UISink()
        self.client = client_from_config(config)
        self.registry = default_registry(with_memory=True, with_agent_tools=True)
        self.memory = MemoryStore(config, self.workspace)
        self.hooks = HookManager(config.get("hooks"))
        self.permissions = PermissionPolicy(config.permissions, self.workspace)
        self.history = History(
            budget_tokens=config.context.get("budget_tokens", 64000),
            max_tool_output=config.context.get("max_tool_output", 30000),
        )
        self.skills = SkillManager((config.get("skills") or {}).get("dirs", []),
                                   history=self.history, registry=self.registry)
        self.mcp = MCPManager()
        self.slash = SlashRegistry()
        register_builtin_commands(self.slash)
        self.cli_running = True

        # 基础 system 提示
        self.history.add_system_part("base", self._base_prompt())
        if self.memory.enabled:
            self.history.add_system_part("memory", self.memory.load_all())
        if skills_block := self.skills.available_block():
            self.history.add_system_part("skills", skills_block)
        self.slash.load_custom((config.get("commands") or {}).get("dir", ".coding_agent/commands"))

    def _base_prompt(self) -> str:
        from .prompts import base_system_prompt
        return base_system_prompt(self.workspace)

    def context(self, agent: AgentLoop) -> SessionContext:
        return SessionContext(
            agent=agent, config=self.config, workspace=self.workspace,
            registry=self.registry, memory=self.memory, skills=self.skills,
            mcp=self.mcp, slash=self.slash, ui=self.ui, cli_running=self.cli_running,
        )

    def make_agent(self, history: Optional[History] = None, ui: Optional[UISink] = None,
                   permission_mode: Optional[str] = None) -> AgentLoop:
        """按传入的 history 构造 AgentLoop;history 缺省用会话默认历史。

        传入 history 时同样会补齐 system 提示(基础/记忆/技能),保证子会话独立可用。
        """
        h = history or self.history
        h.add_system_part("base", self._base_prompt())
        if self.memory.enabled:
            h.add_system_part("memory", self.memory.load_all())
        if skills_block := self.skills.available_block():
            h.add_system_part("skills", skills_block)
        permissions = self.permissions
        if permission_mode:
            perms_cfg = dict(self.config.permissions)
            perms_cfg["mode"] = permission_mode
            permissions = PermissionPolicy(perms_cfg, self.workspace)
        return AgentLoop(
            self.config, self.workspace, self.client, self.registry,
            permissions=permissions, memory=self.memory, history=h,
            ui=ui or self.ui, hooks=self.hooks,
            options=None,
        )

    def connect_mcp_from_config(self) -> list[str]:
        servers = (self.config.get("mcp") or {}).get("servers", {})
        if not servers:
            return []
        return self.mcp.connect_from_config(servers, self.registry)

    def close(self) -> None:
        self.mcp.close_all()

    # ------------------------------------------------------------------ 会话持久化
    def save_history(self, history: History, cid: str) -> None:
        store = self.config.session_store_path()
        try:
            store.mkdir(parents=True, exist_ok=True)
            import json
            (store / f"{cid}.json").write_text(
                json.dumps(history.to_dict(), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def load_history(self, cid: str) -> Optional[History]:
        store = self.config.session_store_path()
        path = store / f"{cid}.json"
        if not path.exists():
            return None
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            h = History(budget_tokens=self.config.context.get("budget_tokens", 64000),
                        max_tool_output=self.config.context.get("max_tool_output", 30000))
            h.load_dict(data)
            return h
        except Exception:
            return None
