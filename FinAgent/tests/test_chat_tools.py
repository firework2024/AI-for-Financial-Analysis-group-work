from finagent.chat.store import ChatSession
from finagent.chat.tools import gather_tool_context
from finagent.chat.web_search import _strip_html, needs_web_search, search_web


def test_needs_web_search():
    assert needs_web_search("最近有什么行业新闻")
    assert needs_web_search("搜一下监管政策")
    assert not needs_web_search("PE是多少")


def test_gather_tool_context_without_stock(monkeypatch):
    monkeypatch.setenv("FINAGENT_ENABLE_WEB_SEARCH", "true")
    session = ChatSession(id="s1", title="t", created_at="", updated_at="")
    payload, calls = gather_tool_context("最近新能源行业新闻", session)
    assert payload["web_search"] is not None
    assert any(item.get("tool") == "web_search" for item in calls)


def test_strip_html():
    assert _strip_html("<b>hello</b> world") == "hello world"


def test_search_web_disabled(monkeypatch):
    monkeypatch.setenv("FINAGENT_ENABLE_WEB_SEARCH", "false")
    result = search_web("测试")
    assert result.get("error") == "web_search_disabled"
