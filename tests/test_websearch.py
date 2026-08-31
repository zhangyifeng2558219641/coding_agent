"""WebSearch 工具的单元测试:解析、请求失败兜底、权限默认确认。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from codingagent.agent.permissions import Decision, PermissionPolicy
from codingagent.config import Config, DEFAULT_CONFIG
from codingagent.tools import ToolContext, WebSearch
from codingagent.tools import websearch as ws

SAMPLE_HTML = """
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://example.com/page1">第一个结果</a></h2>
    <p>这是第一个结果的摘要说明文字。</p>
    <cite>https://example.com/page1</cite>
  </li>
  <li class="b_algo">
    <h2><a href="https://example.com/page2"><strong>第二个</strong>结果 &amp; 测试</a></h2>
    <p>第二个结果的摘要。</p>
  </li>
  <li class="b_algo">
    <h2><a href="https://example.com/page3">第三个结果</a></h2>
    <p>第三个结果的摘要。</p>
  </li>
</ol>
"""


def make_ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, cwd=workspace, config=None)


def test_parse_bing_results():
    results = ws.parse_bing_results(SAMPLE_HTML, max_results=2)
    assert len(results) == 2  # max_results 生效
    r0 = results[0]
    assert r0["title"] == "第一个结果"
    assert r0["url"] == "https://example.com/page1"
    assert "摘要" in r0["snippet"]
    # 标题内的 <strong> 与 &amp; 应被正确清洗
    r1 = results[1]
    assert r1["title"] == "第二个结果 & 测试"
    assert r1["snippet"] == "第二个结果的摘要。"


def test_parse_bing_results_empty():
    assert ws.parse_bing_results("<html>无结果</html>", 5) == []


def test_parse_normalizes_unicode_spaces():
    frag = "含" + " " + "窄" + "　" + "空格"
    h = ('<li class="b_algo"><h2><a href="https://e.com/x">标题</a></h2>'
         f"<p>{frag}</p></li>")
    r = ws.parse_bing_results(h, 1)
    assert r[0]["snippet"] == "含 窄 空格"


def test_websearch_success(workspace, monkeypatch):
    monkeypatch.setattr(ws, "fetch_bing", lambda *a, **k: SAMPLE_HTML)
    r = WebSearch().run(make_ctx(workspace), query="测试", max_results=2)
    assert r.success
    assert "第一个结果" in r.output
    assert "https://example.com/page1" in r.output
    assert "测试" in r.output


def test_websearch_reads_config(workspace, monkeypatch):
    seen = {}
    cfg = Config({"search": {"base_url": "https://cn.bing.com/search",
                             "timeout": 5, "max_results": 1}}, workspace)

    def fake_fetch(query, max_results, *, base_url, timeout, proxy):
        seen.update({"query": query, "max_results": max_results,
                     "base_url": base_url, "timeout": timeout})
        return SAMPLE_HTML

    monkeypatch.setattr(ws, "fetch_bing", fake_fetch)
    ctx = ToolContext(workspace=workspace, cwd=workspace, config=cfg)
    r = WebSearch().run(ctx, query="你好")
    assert r.success
    assert seen == {"query": "你好", "max_results": 1,
                    "base_url": "https://cn.bing.com/search", "timeout": 5}


def test_websearch_request_failure(workspace, monkeypatch):
    def boom(*a, **k):
        raise requests.RequestException("timeout 超时")

    monkeypatch.setattr(ws, "fetch_bing", boom)
    r = WebSearch().run(make_ctx(workspace), query="测试")
    assert not r.success
    assert "搜索请求失败" in r.error


def test_websearch_no_results(workspace, monkeypatch):
    monkeypatch.setattr(ws, "fetch_bing", lambda *a, **k: "<html>被拦截</html>")
    r = WebSearch().run(make_ctx(workspace), query="测试")
    assert not r.success
    assert "未解析到任何搜索结果" in r.error


def test_websearch_empty_query(workspace):
    r = WebSearch().run(make_ctx(workspace), query="   ")
    assert not r.success
    assert "query 为空" in r.error


def test_websearch_max_results_cap(workspace, monkeypatch):
    seen = {}

    def fake(query, max_results, *, base_url, timeout, proxy):
        seen["max_results"] = max_results
        return SAMPLE_HTML

    monkeypatch.setattr(ws, "fetch_bing", fake)
    r = WebSearch().run(make_ctx(workspace), query="测试", max_results=999)
    assert r.success
    assert seen["max_results"] == ws.MAX_RESULTS_CAP


def test_websearch_default_ask_permission(workspace):
    """默认配置下 WebSearch 应被强制确认;显式放行后才 ALLOW。"""
    cfg = Config(json.loads(json.dumps(DEFAULT_CONFIG)), workspace)
    pol = PermissionPolicy(cfg.permissions, workspace)
    assert pol.decide("WebSearch", {"query": "x"}).decision == Decision.ASK

    cfg2 = Config({"permissions": {**cfg.permissions, "ask_tools": [],
                                   "allow_tools": ["WebSearch"]}}, workspace)
    assert PermissionPolicy(cfg2.permissions, workspace).decide(
        "WebSearch", {"query": "x"}).decision == Decision.ALLOW
