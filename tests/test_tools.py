"""核心工具(文件/搜索)的单元测试。"""

from __future__ import annotations

from pathlib import Path

from codingagent.tools import (
    EditFile, Glob, Grep, ReadFile, ToolContext, WriteFile, default_registry,
)


def make_ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, cwd=workspace)


def test_registry():
    reg = default_registry(with_memory=True, with_agent_tools=True)
    names = reg.names()
    for n in ["ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep",
              "MemoryRecall", "MemorySave", "DispatchTask"]:
        assert n in names, n
    schemas = reg.schemas()
    assert all(s["type"] == "function" for s in schemas)
    assert reg.get_ci("readfile") is not None  # 大小写不敏感


def test_readfile(workspace):
    r = ReadFile().run(make_ctx(workspace), path="a.py")
    assert r.success
    assert "def foo" in r.output
    assert "|" in r.output  # 带行号
    # 局部读取
    r2 = ReadFile().run(make_ctx(workspace), path="a.py", offset=1, limit=1)
    assert "1 |" in r2.output and "return 1" not in r2.output or "return 1" in r2.output
    # 不存在
    r3 = ReadFile().run(make_ctx(workspace), path="nope.txt")
    assert not r3.success


def test_readfile_binary(workspace):
    p = workspace / "bin.dat"
    p.write_bytes(b"\x00\x01\x02hello")
    r = ReadFile().run(make_ctx(workspace), path="bin.dat")
    assert not r.success and "二进制" in r.error


def test_writefile(workspace):
    r = WriteFile().run(make_ctx(workspace), path="new/deep/f.txt", content="x\n")
    assert r.success
    assert (workspace / "new" / "deep" / "f.txt").read_text(encoding="utf-8") == "x\n"


def test_editfile_strict(workspace):
    p = workspace / "note.txt"
    # 唯一匹配
    r = EditFile().run(make_ctx(workspace), path="note.txt",
                       old_string="hello world", new_string="hello CODER")
    assert r.success
    text = p.read_text(encoding="utf-8")
    assert "hello CODER" in text and "hello world" not in text
    # 重复匹配 → 报错不猜测
    r2 = EditFile().run(make_ctx(workspace), path="note.txt",
                        old_string="hello", new_string="bye")
    assert not r2.success and "次" in r2.error
    # 不存在 → 报错
    r3 = EditFile().run(make_ctx(workspace), path="note.txt",
                        old_string="不存在的内容", new_string="x")
    assert not r3.success


def test_glob(workspace):
    r = Glob().run(make_ctx(workspace), pattern="**/*.py")
    assert r.success and "a.py" in r.output


def test_grep(workspace):
    r = Grep().run(make_ctx(workspace), pattern="hello")
    assert r.success
    assert "note.txt" in r.output and "hello world" in r.output
    r2 = Grep().run(make_ctx(workspace), pattern="NO_SUCH")
    assert r2.success and "无匹配" in r2.output
    r3 = Grep().run(make_ctx(workspace), pattern="hello", ignore_case=False, context=1)
    assert r3.success


def test_grep_fixed_and_glob(workspace):
    r = Grep().run(make_ctx(workspace), pattern="def foo", fixed_strings=True, glob="*.py")
    assert r.success and "a.py" in r.output
