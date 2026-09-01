"""Agent 团队(Team)编排测试:成员并行执行 + 负责人汇总的容错。"""

from __future__ import annotations

from pathlib import Path

from codingagent.agent.permissions import PermissionPolicy
from codingagent.agent.teams import Team, TeamMember
from codingagent.llm import ChatResponse, LLMError
from codingagent.tools import default_registry
from codingagent.types import Usage
from conftest import MockClient, make_config


class EmptyLeaderClient(MockClient):
    """负责人非流式 chat() 始终返回空 content;成员流式 chat_stream() 走脚本。"""

    def chat(self, messages, **kw):
        return ChatResponse(content="", tool_calls=[], usage=Usage(1, 1))


def _team(config, workspace, client, members):
    reg = default_registry(with_memory=True, with_agent_tools=False)
    return Team("test-team", members, config, workspace, client, reg,
                permissions=PermissionPolicy(config.permissions, workspace))


def test_team_leader_empty_falls_back_to_digest(workspace: Path):
    """负责人汇总返回空响应时,重试后仍失败则兜底展示成员产出原文,而非只报一句错。"""
    config = make_config(workspace)
    client = EmptyLeaderClient([("成员产出一", [])])
    team = _team(config, workspace, client,
                 [TeamMember(name="分析员", role="分析")])
    r = team.run("测试任务")
    assert not r.success
    assert "负责人汇总失败" in r.error
    assert "原始任务" in r.final_text      # 兜底成员摘要
    assert "分析员" in r.final_text
    assert "成员产出一" in r.final_text
    assert r.saved_to == ""                # 汇总失败不写交付文件
    assert not (workspace / "test-team_汇总.md").exists()


def test_team_leader_retries_then_succeeds(workspace: Path):
    """负责人第一次空响应、第二次给出内容时,应重试并采用有效结果,并写入汇总文档。"""
    config = make_config(workspace)
    client = EmptyLeaderClient([("成员产出一", [])])
    attempts = {"n": 0}

    class FlakyLeader(EmptyLeaderClient):
        def chat(self, messages, **kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return ChatResponse(content="", tool_calls=[], usage=Usage(1, 1))
            return ChatResponse(content="最终汇总成果", tool_calls=[], usage=Usage(2, 2))

    team = _team(config, workspace, FlakyLeader([("成员产出一", [])]),
                 [TeamMember(name="分析员", role="分析")])
    r = team.run("测试任务")
    assert r.success
    assert "最终汇总成果" in r.final_text
    assert attempts["n"] == 2
    out = workspace / "test-team_汇总.md"
    assert r.saved_to == str(out)
    assert "最终汇总成果" in out.read_text(encoding="utf-8")


def test_team_leader_error_falls_back(workspace: Path):
    """负责人汇总抛异常时也走兜底。"""
    config = make_config(workspace)
    client = EmptyLeaderClient([("成员产出一", [])])

    class ErrorLeader(EmptyLeaderClient):
        def chat(self, messages, **kw):
            raise LLMError("API 连接失败")

    team = _team(config, workspace, ErrorLeader([("成员产出一", [])]),
                 [TeamMember(name="分析员", role="分析")])
    r = team.run("测试任务")
    assert not r.success
    assert "API 连接失败" in r.error
    assert "成员产出一" in r.final_text
    assert r.saved_to == ""
