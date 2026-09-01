"""内置斜杠命令(CLI/Web 共用)。handler 签名: (ctx: SessionContext, args: str) -> str|None。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..agent import Team, TeamMember, WorktreeManager, WorktreeError
from .slash import SlashCommand, SlashExit


def _help(ctx, args: str) -> str:
    cmds = ctx.slash.list()
    lines = ["可用命令(斜杠命令):"]
    for c in cmds:
        lines.append(f"  /{c.name:<12} {c.description}")
    lines.append("\n提示:以 / 开头输入命令;输入普通文字即与 Agent 对话。")
    return "\n".join(lines)


def _exit(ctx, args: str) -> str:
    ctx.cli_running = False
    raise SlashExit("再见。")


def _clear(ctx, args: str) -> str:
    ctx.agent.history.clear()
    return "(已清空当前会话历史,上下文从零开始)"


def _model(ctx, args: str) -> str:
    model = args.strip() or ctx.config.provider.get("model")
    if args.strip():
        ctx.config.provider["model"] = args.strip()
        ctx.agent.client.model = args.strip()
        return f"已切换模型: {args.strip()}"
    return f"当前模型: {model}\n切换:/model <模型名>"


def _tools(ctx, args: str) -> str:
    names = sorted(ctx.registry.names())
    return f"当前可用工具({len(names)}):\n  " + "\n  ".join(names)


def _permissions(ctx, args: str) -> str:
    policy = ctx.agent.permissions
    return policy.describe()


def _memory(ctx, args: str) -> str:
    a = args.strip()
    if a.startswith("clear"):
        scope = a.split()[-1] if len(a.split()) > 1 else None
        if ctx.memory:
            ctx.memory.clear(scope)
            return f"(已清空记忆: {scope or '全部'})"
    if a.startswith("save"):
        scope, _, entry = a[len("save"):].strip().partition(" ")
        ctx.memory.append(scope or "project", entry.strip())
        return f"(已保存到 {scope or 'project'} 记忆)"
    if a.startswith("user"):
        return ctx.memory.load_user() if ctx.memory else "(无)"
    if a.startswith("project"):
        return ctx.memory.load_project() if ctx.memory else "(无)"
    return (ctx.memory.load_all() if ctx.memory else "(无)") + (
        "\n\n用法:/memory [project|user|save <scope> <条目>|clear [scope]]")


def _skills(ctx, args: str) -> str:
    a = args.strip()
    parts = a.split()
    if not parts or parts[0] == "list":
        lines = ["可用技能:"]
        for s in ctx.skills.list():
            state = "●" if s.name in ctx.skills.loaded() else "○"
            lines.append(f"  {state} {s.name} — {s.description}")
        return "\n".join(lines) + "\n用法:/skills load <名称> | unload <名称>"
    cmd = parts[0]
    name = parts[1] if len(parts) > 1 else ""
    if cmd == "load":
        return ctx.skills.load(name)
    if cmd == "unload":
        return ctx.skills.unload(name)
    return "/skills list|load <名称>|unload <名称>"


def _compact(ctx, args: str) -> str:
    agent = ctx.agent
    ok = agent.history.compact(agent._summarize)
    return f"(已{'完成' if ok else '无需'}压缩;当前摘要:\n{agent.history.summary or '(无)'})"


def _cost(ctx, args: str) -> str:
    u = ctx.agent.usage
    est_cost = (u.prompt_tokens + u.completion_tokens) / 1_000_000 * 1.0  # 粗略按 $1/M
    return (f"本会话累计 token: prompt {u.prompt_tokens}, completion {u.completion_tokens},"
            f" 合计 {u.total}\n(估算费用 ≈ ${est_cost:.4f},按 $1/M 粗算)")


def _mcp(ctx, args: str) -> str:
    a = args.strip().split()
    cmd = a[0] if a else "list"
    if cmd == "list":
        servers = ctx.mcp.list_servers()
        return f"已连接 MCP servers: {', '.join(servers) or '(无)'}"
    if cmd == "connect":
        name = a[1] if len(a) > 1 else ""
        if not name:
            return "/mcp connect <server名>(需要在 config.yaml 的 mcp.servers 配置)"
        servers = (ctx.config.get("mcp") or {}).get("servers", {})
        cfg = servers.get(name)
        if not cfg:
            return f"未配置 MCP server: {name}"
        try:
            tools = ctx.mcp.connect(name, cfg.get("command", ""), cfg.get("args") or [],
                                    cfg.get("env"), cfg.get("cwd"), registry=ctx.registry)
            return f"已连接 {name},注册 {len(tools)} 个工具: {', '.join(tools)}"
        except Exception as e:
            return f"连接 {name} 失败: {e}"
    if cmd == "disconnect":
        name = a[1] if len(a) > 1 else ""
        ok = ctx.mcp.disconnect(name)
        return f"已断开 {name}" if ok else f"未连接: {name}"
    return "/mcp list|connect <名>|disconnect <名>"


def _team(ctx, args: str) -> str:
    a = args.strip()
    if not a:
        return "用法:/team <团队名> <任务>"
    name, _, task = a.partition(" ")
    teams_cfg = (ctx.config.get("teams") or {})
    team_cfg = teams_cfg.get(name)
    if not team_cfg:
        return f"未找到团队 {name}(config.yaml 的 teams 中可用: {', '.join(teams_cfg) or '无'})"
    members = [TeamMember.from_dict(m) for m in team_cfg.get("members", [])]
    if not members:
        return f"团队 {name} 没有成员"
    team = Team(name, members, ctx.config, ctx.workspace, ctx.agent.client,
                ctx.registry, permissions=ctx.agent.permissions, ui=ctx.agent.ui,
                stop_event=getattr(ctx.agent, "stop_event", None))
    r = team.run(task)
    text = r.final_text or r.error or "(空结果)"
    if r.saved_to:
        text += f"\n\n> 汇总文档已写入: {r.saved_to}"
    return text


def _worktree(ctx, args: str) -> str:
    a = args.strip().split()
    cmd = a[0] if a else "list"
    mgr = WorktreeManager(ctx.workspace)
    if not mgr.is_repo():
        return f"{ctx.workspace} 不是 git 仓库,无法使用 worktree"
    if cmd == "list":
        infos = mgr.list()
        lines = ["Git worktrees:"]
        for i in infos:
            lines.append(f"  {i.path}  branch={i.branch}  head={i.head}")
        return "\n".join(lines)
    if cmd == "create":
        branch = a[1] if len(a) > 1 else None
        try:
            info = mgr.create(branch=branch)
            return f"已创建 worktree:\n  路径: {info.path}\n  分支: {info.branch}"
        except WorktreeError as e:
            return f"创建失败: {e}"
    if cmd == "remove":
        if len(a) < 2:
            return "/worktree remove <路径>"
        try:
            mgr.remove(Path(a[1]))
            return f"已移除 worktree: {a[1]}"
        except WorktreeError as e:
            return f"移除失败: {e}"
    return "/worktree list|create [分支]|remove <路径>"


def _plan(ctx, args: str):
    """进入计划模式;带任务时一条龙:只读研究出计划 → 审批 → 执行。"""
    agent = ctx.agent
    agent.plan_mode = True
    if not args.strip():
        return ("已进入计划模式:只做只读调研并输出计划,不会修改任何文件。\n"
                "用法:/plan <任务> 一条龙(计划→审批→执行);或直接描述任务,满意后 /execute 退出执行。")
    agent.run(args.strip())  # 只读调研 + 输出计划(流式展示)
    if agent.ui.ask("已生成计划(见上)。批准并执行?(y/n)"):
        agent.plan_mode = False
        agent.run("请按上面的计划开始执行该任务。")
        return None  # 执行结果已流式展示,避免 CLI 重复打印
    return "计划未批准,仍处于计划模式,可继续调整,或 /execute 退出执行。"


def _execute(ctx, args: str) -> str:
    """退出计划模式,开始正常执行(可写文件)。"""
    ctx.agent.plan_mode = False
    return "已退出计划模式,现在可以正常执行写操作。如需按之前的计划执行,请直接下达指令。"


def _status(ctx, args: str) -> str:
    u = ctx.agent.usage
    return (f"工作区: {ctx.workspace}\n"
            f"模型: {ctx.agent.client.model}\n"
            f"迭代: 最大 {ctx.config.agent.get('max_iterations')}\n"
            f"上下文预算: {ctx.config.context.get('budget_tokens')} tokens\n"
            f"已用: prompt {u.prompt_tokens} / completion {u.completion_tokens}\n"
            f"工具: {len(ctx.registry.names())} 个\n"
            f"技能: {len(ctx.skills.list())} 个(已装载 {len(ctx.skills.loaded())})\n"
            f"MCP: {len(ctx.mcp.list_servers())} 个")


def _fmt_cli_session(f: Path) -> str:
    """把 cli-<时间戳>.json 显示成可读时间;旧版单文件 cli.json 标注为旧版。"""
    stem = f.stem
    if not stem.startswith("cli-"):
        return "旧版会话"
    ts = stem[len("cli-"):]
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.strptime(ts, "%Y%m%d-%H%M%S"))
    except ValueError:
        return ts


def _resume(ctx, args: str) -> str:
    """恢复 CLI 历史会话:不带参数恢复最新,list 列出全部,数字编号选择指定会话。"""
    store = ctx.config.session_store_path()
    if not store.exists():
        return "(无历史会话)"
    # 每个 CLI 会话一个 cli-<时间戳>.json(新在前);旧版单文件 cli.json 视为最旧
    files = sorted((f for f in store.glob("cli-*.json") if f.is_file()), reverse=True)
    legacy = store / "cli.json"
    if legacy.is_file():
        files.append(legacy)
    if not files:
        return "(无历史会话)"

    a = args.strip().lower()
    if a in ("list", "ls", "-l"):
        lines = ["可用 CLI 会话历史(最新在前):"]
        for i, f in enumerate(files, 1):
            lines.append(f"  [{i}] {_fmt_cli_session(f)}  ({f.name})")
        lines.append("用法:/resume [编号] —— 恢复指定会话;不带编号交互选择(单个会话时直接恢复)")
        return "\n".join(lines)

    if a:
        try:
            idx = int(a)
        except ValueError:
            return f"无效编号: {a}(用 /resume list 查看会话列表)"
        if not (1 <= idx <= len(files)):
            return f"编号越界: {idx}(共 {len(files)} 个会话,用 /resume list 查看)"
        latest = files[idx - 1]
    elif len(files) > 1:
        # 多个会话:交互选择;无交互能力的 UI(如 Web)回退到最新
        picked = ctx.ui.choose(
            "检测到多个 CLI 历史会话,请选择要恢复的:",
            [f"{_fmt_cli_session(f)}  ({f.name})" for f in files])
        if picked is None:
            latest = files[0]
        elif picked == -1:
            return "(已取消恢复)"
        elif isinstance(picked, int):
            latest = files[picked]
        else:
            return "(已取消恢复)"
    else:
        latest = files[0]

    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        ctx.agent.history.messages = data.get("messages", [])
        ctx.agent.history.summary = data.get("summary", "")
        ctx.agent.history.compact_count = data.get("compact_count", 0)
        return f"已恢复会话历史 {latest.name}:{len(ctx.agent.history.messages)} 条消息"
    except Exception as e:
        return f"恢复失败: {e}"


def register_builtin_commands(registry) -> None:
    registry.register(SlashCommand("help", "显示帮助", _help))
    registry.register(SlashCommand("status", "显示会话状态", _status))
    registry.register(SlashCommand("exit", "退出", _exit, aliases=("quit",)))
    registry.register(SlashCommand("clear", "清空当前会话上下文", _clear))
    registry.register(SlashCommand("model", "查看/切换模型", _model))
    registry.register(SlashCommand("tools", "列出可用工具", _tools))
    registry.register(SlashCommand("permissions", "显示权限策略", _permissions))
    registry.register(SlashCommand("memory", "查看/保存跨会话记忆", _memory))
    registry.register(SlashCommand("skills", "管理技能包", _skills))
    registry.register(SlashCommand("compact", "手动压缩上下文", _compact))
    registry.register(SlashCommand("cost", "查看 token 用量与估算费用", _cost))
    registry.register(SlashCommand("mcp", "管理 MCP servers", _mcp))
    registry.register(SlashCommand("team", "运行 Agent 团队", _team))
    registry.register(SlashCommand("worktree", "管理 Git worktree", _worktree))
    registry.register(SlashCommand("resume", "恢复 CLI 历史会话(多个会话时交互选择,list 查看列表)", _resume))
    registry.register(SlashCommand("plan", "进入计划模式(只读调研+输出计划);/plan <任务> 一条龙:计划→审批→执行", _plan))
    registry.register(SlashCommand("execute", "退出计划模式,开始执行", _execute))
