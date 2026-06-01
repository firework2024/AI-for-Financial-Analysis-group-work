from finagent.chat.data_tools import _enrich_valuation_payload, _apply_derived_valuation, fetch_valuation_snapshot


def test_enrich_valuation_from_eastmoney(monkeypatch):
    monkeypatch.setattr(
        "finagent.chat.quote_sources.fetch_eastmoney_quote",
        lambda _code: {
            "pe_ttm": 302.93,
            "pb": 76.97,
            "name": "寒武纪",
            "date": "2026-05-29",
            "close": 1310.0,
        },
    )
    payload = _enrich_valuation_payload({"stock_code": "688256", "factor": {}}, "688256")
    assert payload["factor"]["pe_ratio_ttm"] == 302.93
    assert payload["factor"]["pe_ratio_ttm_source"] == "eastmoney"
    assert payload["quote"]["pe_ttm"] == 302.93


def test_fetch_valuation_snapshot_uses_eastmoney_when_factor_empty(monkeypatch):
    monkeypatch.setattr(
        "finagent.chat.data_tools._local_snapshot_fallback",
        lambda _code: None,
    )
    monkeypatch.setattr(
        "finagent.chat.data_tools.fetch_market_snapshot",
        lambda _code, **kwargs: {"stock_code": _code, "factor": {}, "quote": {}},
    )
    monkeypatch.setattr(
        "finagent.chat.quote_sources.fetch_eastmoney_quote",
        lambda _code: {"pe_ttm": 222.2, "name": "中芯国际", "date": "2026-05-29"},
    )
    live = fetch_valuation_snapshot("688981")
    assert live["factor"]["pe_ratio_ttm"] == 222.2


def test_derive_pe_from_market_cap_and_pit_profit(monkeypatch):
    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [{"quarter": "2024q4", "year": 2024, "net_profit_parent_company": 2_000_000_000.0}],
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)

    out = _apply_derived_valuation(
        {"market_cap": 400_000_000_000.0},
        {"close": 200.0},
        "688041",
    )
    assert out["pe_ratio_ttm"] == 200.0
    assert out["pe_ratio_ttm_source"] == "derived_cap_profit"


def test_do_not_derive_pe_from_non_parent_profit(monkeypatch):
    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {"rows": [{"quarter": "2024q4", "year": 2024, "net_profit": 2_000_000_000.0}]},
    )
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)

    out = _apply_derived_valuation({"market_cap": 400_000_000_000.0}, {}, "688041")
    assert "pe_ratio_ttm" not in out


def test_derive_pe_from_price_shares_and_pit_profit(monkeypatch):
    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [{"quarter": "2024q4", "year": 2024, "net_profit_parent_company": 1_000_000_000.0}],
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: {"id": 1})
    monkeypatch.setattr(
        "finagent.datastore.db.load_series",
        lambda _sid, keys, tail=1: {"shares": {"rows": [{"total": 100_000_000.0}]}},
    )
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)

    out = _apply_derived_valuation({}, {"close": 200.0}, "688041")
    assert out["pe_ratio_ttm"] == 20.0
    assert out["pe_ratio_ttm_source"] == "derived_cap_profit"


