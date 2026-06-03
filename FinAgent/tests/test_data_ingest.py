import pytest

from finagent.chat.data_ingest import (
    AnnualCacheError,
    annual_report_needs_update,
    bootstrap_stock_data,
    ensure_annual_report_in_store,
    ensure_report_data_for_generation,
    ensure_stored_data,
    get_data_coverage,
    get_data_gaps,
    ingest_market_snapshot,
    run_data_ingest,
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
    assert "market_history" in gaps
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

    monkeypatch.setattr("finagent.chat.data_ingest.ingest_market_history", fake_ingest)
    monkeypatch.setattr("finagent.chat.data_ingest.get_data_gaps", lambda _c, _q: ["market_history"])

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


def test_bootstrap_stock_data_defaults_to_light_gaps(monkeypatch, temp_db):
    calls: list[str] = []

    def _annual(code, **kwargs):
        calls.append("annual_report")
        return {"ok": True, "report_year": 2025, "sec_name": "测试股"}

    def _pit(code, **kwargs):
        calls.append("pit_financials")
        return {"ok": True, "row_count": 3}

    def _market(code, **kwargs):
        calls.append("market_history")
        return {"ok": True, "snapshot_id": 1}

    monkeypatch.setattr("finagent.chat.data_ingest.ingest_annual_report", _annual)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_pit_financials", _pit)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_market_history", _market)

    result = bootstrap_stock_data("300274", report_year=2025)
    assert result["ok"] is True
    assert set(calls) == {"market_history", "pit_financials"}
    assert result["requested_gaps"] == ["market_history", "pit_financials"]


def test_bootstrap_stock_data_can_include_annual(monkeypatch, temp_db):
    calls: list[str] = []

    def _annual(code, **kwargs):
        calls.append("annual_report")
        return {"ok": True, "report_year": 2025, "sec_name": "测试股"}

    def _pit(code, **kwargs):
        calls.append("pit_financials")
        return {"ok": True, "row_count": 3}

    def _market(code, **kwargs):
        calls.append("market_history")
        return {"ok": True, "snapshot_id": 1}

    monkeypatch.setenv("FINAGENT_BOOTSTRAP_INCLUDE_ANNUAL_REPORT", "true")
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_annual_report", _annual)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_pit_financials", _pit)
    monkeypatch.setattr("finagent.chat.data_ingest.ingest_market_history", _market)

    result = bootstrap_stock_data("300274", report_year=2025)
    assert result["ok"] is True
    assert set(calls) == {"market_history", "pit_financials", "annual_report"}
    assert result["requested_gaps"] == ["market_history", "pit_financials", "annual_report"]


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


def test_ensure_annual_report_in_store_cached_only(temp_db):
    from finagent.chat.data_ingest import AnnualCacheError, ensure_annual_report_in_store
    from finagent.datastore import save_annual_report_record

    with pytest.raises(AnnualCacheError):
        ensure_annual_report_in_store("000001", use_cached_only=True)

    save_annual_report_record(
        stock_code="000001",
        report_year=2024,
        sec_name="平安银行",
        title="2024年报",
        pdf_path="x.pdf",
        financial_data=[{"year": 2024, "quarter": "2024q4"}],
        mda_text="MD&A 摘要",
    )
    annual = ensure_annual_report_in_store("000001", use_cached_only=True)
    assert annual is not None
    assert annual.get("report_year") == 2024


def test_get_data_coverage_empty_db(temp_db):
    cov = get_data_coverage("300750")
    assert cov["stock_code"] == "300750"
    assert "market_history" in cov["gaps"]
    assert cov["ready_for_chat"] is False


def test_get_data_coverage_placeholder_pit_flags_gap(temp_db):
    from finagent.datastore import save_pit_financials
    from finagent.rqdata_client import FinancialFetchResult

    save_pit_financials(
        FinancialFetchResult(
            rows=[{"year": 2024, "quarter": "2024q4"}, {"year": 2023, "quarter": "2023q4"}],
            order_book_id="300750.XSHE",
            quarters=["2024q4", "2023q4"],
        ),
        stock_code="300750",
        report_year=2024,
        years=3,
    )
    cov = get_data_coverage("300750")
    pit = cov["pit_financials"]
    assert pit["row_count"] == 2
    assert pit["rows_with_values"] == 0
    assert pit["placeholder_only"] is True
    assert pit["present"] is False
    assert "pit_financials" in cov["gaps"]


