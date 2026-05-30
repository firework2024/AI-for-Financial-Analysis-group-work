"""对话网页搜索：Tavily API（可选）或 DuckDuckGo HTML 回退。"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from ..env import get_env, load_dotenv

WEB_SEARCH_HINTS = (
    "新闻",
    "消息",
    "传闻",
    "舆情",
    "搜索",
    "搜一下",
    "搜一搜",
    "网上",
    "互联网",
    "网页",
    "行业动态",
    "热点",
    "政策",
    "监管",
    "处罚",
    "公告",
    "资讯",
    "报道",
    "怎么看",
    "发生了什么",
)

_USER_AGENT = "FinAgent/1.0 (+https://github.com/finagent)"


def web_search_enabled() -> bool:
    load_dotenv()
    flag = str(get_env("FINAGENT_ENABLE_WEB_SEARCH", "true") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def web_search_configured() -> bool:
    if not web_search_enabled():
        return False
    if _tavily_api_key():
        return True
    return True


def needs_web_search(query: str) -> bool:
    if not web_search_enabled():
        return False
    q = str(query or "").lower()
    return any(hint in q for hint in WEB_SEARCH_HINTS)


def search_web(query: str, *, max_results: int = 5) -> dict[str, Any]:
    """搜索网页，返回统一结构 {query, provider, results, error?}。"""
    text = str(query or "").strip()
    if not text:
        return {"query": "", "provider": None, "results": [], "error": "empty_query"}
    if not web_search_enabled():
        return {"query": text, "provider": None, "results": [], "error": "web_search_disabled"}

    limit = max(1, min(int(max_results), 8))
    api_key = _tavily_api_key()
    if api_key:
        try:
            results = _search_tavily(text, api_key, limit)
            return {"query": text, "provider": "tavily", "results": results}
        except Exception as exc:
            fallback = _search_duckduckgo(text, limit)
            if fallback:
                return {
                    "query": text,
                    "provider": "duckduckgo",
                    "results": fallback,
                    "warning": f"tavily_failed: {type(exc).__name__}",
                }
            return {"query": text, "provider": "tavily", "results": [], "error": str(exc)}

    try:
        results = _search_duckduckgo(text, limit)
        return {"query": text, "provider": "duckduckgo", "results": results}
    except Exception as exc:
        return {"query": text, "provider": "duckduckgo", "results": [], "error": str(exc)}


def _tavily_api_key() -> str | None:
    key = get_env("TAVILY_API_KEY")
    return key.strip() if key and key.strip() else None


def _search_tavily(query: str, api_key: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or "")[:600],
            }
        )
    return results[:max_results]


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": "cn-zh"},
        headers={"User-Agent": _USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    html = response.text
    blocks = re.split(r'<div class="result results_links results_links_deep web-result">', html)
    results: list[dict[str, Any]] = []
    for block in blocks[1:]:
        title_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', block, re.S)
        if not title_match:
            continue
        url = _normalize_ddg_url(title_match.group(1))
        title = _strip_html(title_match.group(2))
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet[:600]})
        if len(results) >= max_results:
            break
    return results


def _normalize_ddg_url(raw: str) -> str:
    href = unescape(str(raw or "")).strip()
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()