def test_derive_pe_from_ps_and_margin_only_when_primitives_missing(monkeypatch):
    monkeypatch.setattr("finagent.datastore.db.get_pit_financials", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    factor = {
        "market_cap": 500_000_000_000.0,
        "ps_ratio_ttm": 10.0,
        "net_profit_margin_ttm": 0.05,
        "net_profit_parent_company_margin_ttm": 0.05,
    }
    out = _apply_derived_valuation(factor, {"close": 100.0}, "688041")
    assert out["pe_ratio_ttm"] == 200.0
    assert out["pe_ratio_ttm_source"] == "derived_ps_parent_margin"


def test_do_not_derive_pe_from_non_parent_net_margin(monkeypatch):
    monkeypatch.setattr("finagent.datastore.db.get_pit_financials", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    out = _apply_derived_valuation(
        {"market_cap": 500_000_000_000.0, "ps_ratio_ttm": 10.0, "net_profit_margin_ttm": 0.05},
        {},
        "688041",
    )
    assert "pe_ratio_ttm" not in out


def test_derive_other_financial_factors_from_raw_rows(monkeypatch):
    from finagent.chat.data_tools import _apply_derived_financial_factors

    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [
                {
                    "quarter": "2023q4",
                    "year": 2023,
                    "revenue": 8_000.0,
                    "cost_of_goods_sold": 5_000.0,
                    "net_profit": 800.0,
                    "net_profit_parent_company": 700.0,
                    "profit_from_operation": 900.0,
                    "total_assets": 20_000.0,
                    "total_liabilities": 6_000.0,
                    "current_assets": 7_000.0,
                    "current_liabilities": 3_500.0,
                    "inventory": 1_000.0,
                    "equity_parent_company": 12_000.0,
                },
                {
                    "quarter": "2024q4",
                    "year": 2024,
                    "revenue": 10_000.0,
                    "cost_of_goods_sold": 6_000.0,
                    "net_profit": 1_200.0,
                    "net_profit_parent_company": 1_000.0,
                    "profit_from_operation": 1_350.0,
                    "total_assets": 25_000.0,
                    "total_liabilities": 10_000.0,
                    "current_assets": 8_000.0,
                    "current_liabilities": 4_000.0,
                    "inventory": 2_000.0,
                    "equity_parent_company": 15_000.0,
                },
            ]
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    out = _apply_derived_financial_factors({"market_cap": 200_000.0}, {}, "688041")
    assert out["gross_profit_margin_ttm"] == 0.4
    assert out["net_profit_margin_ttm"] == 0.12
    assert out["net_profit_parent_company_margin_ttm"] == 0.1
    assert out["roe_ttm"] == 0.0741
    assert out["debt_to_asset_ratio"] == 40.0
    assert out["current_ratio"] == 2.0
    assert out["quick_ratio"] == 1.5
    assert out["ps_ratio_ttm"] == 20.0
    assert out["operating_revenue_growth_ratio_ttm"] == 0.25
    assert out["net_profit_growth_ratio_ttm"] == 0.5
    assert out["net_profit_parent_company_growth_ratio_ttm"] == 0.4286
    assert out["operating_profit_growth_ratio_ttm"] == 0.5
    assert out["gross_profit_growth_ratio_ttm"] == 0.3333


def test_roe_uses_average_parent_equity(monkeypatch):
    from finagent.chat.data_tools import _apply_derived_financial_factors

    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [
                {
                    "quarter": "2023q4",
                    "year": 2023,
                    "revenue": 100.0,
                    "net_profit_parent_company": 10.0,
                    "equity_parent_company": 80.0,
                },
                {
                    "quarter": "2024q4",
                    "year": 2024,
                    "revenue": 100.0,
                    "net_profit_parent_company": 15.0,
                    "equity_parent_company": 120.0,
                },
            ]
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    out = _apply_derived_financial_factors({}, {}, "688041")
    assert out["roe_ttm"] == 0.15


def test_parent_margin_does_not_fall_back_to_plain_net_profit(monkeypatch):
    from finagent.chat.data_tools import _apply_derived_financial_factors

    monkeypatch.setattr(
        "finagent.datastore.db.get_pit_financials",
        lambda _code: {
            "rows": [
                {
                    "quarter": "2024q4",
                    "year": 2024,
                    "revenue": 100.0,
                    "net_profit": 12.0,
                    "equity_parent_company": 120.0,
                }
            ]
        },
    )
    monkeypatch.setattr("finagent.datastore.db.get_annual_report", lambda _code: None)
    monkeypatch.setattr("finagent.datastore.db.get_latest_snapshot", lambda _code: None)

    out = _apply_derived_financial_factors({}, {}, "688041")
    assert out["net_profit_margin_ttm"] == 0.12
    assert "net_profit_parent_company_margin_ttm" not in out
    assert "roe_ttm" not in out
