"""配置系统:默认值 + YAML 覆盖 + .env 环境变量,逐层合并。

关键原则:
- API key 等敏感项一律不写在代码/仓库里,运行时通过环境变量读取。
- 配置优先级(低 → 高):
    默认值 < config.yaml < ~/.coding_agent/config.yaml < .coding_agent/config.yaml
    < .env 文件 < 进程环境变量 < 命令行参数
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": {
        # DeepSeek 为默认厂商;任意 OpenAI 兼容网关都可通过 base_url 切换
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "max_tokens": 8192,
        # 请求时附带 stream_options.include_usage;若网关报 400 会自动回退去掉
        "include_usage": True,
        # 网络参数
        "timeout": 120,
        "max_retries": 3,
        "retry_backoff": 2.0,
    },
    "context": {
        "budget_tokens": 64000,      # 上下文预算,超过即触发压缩
        "compact_ratio": 0.5,        # 压缩后保留的预算比例
        "max_tool_output": 30000,    # 单条工具结果截断上限(字符)
        "summary_model": None,       # 压缩用的模型;默认沿用主模型
    },
    "agent": {
        "max_iterations": 30,        # 单任务最大工具迭代轮数(循环终止条件之一)
        "system_prompt": "",
    },
    "permissions": {
        # interactive:逐次确认 | auto-approve:白名单外自动放行 | deny:白名单外拒绝
        "mode": "interactive",
        "sandbox": True,             # 工作区沙箱:文件/命令默认限制在工作区根目录内
        "allow_tools": [],           # 直接放行的工具名
        "deny_tools": [],            # 直接拒绝的工具名
        "ask_tools": [],             # 强制确认的工具名
        "allow_commands": [],        # 正则:自动放行的 shell 命令
        "dangerous_commands": [      # 正则:危险命令,默认需要确认
            r"rm\s+-rf",
            r"git\s+push\s+--force",
            r"git\s+reset\s+--hard",
            r"git\s+clean\s+-f",
            r"(^|[;&|])\s*(mkfs|dd\s+if=)",
            r"(^|[;&|])\s*shutdown|reboot",
            r"(^|[;&|])\s*format\s+[a-z]:",
        ],
        "sensitive_paths": [         # 子串/路径模式:匹配即拒绝访问
            ".git",
            "node_modules",
        ],
        "sensitive_file_names": [    # 文件名命中即拒绝(密钥类)
            ".env",
            "*.pem",
            "*.key",
            "id_rsa",
            "id_dsa",
            "id_ed25519",
            "*.jks",
            "*.p12",
            "credentials",
            "secret",
        ],
    },
    "memory": {
        "enabled": True,
        "project_file": ".coding_agent/memory/project.md",
        "user_file": "~/.coding_agent/memory/user.md",
    },
    "skills": {
        "dirs": [
            "skills",
            ".coding_agent/skills",
            "~/.coding_agent/skills",
        ],
    },
    "commands": {
        "dir": ".coding_agent/commands",
    },
    "mcp": {
        "servers": {},   # 名称 -> {"command": str, "args": [..], "env": {..}}
    },
    "hooks": {},         # 事件名 -> [ {command: str} 或 {callable: "模块.函数"} ]
    "teams": {},         # 团队名 -> {members: [..]}
    "sessions_dir": ".coding_agent/sessions",
    "log_level": "INFO",
}

SECRET_ENV_KEYS = {
    # 各厂商 API key 的环境变量名(运行时读取,仓库内不出现)
    "provider": ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY",
                 "DASHSCOPE_API_KEY", "ZHIPUAI_API_KEY", "ANTHROPIC_API_KEY"],
}


# ---------------------------------------------------------------------------
# 极简 .env 解析(零依赖)
# ---------------------------------------------------------------------------

def load_env_file(path: str | Path) -> dict[str, str]:
    """解析 .env 文件:每行 KEY=VALUE,支持 # 注释、双引号/单引号包裹。"""
    out: dict[str, str] = {}
    p = Path(path).expanduser()
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and val:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict,override 优先。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def find_workspace_root(cwd: str | Path | None = None) -> Path:
    """定位工作区根目录:优先找最近的 .git,否则用当前目录。"""
    cwd = Path(cwd or os.getcwd()).resolve()
    for d in [cwd, *cwd.parents]:
        if (d / ".git").exists():
            return d
    return cwd


class Config:
    """合并后的运行时配置;所有敏感项通过 get_secret() 惰性读取。"""

    def __init__(self, data: dict[str, Any], workspace: Path):
        self.data = data
        self.workspace = workspace.resolve()

    # -- 取值 -----------------------------------------------------------------
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def provider(self) -> dict[str, Any]:
        return self.get("provider", default={})

    @property
    def permissions(self) -> dict[str, Any]:
        return self.get("permissions", default={})

    @property
    def agent(self) -> dict[str, Any]:
        return self.get("agent", default={})

    @property
    def context(self) -> dict[str, Any]:
        return self.get("context", default={})

    # -- 敏感项 ---------------------------------------------------------------
    def get_secret(self, key: str, env_names: list[str] | None = None) -> Optional[str]:
        """先查环境变量,再查 .env 中已加载的变量;代码内不保存任何真实 key。"""
        names = env_names or SECRET_ENV_KEYS.get(key, [])
        for n in names:
            v = os.environ.get(n)
            if v:
                return v
        return None

    def api_key(self) -> Optional[str]:
        return self.get_secret("provider") or None

    # -- 路径解析 ---------------------------------------------------------------
    def resolve_path(self, p: str | Path) -> Path:
        """把配置里的路径(可含 ~)解析为相对工作区的绝对路径。"""
        path = Path(str(p)).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def session_store_path(self) -> Path:
        # 注意:Config.get 是 *keys,默认值必须用关键字 default=
        return self.resolve_path(self.get("sessions_dir", default=".coding_agent/sessions"))

    def public_dict(self) -> dict[str, Any]:
        """非敏感配置(供 Web /api/config 返回,绝不包含 key)。"""
        data = json.loads(json.dumps(self.data, ensure_ascii=False))
        data["provider"] = {
            "base_url": self.provider.get("base_url"),
            "model": self.provider.get("model"),
            "temperature": self.provider.get("temperature"),
        }
        data["has_api_key"] = bool(self.api_key())
        data["workspace"] = str(self.workspace)
        return data


def load_config(
    workspace: str | Path | None = None,
    config_files: list[str | Path] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> Config:
    """按优先级逐层合并配置并返回 Config 实例。"""
    ws = find_workspace_root(workspace)
    data: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝

    # 候选配置文件:项目根 config.yaml,再用户级、项目内局部覆盖
    candidates = [
        Path(ws) / "config.yaml",
        Path("~/.coding_agent/config.yaml").expanduser(),
        Path(ws) / ".coding_agent" / "config.yaml",
    ]
    if config_files:
        candidates = [Path(c).expanduser() for c in config_files]

    for cf in candidates:
        if cf and cf.is_file():
            try:
                with open(cf, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                _deep_merge(data, loaded)
            except Exception as e:  # pragma: no cover
                print(f"[warning] 配置加载失败 {cf}: {e}")

    # .env 文件(工作区根 + 用户主目录),解析后写入 os.environ,便于 get_secret
    for env_file in [Path(ws) / ".env", Path("~/.coding_agent/.env").expanduser()]:
        for k, v in load_env_file(env_file).items():
            os.environ.setdefault(k, v)

    if cli_overrides:
        _deep_merge(data, cli_overrides)

    return Config(data, ws)
