"""5 层权限防御的决策矩阵测试。"""

from __future__ import annotations

from pathlib import Path

from codingagent.agent.permissions import Decision, PermissionPolicy


def policy(tmp: Path, mode="interactive", **kw):
    cfg = {"mode": mode, "sandbox": True, "allow_tools": [], "deny_tools": [],
           "ask_tools": [], "allow_commands": [], "dangerous_commands":
           [r"rm\s+-rf"], "sensitive_paths": [".git"], "sensitive_file_names": [".env"]}
    cfg.update(kw)
    return PermissionPolicy(cfg, tmp)


def test_layer1_tool_rules(tmp_path: Path):
    p = policy(tmp_path, allow_tools=["Bash"], deny_tools=["EditFile"], ask_tools=["Glob"])
    assert p.decide("Bash", {"command": "anything"}).decision == Decision.ALLOW
    assert p.decide("EditFile", {"path": "x"}).decision == Decision.DENY
    assert p.decide("Glob", {"pattern": "*"}).decision == Decision.ASK


def test_layer2_sensitive_path(tmp_path: Path):
    p = policy(tmp_path)
    assert p.decide("ReadFile", {"path": str(tmp_path / ".git" / "config")}).decision == Decision.DENY
    assert p.decide("ReadFile", {"path": str(tmp_path / ".env")}).decision == Decision.DENY


def test_layer3_sandbox(tmp_path: Path):
    outside = tmp_path.parent / "other" / "x.txt"
    # interactive:越界 → ASK
    assert policy(tmp_path, "interactive").decide("ReadFile", {"path": str(outside)}).decision == Decision.ASK
    # deny:越界 → DENY
    assert policy(tmp_path, "deny").decide("ReadFile", {"path": str(outside)}).decision == Decision.DENY
    # auto-approve:越界 → ALLOW
    assert policy(tmp_path, "auto-approve").decide("ReadFile", {"path": str(outside)}).decision == Decision.ALLOW
    # 工作区内相对路径不触发
    assert policy(tmp_path).decide("ReadFile", {"path": "a.py"}).decision in (Decision.ALLOW, Decision.ASK)


def test_layer4_dangerous_command(tmp_path: Path):
    p = policy(tmp_path, "interactive")
    assert p.decide("Bash", {"command": "rm -rf /"}).decision == Decision.ASK
    assert policy(tmp_path, "deny").decide("Bash", {"command": "rm -rf /"}).decision == Decision.DENY
    # 非危险命令在 interactive 下也是 ASK(未知操作确认)
    assert p.decide("Bash", {"command": "ls -la"}).decision == Decision.ASK


def test_layer5_allow_command_and_fallback(tmp_path: Path):
    p = policy(tmp_path, "interactive", allow_commands=[r"^git\s+status"])
    assert p.decide("Bash", {"command": "git status"}).decision == Decision.ALLOW
    # auto-approve 兜底放行,deny 兜底拒绝
    assert policy(tmp_path, "auto-approve").decide("Grep", {"pattern": "x"}).decision == Decision.ALLOW
    assert policy(tmp_path, "deny").decide("Grep", {"pattern": "x"}).decision == Decision.DENY
