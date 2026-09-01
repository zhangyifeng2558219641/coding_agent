"""终端 UI(类 Claude Code 的交互体验):
流式输出 + 多轮对话 + 工具调用面板 + 斜杠命令 + 多行输入。"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel

from ..agent.checkpoint import CheckpointStore
from ..agent.loop import UISink
from ..commands.slash import SlashExit

BANNER = r"""
╭──────────────────────────────────────────────╮
│   coding_agent · 编程智能体(类 Claude Code)   │
│   模型可配 · 工具自主 · 权限可控 · 双端交互     │
╰──────────────────────────────────────────────╯
输入任务与 Agent 对话;/help 查看命令;Ctrl+C 中断当前回合
"""


class CLIUI(UISink):
    def __init__(self) -> None:
        self.console = Console(highlight=False, markup=False)
        self._in_text = False

    # ------------------------------------------------------------------ 事件
    def event(self, type: str, data: dict[str, Any]) -> None:
        try:
            getattr(self, f"_ev_{type}")(data)
        except (AttributeError, KeyError):
            pass

    def _ev_text(self, d: dict[str, Any]) -> None:
        delta = d.get("delta", "")
        sys.stdout.write(delta)
        sys.stdout.flush()
        self._in_text = True

    def _ev_tool_call(self, d: dict[str, Any]) -> None:
        self._end_text()
        status = d.get("status", "auto")
        name = d.get("name", "")
        args = d.get("arguments", {})
        style = {"denied": "red", "declined": "yellow", "allowed": "green",
                 "auto": "cyan"}.get(status, "cyan")
        title = f"工具调用: {name}"
        if status == "denied":
            title += "  ✗ 已被权限拦截"
        elif status == "declined":
            title += "  ✗ 用户拒绝"
        try:
            body = json.dumps(args, ensure_ascii=False, indent=2) if args else "(无参数)"
        except Exception:
            body = str(args)
        self.console.print(Panel(body, title=title, border_style=style, expand=False))

    def _ev_tool_result(self, d: dict[str, Any]) -> None:
        name = d.get("name", "")
        ok = d.get("success", True)
        out = str(d.get("output", ""))[:800]
        color = "green" if ok else "red"
        self.console.print(Panel(out, title=f"工具结果: {name}",
                                 border_style=color, expand=False))

    def _ev_status(self, d: dict[str, Any]) -> None:
        self._end_text()
        self.console.print(d.get("message", ""), style="dim")

    def _ev_compact(self, d: dict[str, Any]) -> None:
        self.console.print("(上下文已压缩)", style="dim")

    def _ev_turn_end(self, d: dict[str, Any]) -> None:
        self._end_text()
        u = d.get("usage", {})
        self.console.print(
            f"· 回合结束({d.get('iterations')} 轮工具,耗时 {d.get('elapsed')}s,"
            f"tok: {u.get('prompt_tokens', 0)}/{u.get('completion_tokens', 0)})",
            style="dim")

    def _ev_error(self, d: dict[str, Any]) -> None:
        self._end_text()
        self.console.print(f"✗ 错误: {d.get('message', '')}", style="red")

    def _end_text(self) -> None:
        if self._in_text:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_text = False

    # ------------------------------------------------------------------ 交互
    def ask(self, question: str) -> bool:
        self._end_text()
        while True:
            try:
                answer = self.console.input(f"[yellow]{question}[/yellow]\n[yellow]允许? [y/n]: [/yellow]")
            except (EOFError, KeyboardInterrupt):
                return False
            a = answer.strip().lower()
            if a in ("y", "yes", "是", "允许"):
                return True
            if a in ("n", "no", "否", "拒绝"):
                return False

    def choose(self, prompt: str, options: list[str]) -> Optional[int | str]:
        """交互选择:打印编号列表(含「其他/自定义」)并等待输入。

        返回 0-based 索引、-1(取消),或用户输入的自定义文本。
        """
        self._end_text()
        console = self.console
        console.print(prompt)
        for i, opt in enumerate(options, 1):
            console.print(f"  [{i}] {opt}")
        other = len(options) + 1
        console.print(f"  [{other}] 其他(自行输入)")
        while True:
            try:
                ans = console.input(f"[yellow]请选择编号(0 取消,{other} 其他): [/yellow]")
            except (EOFError, KeyboardInterrupt):
                return -1
            ans = ans.strip()
            if ans == "0":
                return -1
            try:
                n = int(ans)
            except ValueError:
                console.print("(请输入数字)", style="dim")
                continue
            if 1 <= n <= len(options):
                return n - 1
            if n == other:
                try:
                    txt = console.input("[yellow]请输入你的选择: [/yellow]")
                except (EOFError, KeyboardInterrupt):
                    return -1
                return txt.strip() if txt.strip() else -1
            console.print(f"(编号需在 1-{other} 之间)", style="dim")


def _read_multiline(console: Console) -> str:
    """读取输入;以 \\ 结尾的行自动续行(多行输入)。"""
    parts = []
    try:
        first = console.input("[bold cyan]> [/bold cyan]")
    except (EOFError, KeyboardInterrupt):
        raise
    parts.append(first)
    while first.rstrip().endswith("\\"):
        first = first.rstrip()[:-1] + " "
        parts[-1] = first
        try:
            line = console.input("[dim]... [/dim]")
        except (EOFError, KeyboardInterrupt):
            break
        parts.append(line)
    return "".join(parts).strip()


def _ensure_stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _split_slash(line: str) -> tuple[str, str]:
    name, _, args = line[1:].partition(" ")
    return name, args.strip()


def run_cli(session) -> None:
    """交互式 REPL。session 为 codingagent.session.Session。"""
    _ensure_stdout_utf8()
    console = session.ui.console if isinstance(session.ui, CLIUI) else Console()
    console.print(BANNER)

    connected = session.connect_mcp_from_config()
    if connected:
        console.print(f"MCP 已连接: {', '.join(connected)}", style="dim")

    # 本次 CLI 会话的唯一标识:历史保存为 cli-<时间戳>.json,便于 /resume 区分多次会话
    cli_sid = time.strftime("%Y%m%d-%H%M%S")
    # 检查点存储:本会话文件快照持久化到 cli-<时间戳>.checkpoints.json
    cps = CheckpointStore(session.config.session_store_path() / f"cli-{cli_sid}.checkpoints.json")
    agent = session.make_agent(checkpoints=cps)
    ctx = session.context(agent)
    session.cli_running = True

    console.print(f"工作区: {session.workspace}   模型: {agent.client.model}", style="dim")

    while session.cli_running:
        try:
            line = _read_multiline(console)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见。[/dim]")
            break
        if not line:
            continue
        if line.startswith("/"):
            before = len(agent.history.messages)
            try:
                response = session.slash.run(*_split_slash(line), ctx)
            except SlashExit as e:
                console.print(str(e), style="dim")
                break
            if response:
                console.print(response)
            # 内置命令(如 /team)不写历史,记录输入输出,与普通对话一样可 /resume 恢复;
            # 自定义命令经 agent.run 已自行追加,消息数变化即跳过,避免重复记录。
            if len(agent.history.messages) == before:
                agent.history.append({"role": "user", "content": line})
                agent.history.append({"role": "assistant", "content": response or "(无输出)"})
            session.save_history(agent.history, f"cli-{cli_sid}")
            continue
        try:
            agent.run(line)
        except KeyboardInterrupt:
            console.print("\n(已中断当前回合,可继续对话)", style="yellow")
        except Exception as e:
            console.print(f"✗ 回合异常: {e}", style="red")
        finally:
            # 持久化会话历史,供下次启动 /resume 恢复(每个 CLI 会话独立文件)
            session.save_history(agent.history, f"cli-{cli_sid}")

    session.close()


def run_once(session, task: str) -> int:
    """一次性模式:python -m codingagent run \"任务\"。非交互,适合脚本/演示。"""
    _ensure_stdout_utf8()
    console = session.ui.console if isinstance(session.ui, CLIUI) else Console()
    console.print(f"一次性任务 · 工作区 {session.workspace} · 模型 {session.client.model}", style="dim")
    session.connect_mcp_from_config()
    agent = session.make_agent()
    try:
        result = agent.run(task)
    except KeyboardInterrupt:
        console.print("\n(已中断)", style="yellow")
        return 130
    finally:
        session.close()
    if result.text:
        console.print(f"——— 最终结果 ———\n{result.text}", style="bold")
    if not result.success:
        console.print(f"✗ 任务未成功完成: {result.error}", style="red")
        return 1
    return 0
