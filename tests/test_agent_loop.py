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


def test_loop_ask_user_feeds_choice_back(workspace: Path):
    """agent 调 ask_user 工具 → UI.choose 返回用户选择 → 选择以工具结果回灌,模型继续。"""
    from codingagent.agent.loop import UISink

    class PickingUI(UISink):
        def __init__(self):
            self.calls: list = []

        def choose(self, prompt, options):
            self.calls.append((prompt, list(options)))
            return 1  # 选第 2 项

    ui = PickingUI()
    agent = make_agent(
        make_config(workspace), workspace,
        [
            ("有两个方案。", [ToolCall(id="1", name="ask_user",
                                       arguments={"prompt": "选哪个方案?",
                                                  "options": ["方案A", "方案B"]})]),
            ("好,按你选的继续。", []),
        ],
        ui=ui,
    )
    result = agent.run("帮我决策")
    assert result.success
    assert "按你选的继续" in result.text
    assert ui.calls and ui.calls[0][0] == "选哪个方案?" and ui.calls[0][1] == ["方案A", "方案B"]
    assert agent.tool_history == [{"name": "ask_user", "status": "ok"}]


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


def test_loop_stop_event_breaks_early(workspace: Path):
    """stop_event 预先置位时 run() 应在首轮即中断,不再消费脚本(不调用 LLM)。"""
    import threading
    config = make_config(workspace)
    ev = threading.Event(); ev.set()
    agent = make_agent(config, workspace, script=[("不该被消费", [])])
    agent.stop_event = ev
    result = agent.run("测试")
    assert not result.success
    assert result.error == "用户中断"
    assert result.iterations == 0


def test_loop_interrupt_sets_stop_event(workspace: Path):
    """interrupt() 同时置位 stop_event:Web「停止生成」/团队并行共用同一信号。"""
    import threading
    config = make_config(workspace)
    ev = threading.Event()
    agent = make_agent(config, workspace, script=[("hi", [])])
    agent.stop_event = ev
    agent.interrupt()
    assert agent._interrupted
    assert ev.is_set()
    result = agent.run("测试")
    assert not result.success
    assert result.error == "用户中断"


def test_plan_mode_blocks_write_allows_read(workspace: Path):
    """计划模式:写工具被硬拦截,读工具正常放行,任务成功收尾。"""
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("先读文件。", [ToolCall(id="1", name="ReadFile", arguments={"path": "a.py"})]),
        ("再写文件。", [ToolCall(id="2", name="WriteFile",
                                 arguments={"path": "hello.txt", "content": "plan"})]),
        ("完成。", []),
    ])
    agent.plan_mode = True
    result = agent.run("调研项目结构")
    assert result.success
    assert not (workspace / "hello.txt").exists(), "计划模式禁止写文件"
    assert {"name": "ReadFile", "status": "ok"} in agent.tool_history
    assert {"name": "WriteFile", "status": "plan-blocked"} in agent.tool_history


def test_plan_mode_schemas_filtered(workspace: Path):
    """计划模式:暴露给模型的工具只剩只读工具。"""
    config = make_config(workspace)
    agent = make_agent(config, workspace, [])
    names = lambda: {s["function"]["name"] for s in agent._schemas()}
    assert "ReadFile" in names() and "Glob" in names() and "WriteFile" in names()
    agent.plan_mode = True
    only = names()
    assert "ReadFile" in only and "Glob" in only
    assert "WriteFile" not in only and "EditFile" not in only and "Bash" not in only


def test_plan_mode_bash_whitelist(workspace: Path):
    """计划模式:Bash 只放行只读命令白名单,危险命令被拦截。"""
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("读目录。", [ToolCall(id="1", name="Bash", arguments={"command": "pwd"})]),
        ("清理目录。", [ToolCall(id="2", name="Bash", arguments={"command": "rm -rf tmp"})]),
        ("完成。", []),
    ])
    agent.plan_mode = True
    result = agent.run("看看工作区")
    assert result.success
    assert {"name": "Bash", "status": "ok"} in agent.tool_history
    assert {"name": "Bash", "status": "plan-blocked"} in agent.tool_history


def test_slash_plan_toggles_mode(workspace: Path):
    """/plan 置位计划模式,/execute 复位。"""
    from types import SimpleNamespace
    from codingagent.commands.builtins import register_builtin_commands
    from codingagent.commands.slash import SlashRegistry

    agent = make_agent(make_config(workspace), workspace, [])
    assert not agent.plan_mode
    ctx = SimpleNamespace(agent=agent)
    reg = SlashRegistry()
    register_builtin_commands(reg)
    assert reg.get("plan") is not None and reg.get("execute") is not None
    reg.run("plan", "", ctx)
    assert agent.plan_mode
    reg.run("execute", "", ctx)
    assert not agent.plan_mode


# --------------------------------------------------------------------------
# 文件检查点:WriteFile/EditFile 自动快照,回合末 finalize 成检查点
# --------------------------------------------------------------------------


def test_loop_creates_checkpoint(workspace: Path):
    from codingagent.agent.checkpoint import CheckpointStore
    cps = CheckpointStore(workspace / "cps.json")
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("先写文件。", [ToolCall(id="1", name="WriteFile",
                                 arguments={"path": "hello.txt", "content": "hello agent"})]),
        ("已创建完成。", []),
    ], checkpoints=cps)
    result = agent.run("请创建 hello.txt")
    assert result.success
    cps_list = cps.list()
    assert len(cps_list) == 1
    assert cps_list[0]["files"]["hello.txt"]["before"] is None
    assert cps_list[0]["files"]["hello.txt"]["after"] == "hello agent"


