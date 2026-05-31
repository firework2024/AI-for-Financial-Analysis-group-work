from datetime import date

from finagent.chat.data_tools import (
    _build_quote_summary,
    _market_context,
    live_quote_available,
    resolve_stock_code,
)
from finagent.chat.store import ChatSession
from finagent.chat.tools import gather_tool_context


def test_resolve_stock_code_from_alias():
    session = ChatSession(id="s1", title="t", created_at="", updated_at="")
    assert resolve_stock_code("阳光电源今天股价多少", session) == "300274"


def test_build_quote_summary():
    rows = [
        {"date": "2026-05-28", "close": 100.0},
        {"date": "2026-05-29", "close": 102.5},
    ]
    quote = _build_quote_summary(rows, {"latest_close": 102.5}, "2026-05-29")
    assert quote["close"] == 102.5
    assert quote["date"] == "2026-05-29"
    assert quote["change_pct"] == 2.5


def test_market_context_weekend():
    ctx = _market_context(date(2026, 5, 31))
    assert ctx["is_weekend"] is True
    assert ctx["last_trading_date_guess"] == "2026-05-29"
    assert any("周末" in note for note in ctx["notes"])


def test_live_quote_available_with_fallback_quote():
    live = {"error": "Timeout", "quote": {"close": 88.0, "date": "2026-05-29"}}
    assert live_quote_available(live) is True


def test_gather_triggers_web_when_live_empty(monkeypatch):
    monkeypatch.setenv("FINAGENT_ENABLE_WEB_SEARCH", "true")

    def fake_fetch(_code, **_kwargs):
        return {"stock_code": "300274", "error": "NetworkError", "quote": {}}

    def fake_web(query, **kwargs):
        return {"query": query, "results": [{"title": "收盘", "snippet": "102.5元"}], "provider": "ddg"}

    monkeypatch.setattr("finagent.chat.tools.fetch_market_snapshot", fake_fetch)
    monkeypatch.setattr("finagent.chat.tools.search_web", fake_web)

    session = ChatSession(id="s1", title="t", created_at="", updated_at="", stock_code="300274")
    payload, calls = gather_tool_context("5月29日收盘价", session)
    assert payload["live_data"]["error"]
    assert payload["web_search"] is not None
    assert any(c.get("tool") == "web_search" for c in calls)
