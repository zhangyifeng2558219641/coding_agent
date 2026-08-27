"""MCP(Model Context Protocol)客户端 —— 自行实现,不依赖任何 agent SDK。

以 stdio 为传输层:启动 MCP server 子进程,通过 stdin/stdout 走 JSON-RPC 2.0。
实现了握手(initialize / initialized)、tools/list、tools/call,足以把
任意符合 MCP 规范的本地工具服务(GitHub、数据库、12306 等)挂载进来。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolContext
from ..types import ToolResult

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    pass


class MCPClient:
    """单个 stdio MCP server 的客户端连接。"""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | Path | None = None,
                 name: str = "mcp"):
        self.name = name
        merged_env = dict(os.environ)
        merged_env.update({k: str(v) for k, v in (env or {}).items()})
        self._proc = subprocess.Popen(
            [command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, encoding="utf-8",
            env=merged_env, cwd=str(cwd) if cwd else None,
        )
        self._id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._closed = False
        self._stderr_lines: list[str] = []
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    # ------------------------------------------------------------------ 读写
    def _drain_stderr(self) -> None:
        try:
            for line in self._proc.stderr:
                self._stderr_lines.append(line.rstrip())
                if len(self._stderr_lines) > 200:
                    self._stderr_lines.pop(0)
        except Exception:
            pass

    def _read_loop(self) -> None:
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in msg:
                    q = self._pending.pop(msg["id"], None)
                    if q:
                        q.put(msg)
                # 服务端主动通知(如 logging)忽略
        except Exception:
            pass

    def _request(self, method: str, params: Optional[dict[str, Any]] = None,
                 timeout: float = 60) -> dict[str, Any]:
        if self._closed:
            raise MCPError(f"MCP server {self.name} 已关闭")
        self._id += 1
        rid = self._id
        q: queue.Queue = queue.Queue(maxsize=1)
        self._pending[rid] = q
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._pending.pop(rid, None)
            raise MCPError(f"写入 MCP server 失败: {e}")
        try:
            resp = q.get(timeout=timeout)
        except queue.Empty:
            self._pending.pop(rid, None)
            raise MCPError(f"MCP server {self.name} 响应超时({timeout}s)")
        if "error" in resp:
            err = resp["error"]
            raise MCPError(f"MCP 错误 {err.get('code')}: {err.get('message')}")
        return resp.get("result", {})

    # ------------------------------------------------------------------ 协议方法
    def initialize(self) -> None:
        try:
            self._request("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "codingagent", "version": "0.1"},
            })
        except MCPError:
            raise
        self._notify("notifications/initialized", {})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list")
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        is_error = bool(result.get("isError"))
        text = "\n".join(parts)
        if is_error:
            raise MCPError(text or f"MCP 工具 {tool_name} 返回错误")
        return text

    # ------------------------------------------------------------------ 资源回收
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines[-20:])


class MCPToolAdapter(Tool):
    """把远端 MCP 工具包装成本地 Tool,让 Agent 循环无感调用。"""

    def __init__(self, server_name: str, client: MCPClient, spec: dict[str, Any]):
        self._client = client
        self._server = server_name
        self.name = spec.get("name") or "mcp_tool"
        self.description = spec.get("description") or f"MCP 工具(server={server_name})"
        schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
        self.parameters = schema if "properties" in schema else {
            "type": "object", "properties": schema.get("properties", {}),
        }
        self.category = "mcp"

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        try:
            text = self._client.call_tool(self.name, kwargs)
            return ToolResult(name=self.name, success=True, output=text)
        except MCPError as e:
            return ToolResult(name=self.name, success=False, error=str(e))
        except Exception as e:
            return ToolResult(name=self.name, success=False, error=f"MCP 调用异常: {e}")


class MCPManager:
    """管理多个 MCP server 连接,并把远端工具注册进本地注册表。"""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    def connect(self, name: str, command: str, args: list[str] | None = None,
                env: dict[str, str] | None = None, cwd: str | Path | None = None,
                registry=None) -> list[str]:
        client = MCPClient(command, args, env, cwd, name=name)
        client.initialize()
        tools = client.list_tools()
        self._clients[name] = client
        if registry is not None:
            for spec in tools:
                registry.register(MCPToolAdapter(name, client, spec))
        return [t.get("name", "") for t in tools]

    def connect_from_config(self, servers_cfg: dict[str, Any], registry) -> list[str]:
        connected: list[str] = []
        for name, cfg in (servers_cfg or {}).items():
            try:
                tool_names = self.connect(
                    name, cfg.get("command", ""), cfg.get("args") or [],
                    env=cfg.get("env"), cwd=cfg.get("cwd"), registry=registry,
                )
                connected.append(f"{name}({len(tool_names)} tools)")
            except Exception as e:
                connected.append(f"{name}(连接失败: {e})")
        return connected

    def disconnect(self, name: str) -> bool:
        client = self._clients.pop(name, None)
        if client:
            client.close()
            return True
        return False

    def list_servers(self) -> list[str]:
        return list(self._clients.keys())

    def close_all(self) -> None:
        for c in self._clients.values():
            try:
                c.close()
            except Exception:
                pass
        self._clients.clear()