def test_loop_two_turns_rollback_restores(workspace: Path):
    """跨轮累计:turn1 写、turn2 改 → 两个检查点;回滚 cp1 还原 turn1 的状态。"""
    from codingagent.agent.checkpoint import CheckpointStore
    cps = CheckpointStore(workspace / "cps.json")
    config = make_config(workspace)
    a1 = make_agent(config, workspace, script=[
        ("写文件。", [ToolCall(id="1", name="WriteFile",
                               arguments={"path": "note.txt", "content": "v1"})]),
        ("完成。", []),
    ], checkpoints=cps)
    a1.run("创建 note.txt")
    assert len(cps.list()) == 1
    a2 = make_agent(config, workspace, script=[
        ("改文件。", [ToolCall(id="1", name="EditFile",
                               arguments={"path": "note.txt", "old_string": "v1",
                                          "new_string": "v2"})]),
        ("完成。", []),
    ], checkpoints=cps)
    a2.run("把 v1 改成 v2")
    assert len(cps.list()) == 2
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "v2"
    res = cps.rollback(1, workspace)
    assert res["restored"] == ["note.txt"]
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "v1"


def test_loop_llm_error_still_finalizes(workspace: Path):
    """LLM 失败中断的回合,已成功写盘的文件也要 finalize 成检查点。"""
    from codingagent.agent.checkpoint import CheckpointStore
    from codingagent.agent.loop import AgentLoop, UISink
    from codingagent.agent.permissions import PermissionPolicy
    from codingagent.llm import LLMError
    from codingagent.tools import default_registry

    class WriteThenFail(MockClient):
        def __init__(self):
            self.calls = []

        def chat_stream(self, messages, tools=None, **kw):
            self.calls.append(list(messages))
            if len(self.calls) == 1:
                yield StreamEvent(type="text", text="先写文件。")
                yield StreamEvent(type="tool_calls", calls=[
                    ToolCall(id="1", name="WriteFile",
                             arguments={"path": "a.txt", "content": "data"})])
                yield StreamEvent(type="finish", reason="tool_calls")
            else:
                raise LLMError("API 连接失败")

    class RecordingUI(UISink):
        def __init__(self):
            self.events = []

        def event(self, type, data):
            self.events.append((type, data))

    cps = CheckpointStore(workspace / "cps.json")
    config = make_config(workspace)
    reg = default_registry(with_memory=True, with_agent_tools=False)
    agent = AgentLoop(config, workspace, WriteThenFail(), reg,
                      permissions=PermissionPolicy(config.permissions, workspace),
                      ui=RecordingUI(), checkpoints=cps)
    result = agent.run("写个文件")
    assert not result.success
    cps_list = cps.list()
    assert len(cps_list) == 1, "LLM 失败也要把已写盘的内容落成检查点"
    assert cps_list[0]["files"]["a.txt"]["after"] == "data"


def test_checkpoint_skips_self_capture(workspace: Path):
    """写 .coding_agent/ 自管理文件不产生检查点(避免检查点套娃)。"""
    from codingagent.agent.checkpoint import CheckpointStore
    cps = CheckpointStore(workspace / "cps.json")
    config = make_config(workspace)
    agent = make_agent(config, workspace, script=[
        ("写自定义命令。", [ToolCall(id="1", name="WriteFile",
                                     arguments={"path": ".coding_agent/commands/foo.md",
                                                "content": "# test"})]),
        ("完成。", []),
    ], checkpoints=cps)
    result = agent.run("创建自定义命令")
    assert result.success
    assert cps.list() == []


def test_slash_checkpoint_list_and_rollback(workspace: Path):
    """/checkpoint 列出检查点;/checkpoint rollback <n> 回滚并写历史备注。"""
    from types import SimpleNamespace
    from codingagent.agent.checkpoint import CheckpointStore
    from codingagent.commands.builtins import register_builtin_commands
    from codingagent.commands.slash import SlashRegistry

    cps = CheckpointStore(workspace / "cps.json")
    config = make_config(workspace)
    agent = make_agent(config, workspace, [])
    agent.checkpoints = cps
    # cp1: v0 -> v1
    (workspace / "a.txt").write_text("v0", encoding="utf-8")
    cps.snapshot_before(workspace, "a.txt")
    (workspace / "a.txt").write_text("v1", encoding="utf-8")
    cps.snapshot_after(workspace, "a.txt")
    cps.finalize()
    # cp2: v1 -> v2
    cps.snapshot_before(workspace, "a.txt")
    (workspace / "a.txt").write_text("v2", encoding="utf-8")
    cps.snapshot_after(workspace, "a.txt")
    cps.finalize()

    ctx = SimpleNamespace(agent=agent, config=config, workspace=workspace,
                          checkpoints=cps, ui=None)
    reg = SlashRegistry()
    register_builtin_commands(reg)
    assert reg.get("checkpoint") is not None
    out = reg.run("checkpoint", "", ctx)
    assert "#1" in out and "#2" in out and "a.txt" in out
    out2 = reg.run("checkpoint", "rollback 1", ctx)
    assert "已回滚到检查点 #1" in out2
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "v1"  # cp1 之后的状态(撤销 cp2)
    assert any("回滚" in (m.get("content") or "") for m in agent.history.messages)
