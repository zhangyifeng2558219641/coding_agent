"""WebSearch:联网搜索工具(无 key,直接抓取 Bing 搜索结果页解析)。

- 用 requests 抓取 Bing 搜索页(中国大陆可访问,无需 API key);
- stdlib 正则 + html.unescape 解析标题/链接/摘要,不引入额外解析库;
- 超时、结果截断、错误兜底,与其余工具行为一致;
- 联网属敏感操作:默认配置为 ask(需交互确认),可在权限名单中调整。

配置(config.yaml 的 search 段):
  base_url: 可换成 https://cn.bing.com/search 等
  timeout / max_results / proxy: 见下
"""

from __future__ import annotations

import html
import re
from typing import Any

import requests

from .base import Tool, ToolContext
from ..types import ToolResult, truncate

MAX_OUTPUT = 20000
DEFAULT_BASE_URL = "https://www.bing.com/search"
DEFAULT_TIMEOUT = 15
MAX_RESULTS_CAP = 10

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 网页文本里常见的 Unicode 空白(不断空格/各类空格),统一归一化为普通空格,
# 避免进入模型上下文或 GBK 终端时带来意外。
_UNICODE_SPACES = re.compile("[  -  　]")


def _clean_fragment(frag: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", frag)).strip()


def parse_bing_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    """从 Bing 搜索结果页 HTML 中抽取 (title, url, snippet),最多 max_results 条。

    以 <li class="b_algo"> 为结果块边界(organic 结果);无嵌套 <li>,可直接按块切分。
    """
    results: list[dict[str, str]] = []
    blocks = re.split(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>', html_text)
    for block in blocks[1:]:
        end = block.find("</li>")
        if end != -1:
            block = block[:end]
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = html.unescape(m.group(1)).strip()
        title = _UNICODE_SPACES.sub(" ", _clean_fragment(m.group(2)))
        if not title:
            continue
        pm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = _UNICODE_SPACES.sub(" ", _clean_fragment(pm.group(1))) if pm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def fetch_bing(query: str, max_results: int = 5, *,
               base_url: str = DEFAULT_BASE_URL, timeout: int = DEFAULT_TIMEOUT,
               proxy: str | None = None) -> str:
    """抓取 Bing 搜索结果页,返回原始 HTML。"""
    params = {"q": query, "count": str(max_results), "setlang": "zh-CN"}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    resp = requests.get(base_url, params=params, headers=_HEADERS,
                        timeout=timeout, proxies=proxies)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


class WebSearch(Tool):
    name = "WebSearch"
    description = (
        "联网搜索网页内容(无需 API key),返回标题/链接/摘要列表。"
        "用于查询最新信息、外部资料、报错解决方案等本地看不到的内容。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词,尽量具体"},
            "max_results": {"type": "integer", "description": "返回结果条数,默认 5,最多 10"},
        },
        "required": ["query"],
    }
    category = "web"
    read_only = True

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(name=self.name, success=False, error="query 为空")

        cfg = getattr(ctx, "config", None)
        base_url = cfg.get("search", "base_url", default=DEFAULT_BASE_URL) if cfg else DEFAULT_BASE_URL
        timeout = int(cfg.get("search", "timeout", default=DEFAULT_TIMEOUT)) if cfg else DEFAULT_TIMEOUT
        proxy = cfg.get("search", "proxy", default=None) if cfg else None
        default_n = int(cfg.get("search", "max_results", default=5)) if cfg else 5
        max_results = min(int(kwargs.get("max_results") or default_n), MAX_RESULTS_CAP)

        try:
            html_text = fetch_bing(query, max_results,
                                   base_url=base_url, timeout=timeout, proxy=proxy)
        except requests.RequestException as e:
            return ToolResult(name=self.name, success=False,
                              error=f"搜索请求失败: {e}")

        results = parse_bing_results(html_text, max_results)
        if not results:
            return ToolResult(name=self.name, success=False,
                              error="未解析到任何搜索结果(Bing 页面结构可能变化,或被重定向/拦截)")

        lines = [f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                 for i, r in enumerate(results, 1)]
        output = truncate(f"搜索「{query}」结果:\n\n" + "\n\n".join(lines), MAX_OUTPUT)
        return ToolResult(name=self.name, success=True, output=output)
