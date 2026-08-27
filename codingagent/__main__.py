"""命令行入口。

用法:
  python -m codingagent                  交互式终端(REPL)
  python -m codingagent run "任务描述"    一次性执行,输出最终结果
  python -m codingagent web [--port 8787] 启动网页端
  python -m codingagent doctor           环境自检
"""

from __future__ import annotations

import argparse
import sys


def _build_config(args) -> None:
    from .config import load_config

    overrides = {}
    if getattr(args, "model", None):
        overrides["provider"] = {"model": args.model}
    return load_config(workspace=getattr(args, "workspace", None),
                       config_files=getattr(args, "config", None),
                       cli_overrides=overrides or None)


def _cmd_interactive(args) -> int:
    from .session import Session
    from .ui.cli import CLIUI, run_cli

    config = _build_config(args)
    session = Session(config, ui=CLIUI())
    run_cli(session)
    return 0


def _cmd_run(args) -> int:
    from .session import Session
    from .ui.cli import CLIUI, run_once

    config = _build_config(args)
    session = Session(config, ui=CLIUI())
    return run_once(session, " ".join(args.task))


def _cmd_web(args) -> int:
    import uvicorn

    from .session import Session
    from .ui.web import create_app

    config = _build_config(args)
    session = Session(config)
    app = create_app(session)
    print(f"coding_agent web 已启动: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_doctor(args) -> int:
    from .session import Session
    from .config import load_config

    print("== coding_agent 环境自检 ==")
    config = _build_config(args)
    print(f"[OK] 工作区: {config.workspace}")
    print(f"[OK] 模型: {config.provider.get('model')} @ {config.provider.get('base_url')}")
    key = config.api_key()
    print(f"[{'OK' if key else 'WARN'}] API key: {'已配置(环境变量)' if key else '未配置 —— 请在 .env 或环境变量设置'}")

    try:
        session = Session(config)
        print(f"[OK] 工具: {len(session.registry.names())} 个 -> {', '.join(sorted(session.registry.names()))}")
        print(f"[OK] 技能: {len(session.skills.list())} 个")
        print(f"[OK] 内置斜杠命令: {len(session.slash.list())} 个")
        print(f"[OK] 权限模式: {config.permissions.get('mode')}")
        connected = session.connect_mcp_from_config()
        if connected:
            print(f"[OK] MCP 连接: {', '.join(connected)}")
        session.close()
    except Exception as e:
        print(f"[ERROR] 会话初始化失败: {e}")
        return 1
    print("== 自检完成 ==")
    return 0


def _ensure_stdout_utf8() -> None:
    """Windows 控制台默认 GBK,统一改为 UTF-8,避免中文/emoji 乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_stdout_utf8()
    parser = argparse.ArgumentParser(
        prog="codingagent",
        description="自研编程智能体(类 Claude Code):自主读写文件、执行命令完成编程任务。",
    )
    parser.add_argument("--workspace", "-w", default=None, help="工作区根目录(默认自动检测 .git)")
    parser.add_argument("--config", "-c", action="append", default=None, help="额外的配置文件(yaml)")
    parser.add_argument("--model", "-m", default=None, help="覆盖模型名")

    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="一次性执行任务")
    p_run.add_argument("task", nargs="*", help="任务描述")

    p_web = sub.add_parser("web", help="启动网页端")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8787)

    sub.add_parser("doctor", help="环境自检")

    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "web":
        return _cmd_web(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    return _cmd_interactive(args)


if __name__ == "__main__":
    sys.exit(main())
