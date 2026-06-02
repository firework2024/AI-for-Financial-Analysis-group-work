import json
from pathlib import Path

import pytest

from finagent.datastore import init_db, query_stored_data, save_annual_report_record, save_data_snapshot, save_pit_financials
from finagent.datastore.db import get_latest_snapshot, load_series
from finagent.rqdata_client import FinancialFetchResult


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("FINAGENT_DB_PATH", str(db_path))
    init_db(db_path)
    return db_path


def test_save_and_query_snapshot(temp_db):
    data = {
        "order_book_id": "600519.XSHG",
        "start_date": "2025-01-01",
        "end_date": "2025-05-29",
        "price": {
            "rows": [{"date": "2025-05-28", "close": 100.0}, {"date": "2025-05-29", "close": 101.5}],
            "row_count": 2,
            "columns": ["date", "close"],
        },
        "factor": {"pe_ratio_ttm": 20.1, "pb_ratio_ttm": 3.2},
        "technical": {"latest_close": 101.5, "return_20d": 0.05},
        "pit_financials": {"rows": [{"year": 2024, "quarter": "2024q4", "revenue": 1e10}], "row_count": 1},
    }
    snapshot_id = save_data_snapshot(data, stock_code="600519", lookback_days=60)
    assert snapshot_id == 1

    latest = get_latest_snapshot("600519")
    assert latest is not None
    assert latest["order_book_id"] == "600519.XSHG"

    series = load_series(snapshot_id, ["price"], tail=1)
    assert len(series["price"]["rows"]) == 1
    assert series["price"]["rows"][0]["close"] == 101.5

    stored = query_stored_data("600519", "最近股价和PE怎么样")
    assert stored is not None
    assert stored["snapshot"]["id"] == snapshot_id
    assert "price" in stored["series"]
    assert stored["technical"]["latest_close"] == 101.5


def test_save_pit_financials(temp_db):
    rows = [{"year": 2024, "quarter": "2024q4", "revenue": 123.0}]
    result = FinancialFetchResult(rows=rows, order_book_id="300750.XSHE", quarters=["2024q4"])
    save_pit_financials(result, stock_code="300750", report_year=2024, years=3)

    stored = query_stored_data("300750", "营收和利润")
    assert stored is not None
    assert stored["pit_financials_cache"]["rows"][0]["revenue"] == 123.0


def test_query_matches_margin_keywords(temp_db):
    data = {
        "order_book_id": "300750.XSHE",
        "end_date": "2025-05-29",
        "securities_margin": {
            "rows": [{"date": "2025-05-29", "margin_balance": 999.0}],
            "row_count": 1,
        },
    }
    save_data_snapshot(data, stock_code="300750")
    stored = query_stored_data("300750", "融资余额最近如何")
    assert stored is not None
    assert "securities_margin" in stored["series"]


def test_upsert_market_snapshot_incremental(temp_db):
    from finagent.datastore import list_snapshots, persist_market_snapshot

    first = {
        "order_book_id": "300750.XSHE",
        "stock_code": "300750",
        "start_date": "2026-01-01",
        "end_date": "2026-05-28",
        "price": {
            "rows": [{"date": "2026-05-27", "close": 100.0}, {"date": "2026-05-28", "close": 101.0}],
            "row_count": 2,
            "columns": ["date", "close"],
        },
        "technical": {"latest_close": 101.0},
    }
    sid1 = persist_market_snapshot(first, lookback_days=60)
    second = {
        "order_book_id": "300750.XSHE",
        "stock_code": "300750",
        "start_date": "2026-05-29",
        "end_date": "2026-05-29",
        "price": {
            "rows": [{"date": "2026-05-28", "close": 101.5}, {"date": "2026-05-29", "close": 102.0}],
            "row_count": 2,
            "columns": ["date", "close"],
        },
        "technical": {"latest_close": 102.0},
    }
    sid2 = persist_market_snapshot(second, lookback_days=60)
    assert sid1 == sid2 == 1
    assert len(list_snapshots("300750", limit=5)) == 1

    series = load_series(1, ["price"])
    dates = [r["date"] for r in series["price"]["rows"]]
    assert dates == ["2026-05-27", "2026-05-28", "2026-05-29"]
    assert series["price"]["rows"][-1]["close"] == 102.0

    stored = query_stored_data("300750", "最近股价")
    assert stored["technical"]["latest_close"] == 102.0


