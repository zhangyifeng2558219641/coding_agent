"""Skill 技能包系统:把 prompt + 工具 + 资源打包成可装载的技能包。

技能包 = 一个目录,内含:
  SKILL.md       —— frontmatter(name/description) + 正文 instructions(prompt)
  tools/*.py     —— 可选,定义额外 Tool(暴露 TOOLS 列表或 register(registry))
  resources/**   —— 可选,技能附带的静态资源

Agent 通过「装技能」的方式持续扩展能力;装载后 instructions 注入 system,
tools 注册进工具注册表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import util
from pathlib import Path
from typing import Any, Optional

import yaml

from ..tools import Tool, ToolRegistry


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    path: Path
    tools_dir: Optional[Path] = None
    resources_dir: Optional[Path] = None
    tool_names: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        return f"{self.name}: {self.description}"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析 SKILL.md 的 --- frontmatter --- 与正文。"""
    lines = text.splitlines()
    if not (lines and lines[0].strip() == "---"):
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:]).strip()
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


class SkillManager:
    def __init__(self, dirs: list[str | Path], history=None, registry: Optional[ToolRegistry] = None):
        self._dirs = [Path(d).expanduser().resolve() for d in dirs]
        self.history = history
        self.registry = registry
        self._skills: dict[str, Skill] = {}
        self._loaded: set[str] = set()
        self._scan()

    # ------------------------------------------------------------------ 扫描
    def _scan(self) -> None:
        self._skills.clear()
        for base in self._dirs:
            if not base.is_dir():
                continue
            for md in base.rglob("SKILL.md"):
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError:
                    continue
                fm, body = _parse_frontmatter(text)
                name = (fm.get("name") or md.parent.name).strip()
                self._skills[name] = Skill(
                    name=name,
                    description=str(fm.get("description") or "").strip(),
                    instructions=body,
                    path=md.parent,
                    tools_dir=md.parent / "tools",
                    resources_dir=md.parent / "resources",
                )

    # ------------------------------------------------------------------ 查询
    def list(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def available_block(self) -> str:
        """供 system 提示:列出可用技能,让模型知道能装什么。"""
        if not self._skills:
            return ""
        lines = ["可用技能(Skill):"]
        for s in self.list():
            marker = "(已装载)" if s.name in self._loaded else ""
            lines.append(f"- {s.name}: {s.description} {marker}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 装载/卸载
    def load(self, name: str) -> str:
        skill = self._skills.get(name)
        if not skill:
            return f"未找到技能: {name}(可用: {', '.join(self._skills) or '无'})"
        if name in self._loaded:
            return f"技能 {name} 已装载"
        self._loaded.add(name)
        if self.history:
            self.history.add_system_part(f"skill:{name}", self._render(skill))
        if self.registry and skill.tools_dir and skill.tools_dir.is_dir():
            self._load_tools(skill)
        return f"已装载技能 {name}: {skill.description}"

    def unload(self, name: str) -> str:
        if name not in self._loaded:
            return f"技能 {name} 未装载"
        self._loaded.discard(name)
        if self.history:
            self.history.remove_system_part(f"skill:{name}")
        if self.registry:
            skill = self.get(name)
            if skill:
                for t in skill.tool_names:
                    self.registry.unregister(t)
        return f"已卸载技能 {name}"

    def loaded(self) -> list[str]:
        return sorted(self._loaded)

    def _render(self, skill: Skill) -> str:
        parts = [f"【技能:{skill.name}】{skill.description}", skill.instructions]
        if skill.resources_dir and skill.resources_dir.is_dir():
            files = ", ".join(p.name for p in skill.resources_dir.iterdir())
            parts.append(f"资源: {files}(位于 {skill.resources_dir})")
        return "\n".join(p for p in parts if p)

    def _load_tools(self, skill: Skill) -> None:
        for py in skill.tools_dir.glob("*.py"):
            mod_name = f"_skill_{skill.name}_{py.stem}"
            try:
                spec = util.spec_from_file_location(mod_name, py)
                mod = util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                print(f"[skills] 载入 {py.name} 失败: {e}")
                continue
            found = getattr(mod, "TOOLS", None) or []
            for tool in found:
                if isinstance(tool, Tool):
                    self.registry.register(tool)
                    skill.tool_names.append(tool.name)
