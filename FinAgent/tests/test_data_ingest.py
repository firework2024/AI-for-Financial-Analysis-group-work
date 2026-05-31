import pytest

from finagent.chat.data_ingest import (
    annual_report_needs_update,
    bootstrap_stock_data,
    ensure_stored_data,
    get_data_gaps,
    ingest_market_snapshot,
    target_annual_report_year,
)
from finagent.chat.store import ChatSession
from finagent.chat.tools import gather_tool_context


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("FINAGENT_DB_PATH", str(db_path))
    from finagent.datastore import init_db

    init_db(db_path)
    return db_path


def test_get_data_gaps_market_only(temp_db):
    gaps = get_data_gaps("300750", "宁德时代最新股价多少")
    assert "market_snapshot" in gaps
    assert "annual_report" not in gaps


def test_get_data_gaps_annual(temp_db):
    gaps = get_data_gaps("300750", "2024年年报营收和净利润")
    assert "annual_report" in gaps


def test_get_data_gaps_empty_when_no_need(temp_db):
    gaps = get_data_gaps("300750", "这份报告的核心风险是什么")
    assert gaps == []


def test_ensure_stored_data_market(monkeypatch, temp_db):
    calls: list[str] = []

    def fake_ingest(code, **kwargs):
        calls.append(code)
        return {"ok": True, "snapshot_id": 1, "source": "rqdata", "end_date": "2026-05-29", "live": {"quote": {"close": 200}}}

    monkeypatch.setattr("finagent.chat.data_ingest.ingest_market_snapshot", fake_ingest)
    monkeypatch.setattr("finagent.chat.data_ingest.get_data_gaps", lambda _c, _q: ["market_snapshot"])

    result = ensure_stored_data("300750", "查一下最新股价")
    assert result is not None
    assert result["ok"] is True
    assert calls == ["300750"]


def test_gather_triggers_ensure_before_data_api(monkeypatch, temp_db):
    order: list[str] = []

    def fake_ensure(code, query, **kwargs):
        order.append("ensure")
        return {"ok": True, "requested_gaps": ["market_snapshot"], "actions": [{"gap": "market_snapshot", "ok": True, "live": {"quote": {"close": 88.0, "date": "2026-05-29"}}}]}

    def fake_query_api(code, query, **kwargs):
        order.append("query_api")
        return {"stock_code": code, "stored": {"matched_keys": ["price"], "series": {"price": {"rows": [{"close": 88}]}}}}

    def fake_supplement(live, stock, query):
        return live

    monkeypatch.setattr("finagent.chat.tools.ensure_stored_data", fake_ensure)
    monkeypatch.setattr("finagent.chat.tools.query_data_api", fake_query_api)
    monkeypatch.setattr("finagent.chat.tools.supplement_live_with_web_quote", fake_supplement)

    session = ChatSession(id="s1", title="t", created_at="", updated_at="")
    payload, calls = gather_tool_context("300274 最新收盘价", session)
    assert order[0] == "ensure"
    assert "query_api" in order
    assert payload["data_ingest"]["ok"] is True
    assert payload["live_data"]["quote"]["close"] == 88.0
    assert session.stock_code == "300274"
    assert any(c.get("tool") == "ensure_stored_data" for c in calls)


def test_annual_report_needs_update_by_year_and_age(monkeypatch):
    monkeypatch.setenv("FINAGENT_ANNUAL_MAX_AGE_DAYS", "120")
    year = target_annual_report_year()
    assert annual_report_needs_update("600519", None) is True
    assert annual_report_needs_update("600519", {"report_year": year - 1, "fetched_at": "2026-01-01"}) is True
    assert (
        annual_report_needs_update(
            "600519",
            {"report_year": year, "fetched_at": "2020-01-01T00:00:00"},
        )
        is True
    )
    assert (
        annual_report_needs_update(
            "600519",
            {"report_year": year, "fetched_at": "2099-01-01T00:00:00"},
        )
        is False
    )


def test_bootstrap_stock_data_calls_all_gaps(monkeypatch, temp_db):
    calls: list[str] = []

    def _annual(code, **kwargs):
        calls.append("annual_report")
        return {"ok": True, "report_year": 2025, "sec_name": "测试股"}

    def _pit(code, **kwargs):
        calls.append("pit_financials")
        return {"ok": True, "row_count": 3}

    def _market(code, **kwargs):
        calls.append("market_snapshot")
        return {"ok": True, "snapshot_id": 1}

    monkeypatch.setattr("finagent.chat.data_ingest.ingest_annual_report", _annual)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_pit_financials", _pit)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_market_snapshot", _market)

    result = bootstrap_stock_data("300274", report_year=2025)
    assert result["ok"] is True
    assert calls == ["market_snapshot", "pit_financials", "annual_report"]


def test_incremental_persist_merges_price_rows(temp_db):
    from finagent.datastore.db import get_latest_snapshot, load_series, persist_market_snapshot

    persist_market_snapshot(
        {
            "order_book_id": "300750.XSHE",
            "stock_code": "300750",
            "start_date": "2026-01-01",
            "end_date": "2026-05-28",
            "price": {"rows": [{"date": "2026-05-28", "close": 101.0}], "row_count": 1},
            "technical": {"latest_close": 101.0},
        },
        lookback_days=60,
    )
    persist_market_snapshot(
        {
            "order_book_id": "300750.XSHE",
            "stock_code": "300750",
            "end_date": "2026-05-29",
            "price": {"rows": [{"date": "2026-05-29", "close": 102.0}], "row_count": 1},
            "technical": {"latest_close": 102.0},
        },
        lookback_days=60,
    )
    snap = get_latest_snapshot("300750")
    assert snap["id"] == 1
    rows = load_series(1, ["price"])["price"]["rows"]
    assert [r["date"] for r in rows] == ["2026-05-28", "2026-05-29"]


def test_ingest_market_snapshot_uses_latest_snapshot(monkeypatch, temp_db):
    from finagent.datastore import save_data_snapshot

    save_data_snapshot(
        {
            "order_book_id": "300750.XSHE",
            "end_date": "2026-05-29",
            "start_date": "2026-01-01",
            "price": {"rows": [{"date": "2026-05-29", "close": 250.0}]},
            "technical": {"latest_close": 250.0},
        },
        stock_code="300750",
    )

    monkeypatch.setattr(
        "finagent.chat.data_ingest.fetch_market_snapshot",
        lambda code, **kwargs: {"stock_code": code, "source": "rqdata", "end_date": "2026-05-29", "quote": {"close": 250.0}},
    )
    result = ingest_market_snapshot("300750")
    assert result["ok"] is True
    assert result["snapshot_id"] == 1