def test_persist_market_snapshot_matches_executor_shape(temp_db):
    from finagent.datastore import list_snapshots, persist_market_snapshot

    data = {
        "order_book_id": "600519.XSHG",
        "stock_code": "600519",
        "sec_name": "贵州茅台",
        "start_date": "2025-11-01",
        "end_date": "2026-05-29",
        "price": {
            "rows": [{"date": "2026-05-29", "close": 1326.0}],
            "row_count": 1,
            "columns": ["date", "close"],
        },
        "securities_margin": {
            "rows": [{"date": "2026-05-28", "margin_balance": 20048000000.0}],
            "row_count": 1,
        },
        "interbank_rate": {
            "rows": [{"date": "2026-05-29", "ON": 0.01324}],
            "row_count": 1,
        },
        "factor": {"pe_ratio_ttm": 20.04},
        "technical": {"latest_close": 1326.0, "rsi_14": 41.04},
        "industry": {"first_industry_name": "食品饮料"},
    }
    snapshot_id = persist_market_snapshot(data, lookback_days=180, source="data_executor")
    assert snapshot_id == 1
    assert data.get("data_snapshot_id") is None  # caller attaches id when needed

    snapshots = list_snapshots("600519", limit=1)
    assert snapshots[0]["order_book_id"] == "600519.XSHG"
    assert snapshots[0]["lookback_days"] == 180

    stored = query_stored_data("600519", "最近股价和融资余额")
    assert stored is not None
    assert "price" in stored["series"]
    assert "securities_margin" in stored["series"]


def test_save_annual_report_and_query(temp_db):
    financial = [
        {
            "year": 2024,
            "quarter": "2024q4",
            "fields": {"revenue": {"value": 500.0, "source": "annual_report"}},
        }
    ]
    save_annual_report_record(
        stock_code="000001",
        report_year=2024,
        sec_name="平安银行",
        title="2024年报",
        pdf_path="annual_reports/000001.pdf",
        financial_data=financial,
        mda_text="管理层讨论与分析：本期营收稳步增长，资产质量保持稳定。",
        mda_meta={"confidence": "high", "summary": "营收稳增"},
    )
    stored = query_stored_data("000001", "年报里管理层怎么说的")
    assert stored is not None
    assert stored["annual_report"]["report_year"] == 2024
    assert stored["annual_report"]["mda_hits"]
    assert "管理层" in stored["annual_report"]["mda_hits"][0]["text"]
    assert "\n" in stored["annual_report"]["mda_hits"][0]["text"] or "管理层讨论与分析" in stored["annual_report"]["mda_hits"][0]["text"]
    assert stored["annual_report"]["financial_data"][0]["fields"]["revenue"]["source"] == "annual_report"


def test_relaxed_local_load_ignores_lookback_metadata(temp_db):
    from datetime import date

    from finagent.datastore.market_cache import (
        load_executor_payload_from_snapshot,
        snapshot_usable_for_executor,
    )

    data = {
        "order_book_id": "000001.XSHE",
        "start_date": "2025-01-01",
        "end_date": "2025-05-29",
        "price": {
            "rows": [{"date": "2025-05-28", "close": 10.0}, {"date": "2025-05-29", "close": 10.5}],
            "row_count": 2,
            "columns": ["date", "close"],
        },
    }
    save_data_snapshot(data, stock_code="000001", lookback_days=90)
    snap = get_latest_snapshot("000001")
    assert snap is not None
    assert snapshot_usable_for_executor(snap, as_of=date(2026, 6, 2), lookback_days=260) is False

    payload = load_executor_payload_from_snapshot(
        "000001",
        lookback_days=260,
        relaxed=True,
        as_of=date(2026, 6, 2),
    )
    assert payload is not None
    assert payload["source"] == "local_db_relaxed"
    assert payload["price"]["row_count"] == 2
    assert any("回看" in note for note in (payload.get("local_cache_warnings") or []))
