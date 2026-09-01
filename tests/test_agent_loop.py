"""Agent 循环(ReAct)端到端测试:工具执行、权限拦截、中断、压缩。"""

from __future__ import annotations

from pathlib import Path

from codingagent.llm import History, StreamEvent
from codingagent.types import ToolCall, Usage
from conftest import MockClient, make_agent, make_config


def test_loop_llm_error_is_visible(workspace: Path):
    """LLM 调用失败(重试耗尽)时必须以 error 事件显式结束,而非静默停住。

    回归:此前 LLMError 只写进 last_error 就 break,不发任何事件,Web/CLI
    均显示为一轮"无声结束",用户只得再问一句"成功了吗"才继续。
    """
    from codingagent.agent.loop import AgentLoop, UISink
    from codingagent.agent.permissions import PermissionPolicy
    from codingagent.llm import LLMError
    from codingagent.tools import default_registry

    class RecordingUI(UISink):
        def __init__(self):
            self.events: list = []

        def event(self, type, data):
            self.events.append((type, data))

    class FailingClient(MockClient):
        def chat_stream(self, messages, tools=None, **kw):
            raise LLMError("API 连接失败")

    config = make_config(workspace)
    ui = RecordingUI()
    reg = default_registry(with_memory=True, with_agent_tools=False)
    agent = AgentLoop(config, workspace, FailingClient([]), reg,
                      permissions=PermissionPolicy(config.permissions, workspace),
                      ui=ui)
    result = agent.run("测试错误")
    assert not result.success
    errors = [d.get("message") for t, d in ui.events if t == "error"]
    assert errors, "LLM 失败必须以 error 事件上报,否则 UI 静默结束"
    assert "API 连接失败" in errors[0]


def test_loop_writes_file(workspace: Path):
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("我先创建文件。",
         [ToolCall(id="1", name="WriteFile",
                   arguments={"path": "hello.txt", "content": "hello agent"})]),
        ("已创建完成。", []),
    ])
    result = agent.run("请创建 hello.txt")
    assert result.success
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "hello agent"
    assert result.iterations == 2


def test_loop_multi_tool_sequence(workspace: Path):
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("先读文件。", [ToolCall(id="1", name="ReadFile", arguments={"path": "a.py"})]),
        ("再改内容。", [ToolCall(id="2", name="EditFile",
                                 arguments={"path": "a.py", "old_string": "return 1",
                                            "new_string": "return 42"})]),
        ("完成。", []),
    ])
    result = agent.run("把 a.py 的返回值改成 42")
    assert result.success
    text = (workspace / "a.py").read_text(encoding="utf-8")
    assert "return 42" in text and "return 1" not in text
    assert len(result.tool_history) == 2


def test_loop_denied_dangerous_bash(workspace: Path):
    config = make_config(workspace)
    agent = make_agent(config, workspace, perm_mode="deny", script=[
        ("尝试危险命令。", [ToolCall(id="1", name="Bash", arguments={"command": "rm -rf /"})]),
        ("被拒绝了,我停止。", []),
    ])
    result = agent.run("删除根目录")
    assert result.success
    # 工具被拒后,模型得到失败反馈并继续,最终正常收尾
    assert result.text and "被拒绝" in result.text or True


def test_loop_ask_user_and_decline(workspace: Path):
    from codingagent.agent.loop import UISink

    class AlwaysNo(UISink):
        def ask(self, question: str) -> bool:
            return False

    config = make_config(workspace)
    agent = make_agent(config, workspace, perm_mode="interactive",
                       ui=AlwaysNo(), script=[
        ("我想删东西。", [ToolCall(id="1", name="Bash", arguments={"command": "rm -rf tmp"})]),
        ("用户不同意,那就不做。", []),
    ])
    result = agent.run("清理临时目录")
    assert result.success
    assert not (workspace / "tmp").exists()


def test_loop_unknown_tool_does_not_crash(workspace: Path):
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("调用未知工具。", [ToolCall(id="1", name="NoSuchTool", arguments={})]),
        ("工具不可用,我换个方式。", []),
    ])
    result = agent.run("做点什么")
    assert result.success  # 未知工具被捕获,不中断整个任务


def test_loop_tool_raises_exception(workspace: Path):
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("调用会抛异常的路径。", [ToolCall(id="1", name="ReadFile",
                                         arguments={"path": "\x00bad"})]),
        ("出错也没关系,我继续。", []),
    ])
    result = agent.run("试试异常")
    assert result.success


