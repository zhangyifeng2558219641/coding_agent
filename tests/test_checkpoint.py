"""检查点(CheckpointStore)单元测试:捕获、持久化、回滚语义与路径安全。"""

from __future__ import annotations

from codingagent.agent.checkpoint import CheckpointStore


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def test_checkpoint_record_and_finalize(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    # 创建文件(before=None)
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("hello", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    cp = store.finalize()
    assert cp is not None and cp["seq"] == 1
    assert cp["files"]["a.txt"]["before"] is None
    assert cp["files"]["a.txt"]["after"] == "hello"
    # 覆盖已有文件(before 非 None)
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("world", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    cp2 = store.finalize()
    assert cp2 is not None and cp2["seq"] == 2
    assert cp2["files"]["a.txt"]["before"] == "hello"
    assert cp2["files"]["a.txt"]["after"] == "world"


def test_checkpoint_seq_and_persist_roundtrip(tmp_path):
    ws = _ws(tmp_path)
    path = tmp_path / "cp.json"
    store = CheckpointStore(path)
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()
    # 从磁盘重新加载,检查点仍在且内容正确
    store2 = CheckpointStore(path)
    cps = store2.list()
    assert len(cps) == 1 and cps[0]["seq"] == 1
    assert cps[0]["files"]["a.txt"]["before"] == "v1"
    assert cps[0]["files"]["a.txt"]["after"] == "v2"


def test_checkpoint_same_file_one_entry(tmp_path):
    """同一回合多次写同一文件 → 只一条记录:首个 before + 最后 after。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "a.txt").write_text("start", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("mid", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    (ws / "a.txt").write_text("end", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    cp = store.finalize()
    assert cp is not None
    files = cp["files"]
    assert set(files) == {"a.txt"}
    assert files["a.txt"]["before"] == "start"
    assert files["a.txt"]["after"] == "end"


def test_checkpoint_discard(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    store.snapshot_before(ws, "a.txt")
    store.discard("a.txt")
    assert store.finalize() is None
    assert store.list() == []


def test_checkpoint_filters_noop_and_failed(tmp_path):
    """内容未变(写失败后重读)与 after 缺失(写被打断)都不构成检查点。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "a.txt").write_text("same", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    store.snapshot_after(ws, "a.txt")  # after == before
    store.snapshot_before(ws, "b.txt")  # after 未设置
    assert store.finalize() is None


def test_checkpoint_begin_turn_clears_pending(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    store.snapshot_before(ws, "a.txt")
    store.begin_turn()
    assert store.finalize() is None


def test_checkpoint_rollback_restores_last_after(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "a.txt").write_text("v0", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp1: v0 -> v1
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp2: v1 -> v2
    res = store.rollback(1, ws)
    assert res["restored"] == ["a.txt"]
    assert res["deleted"] == [] and res["left_unchanged"] == [] and res["errors"] == []
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v1"


def test_checkpoint_rollback_deletes_created_after(tmp_path):
    """回滚到更早检查点:之后才被 agent 创建的文件应删除。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "a.txt").write_text("keep", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("keep2", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp1
    store.snapshot_before(ws, "b.txt")  # 创建,before=None
    (ws / "b.txt").write_text("new", encoding="utf-8")
    store.snapshot_after(ws, "b.txt")
    store.finalize()  # cp2
    res = store.rollback(1, ws)
    assert "b.txt" in res["deleted"]
    assert not (ws / "b.txt").exists()
    assert (ws / "a.txt").read_text(encoding="utf-8") == "keep2"


def test_checkpoint_rollback_preserves_pre_existing(tmp_path):
    """关键边界:N 之后才首次被改、但文件本就存在 → 保留不删,计入 left_unchanged。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "orig.txt").write_text("original", encoding="utf-8")
    (ws / "a.txt").write_text("v0", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp1
    store.snapshot_before(ws, "orig.txt")  # 已存在文件首次被改
    (ws / "orig.txt").write_text("modified", encoding="utf-8")
    store.snapshot_after(ws, "orig.txt")
    store.snapshot_before(ws, "b.txt")  # agent 创建
    (ws / "b.txt").write_text("new", encoding="utf-8")
    store.snapshot_after(ws, "b.txt")
    store.finalize()  # cp2
    res = store.rollback(1, ws)
    assert "orig.txt" in res["left_unchanged"], "既存文件不可重建,必须保留"
    assert "b.txt" in res["deleted"]
    assert "a.txt" in res["restored"]
    assert (ws / "orig.txt").read_text(encoding="utf-8") == "modified"


def test_checkpoint_rollback_recreates_missing_file(tmp_path):
    """回滚到更早检查点:期间被删的文件应以其 after 重建。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp1: v2
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("v3", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()  # cp2: v3
    (ws / "a.txt").unlink()
    res = store.rollback(1, ws)
    assert "a.txt" in res["restored"]
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v2"


def test_checkpoint_rollback_bad_seq(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    assert "error" in store.rollback(1, ws)  # 空
    store.snapshot_before(ws, "a.txt")
    (ws / "a.txt").write_text("x", encoding="utf-8")
    store.snapshot_after(ws, "a.txt")
    store.finalize()
    assert "error" in store.rollback(0, ws)
    assert "error" in store.rollback(2, ws)


def test_checkpoint_safe_join_rejects_escape(tmp_path):
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    assert store.safe_join(ws, "../evil.txt") is None      # 越出工作区
    assert store.safe_join(ws, "C:/abs/path.txt") is None  # 绝对路径
    assert store.safe_join(ws, "/abs/path.txt") is None    # 绝对路径
    assert store.safe_join(ws, "sub/ok.txt") == (ws / "sub/ok.txt").resolve()


def test_checkpoint_rollback_ignores_escape_paths(tmp_path):
    """防御:即使检查点数据被污染成逃逸路径,回滚也不会写出工作区。"""
    ws = _ws(tmp_path)
    store = CheckpointStore(tmp_path / "cp.json")
    store._checkpoints = [{"seq": 1, "ts": "t", "files": {
        "../evil.txt": {"before": None, "after": "x"},
        "ok.txt": {"before": None, "after": "fine"},
    }}]
    res = store.rollback(1, ws)
    assert "../evil.txt" in res["errors"]
    assert "ok.txt" in res["restored"]
    assert (ws / "ok.txt").read_text(encoding="utf-8") == "fine"
    assert not (tmp_path / "evil.txt").exists()
