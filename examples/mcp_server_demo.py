"""一个最小但完整的 MCP server 演示 —— 用 stdio + JSON-RPC 2.0 自行实现。

运行:coding_agent 的 config.yaml 里 mcp.servers 配置好它后自动连接;
或手动测试: python examples/mcp_server_demo.py
提供两个演示工具:demo_echo / demo_add。
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "demo_echo",
        "description": "原样返回输入的文本,演示 MCP 工具调用",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
    },
    {
        "name": "demo_add",
        "description": "计算两个整数之和,演示参数传递",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    },
]


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo-server", "version": "1.0.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "demo_echo":
            return {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]}
        if name == "demo_add":
            try:
                total = int(args.get("a", 0)) + int(args.get("b", 0))
            except (TypeError, ValueError):
                return {"content": [{"type": "text", "text": "参数需为整数"}], "isError": True}
            return {"content": [{"type": "text", "text": f"{args.get('a')} + {args.get('b')} = {total}"}]}
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}], "isError": True}
    return {"content": [{"type": "text", "text": f"未实现方法: {method}"}], "isError": True}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "method" not in msg:  # 忽略响应/通知
            continue
        result = handle(msg["method"], msg.get("params") or {})
        if "id" in msg:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
