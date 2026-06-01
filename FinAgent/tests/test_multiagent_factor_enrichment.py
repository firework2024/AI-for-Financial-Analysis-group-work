from finagent.multiagent import _enrich_multi_factor_payload


def test_multiagent_factor_enrichment_uses_local_primitives(monkeypatch):
    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [
                {
                    "quarter": "2023q4",
                    "year": 2023,
                    "revenue": 800.0,
                    "net_profit": 80.0,
                    "net_profit_parent_company": 70.0,
                    "equity_parent_company": 700.0,
                    "total_assets": 1_500.0,
                    "total_liabilities": 600.0,
                    "current_assets": 500.0,
                    "current_liabilities": 250.0,
                    "inventory": 100.0,
                },
                {
                    "quarter": "2024q4",
                    "year": 2024,
                    "revenue": 1_000.0,
                    "net_profit": 120.0,
                    "net_profit_parent_company": 100.0,
                    "equity_parent_company": 900.0,
                    "total_assets": 2_000.0,
                    "total_liabilities": 800.0,
                    "current_assets": 600.0,
                    "current_liabilities": 300.0,
                    "inventory": 150.0,
                },
            ]
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    payload = {
        "factor": {},
        "price": {"rows": [{"date": "2026-06-01", "close": 20.0}]},
        "shares": {"rows": [{"date": "2026-06-01", "total": 100.0}]},
        "factor_history": {"rows": [{"date": "2026-06-01"}], "columns": ["date"]},
    }

    _enrich_multi_factor_payload(payload, "688041")

    factor = payload["factor"]
    assert factor["market_cap"] == 2000.0
    assert factor["pe_ratio_ttm"] == 20.0
    assert factor["pb_ratio_ttm"] == 2.22
    assert factor["ps_ratio_ttm"] == 2.0
    assert factor["roe_ttm"] == 0.125
    assert factor["net_profit_parent_company_margin_ttm"] == 0.1
    assert factor["debt_to_asset_ratio"] == 40.0
    assert factor["current_ratio"] == 2.0
    assert factor["quick_ratio"] == 1.5

    latest = payload["factor_history"]["rows"][-1]
    assert latest["pe_ratio_ttm"] == 20.0
    assert "pe_ratio_ttm" in payload["factor_history"]["columns"]


def test_multiagent_factor_enrichment_does_not_overwrite_existing_rq_factor(monkeypatch):
    monkeypatch.setattr("finagent.datastore.db.get_pit_financials", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    payload = {
        "factor": {"pe_ratio_ttm": 33.0, "pb_ratio_ttm": 4.0},
        "price": {"rows": [{"date": "2026-06-01", "close": 20.0}]},
        "factor_history": {"rows": [{"date": "2026-06-01", "pe_ratio_ttm": 33.0}], "columns": ["date", "pe_ratio_ttm"]},
    }

    _enrich_multi_factor_payload(payload, "688041")

    assert payload["factor"]["pe_ratio_ttm"] == 33.0
    assert payload["factor"]["pb_ratio_ttm"] == 4.0
