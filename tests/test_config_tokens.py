"""配置加载 / .env 解析 / token 估算的单元测试。"""

from __future__ import annotations

from pathlib import Path

from codingagent.config import Config, load_config, load_env_file
from codingagent.llm.tokens import estimate_messages_tokens, estimate_tokens
from codingagent.prompts import base_system_prompt


def test_estimate_tokens_basic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") >= 4          # 中文按字符
    assert estimate_tokens("a" * 4000) <= 1100       # ASCII 按 1/4
    assert estimate_tokens("short") > 0


def test_estimate_messages():
    msgs = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "hi"}]
    assert estimate_messages_tokens(msgs) > 0


def test_env_parser(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# 注释\nDEEPSEEK_API_KEY=sk-abc123\n\nEMPTY=\nQUOTED=\"a b c\"\nSINGLE='x y'\n",
        encoding="utf-8",
    )
    data = load_env_file(env)
    assert data["DEEPSEEK_API_KEY"] == "sk-abc123"
    assert data["QUOTED"] == "a b c"
    assert data["SINGLE"] == "x y"
    assert "EMPTY" not in data  # 空值不入
    assert load_env_file(tmp_path / "not-exist") == {}


def test_config_merge(tmp_path: Path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "provider:\n  model: custom-model\ncontext:\n  budget_tokens: 123\n", encoding="utf-8")
    cfg = load_config(workspace=tmp_path, config_files=[tmp_path / "config.yaml"])
    assert cfg.provider["model"] == "custom-model"
    assert cfg.context["budget_tokens"] == 123
    # 未覆盖的仍保留默认
    assert cfg.provider["base_url"] == "https://api.deepseek.com"
    assert cfg.permissions["mode"] == "interactive"


def test_config_secret(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    cfg = load_config(workspace=Path.cwd())
    assert cfg.api_key() == "sk-test-123"
    cfg2 = load_config(workspace=Path.cwd())
    assert cfg2.api_key() == "sk-test-123"


def test_public_dict_no_secret():
    cfg = Config({"provider": {"model": "m", "base_url": "u"}, "nested": {"k": 1}},
                 Path.cwd())
    d = cfg.public_dict()
    assert "model" in str(d)
    assert "api_key" not in str(d).lower() or d.get("has_api_key") is not None


def test_base_prompt_contains_workspace(workspace):
    text = base_system_prompt(workspace)
    assert str(workspace) in text
    assert "编程智能体" in text