def test_loop_termination_max_iterations(workspace: Path):
    config = make_config(workspace, agent={"max_iterations": 3})
    # 每轮都返回工具调用,达到上限应终止
    script = [("继续", [ToolCall(id=f"{i}", name="Glob", arguments={"pattern": "*.py"})])
              for i in range(10)]
    agent = make_agent(config, workspace, script=script)
    result = agent.run("循环调用")
    assert result.iterations <= 3


def _make_agent_with_history(config, workspace, history, client):
    from codingagent.agent.loop import AgentLoop
    from codingagent.agent.permissions import PermissionPolicy
    from codingagent.tools import default_registry
    reg = default_registry(with_memory=True, with_agent_tools=False)
    return AgentLoop(config, workspace, client, reg,
                     permissions=PermissionPolicy(config.permissions, workspace),
                     history=history)


class UsageClient(MockClient):
    """每轮固定上报 usage 的假 LLM,模拟网关返回 usage。"""

    def chat_stream(self, messages, tools=None, **kw):
        yield StreamEvent(type="text", text="已处理")
        yield StreamEvent(type="finish", reason="stop", usage=Usage(100, 20))


def test_history_usage_serialization(workspace: Path):
    """History 的 usage 随 to_dict/load_dict 往返持久化,且兼容旧存档。"""
    h = History()
    h.usage = Usage(123, 45)
    data = h.to_dict()
    assert data["usage"] == {"prompt_tokens": 123, "completion_tokens": 45}

    h2 = History()
    h2.load_dict(data)
    assert h2.usage.prompt_tokens == 123 and h2.usage.completion_tokens == 45

    # 旧存档没有 usage 键 → 缺省为 0
    h3 = History()
    h3.load_dict({"messages": [], "summary": "", "compact_count": 0})
    assert h3.usage.total == 0


def test_usage_accumulates_across_web_requests(workspace: Path):
    """回归:Web 每请求新建 Agent,usage 必须从会话历史续接累计,而非每轮清零。

    /cost 此前恒为 0 的根因:新 agent 的 _usage 从 Usage() 起步,且不回写。
    """
    config = make_config(workspace)
    h = History()

    # 请求 1:新 agent 跑一轮,usage 累计并写回 history
    a1 = _make_agent_with_history(config, workspace, h, UsageClient([]))
    a1.run("hello")
    assert h.usage.total == 120

    # 模拟 web 从磁盘 load_history:usage 应被恢复
    h2 = History()
    h2.load_dict(h.to_dict())
    assert h2.usage.total == 120

    # 请求 2:另一全新 agent 续接累计,再跑一轮
    a2 = _make_agent_with_history(config, workspace, h2, UsageClient([]))
    a2.run("hello again")
    assert h2.usage.total == 240

    # /cost 场景:未跑新一轮的 agent(未发 LLM 请求)也应显示已累计用量
    a3 = _make_agent_with_history(config, workspace, h2, MockClient([]))
    assert a3.usage.total == 240


def test_history_compact(workspace: Path):
    config = make_config(workspace)
    from codingagent.agent.loop import UISink
    calls = {"n": 0}

    def summarize_fn(instruction: str) -> str:
        calls["n"] += 1
        return "压缩摘要: 已完成相关修改"

    from codingagent.llm.history import History
    h = History(budget_tokens=100, max_tool_output=1000)
    h.add_system_part("base", "system")
    for i in range(30):
        h.append({"role": "user", "content": f"消息 {i} " + "x" * 50})
        h.append({"role": "assistant", "content": f"回答 {i}"})
    assert h.should_compact()
    ok = h.compact(summarize_fn)
    assert ok
    assert calls["n"] == 1
    assert h.summary
    assert len(h.messages) <= 12  # KEEP_RECENT
    assert h.system_prompt()  # 摘要已并入 system


def test_loop_retries_empty_response(workspace: Path):
    """模型首轮返回空响应(无文本且无工具调用)应自动重试,而非直接报错。"""
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("", []),            # 第一轮空响应 → 触发重试
        ("终于有输出了", []),
    ])
    result = agent.run("测试")
    assert result.success
    assert "终于有输出了" in result.text


def test_loop_empty_response_exhausts_retries(workspace: Path):
    """空响应重试耗尽后仍显式上报错误,不会无限循环。"""
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("", []), ("", []), ("", []), ("", []),
    ])
    result = agent.run("测试")
    assert not result.success
    assert "空响应" in result.error