def test_ingest_pit_refetches_placeholder(monkeypatch, temp_db):
    from finagent.chat.data_ingest import ingest_pit_financials
    from finagent.datastore import save_pit_financials
    from finagent.rqdata_client import FinancialFetchResult

    save_pit_financials(
        FinancialFetchResult(
            rows=[{"year": 2024, "quarter": "2024q4"}],
            order_book_id="300750.XSHE",
            quarters=["2024q4"],
        ),
        stock_code="300750",
        report_year=2024,
        years=3,
    )

    def fake_fetch(code, year, years=3):
        from finagent.datastore import save_pit_financials

        result = FinancialFetchResult(
            rows=[{"year": year, "quarter": f"{year}q4", "net_profit": 1.0e9}],
            order_book_id="300750.XSHE",
            quarters=[f"{year}q4"],
        )
        save_pit_financials(result, stock_code=code, report_year=int(year), years=years)
        return result

    monkeypatch.setattr("finagent.rqdata_client.fetch_financials", fake_fetch)

    first = ingest_pit_financials("300750")
    assert first.get("ok") is True
    assert first.get("usable") is True
    assert first.get("rows_with_values") == 1

    second = ingest_pit_financials("300750")
    assert second.get("skipped") is True
    assert second.get("rows_with_values") == 1


def test_report_generation_cached_only_accepts_stale_local_data(temp_db):
    from finagent.datastore import save_annual_report_record, save_data_snapshot, save_pit_financials
    from types import SimpleNamespace

    save_data_snapshot(
        {
            "order_book_id": "300750.XSHE",
            "end_date": "2025-01-10",
            "start_date": "2024-01-01",
            "price": {"rows": [{"date": "2025-01-10", "close": 200.0}], "row_count": 1},
        },
        stock_code="300750",
        lookback_days=60,
    )
    save_pit_financials(
        SimpleNamespace(
            order_book_id="300750.XSHE",
            quarters=["2024q4"],
            rows=[{"quarter": "2024q4", "net_profit": 1.0}],
        ),
        stock_code="300750",
        report_year=2024,
        years=3,
    )
    save_annual_report_record(
        stock_code="300750",
        report_year=2024,
        sec_name="宁德时代",
        title="2024年报",
        pdf_path="x.pdf",
        financial_data=[{"year": 2024, "quarter": "2024q4"}],
        mda_text="MD&A 摘要",
    )

    out = ensure_report_data_for_generation("300750", use_cached_only=True, lookback_days=260)
    assert out.get("skipped") is True
    assert out["coverage"]["market_snapshot"]["present"] is True


def test_get_data_gaps_stale_triggers_quote_refresh(temp_db):
    from finagent.datastore import save_data_snapshot

    save_data_snapshot(
        {
            "order_book_id": "300750.XSHE",
            "end_date": "2025-01-10",
            "price": {"rows": [{"date": "2025-01-10", "close": 200.0}], "row_count": 1},
        },
        stock_code="300750",
        lookback_days=60,
    )
    gaps = get_data_gaps("300750", "宁德时代最新股价多少")
    assert "quote_refresh" in gaps


def test_run_data_ingest_query_driven_skips_when_satisfied(monkeypatch, temp_db):
    monkeypatch.setattr("finagent.chat.data_ingest.get_data_gaps", lambda _c, _q: [])
    result = run_data_ingest("300750", mode="query_driven", query="这份报告风险是什么")
    assert result.get("skipped") is True
    assert result["requested_gaps"] == []


def test_ensure_stored_data_uses_run_data_ingest(monkeypatch, temp_db):
    monkeypatch.setattr(
        "finagent.chat.data_ingest.run_data_ingest",
        lambda code, **kw: {"ok": True, "requested_gaps": ["market_snapshot"], "actions": []},
    )
    assert ensure_stored_data("300750", "最新股价") is not None
    monkeypatch.setattr(
        "finagent.chat.data_ingest.run_data_ingest",
        lambda code, **kw: {"ok": True, "skipped": True, "requested_gaps": [], "actions": []},
    )
    assert ensure_stored_data("300750", "风险是什么") is None
