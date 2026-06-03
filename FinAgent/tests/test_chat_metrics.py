from finagent.chat.intent import classify_query_intent
from finagent.chat.metrics import extract_financial_facts, filter_financial_rows, resolve_focused_metrics


def test_resolve_pe():
    assert resolve_focused_metrics("他们的pe") == ["市盈率"]
    assert resolve_focused_metrics("这几个公司的PE") == ["市盈率"]


def test_resolve_total_assets():
    assert resolve_focused_metrics("总资产？") == ["总资产"]


def test_resolve_net_profit_only():
    assert resolve_focused_metrics("我只要净利润") == ["净利润"]


def test_filter_financial_rows():
    rows = [
        {"year": 2025, "revenue": 100, "net_profit": 10, "total_assets": 500},
        {"year": 2024, "revenue": 90, "net_profit": 9, "total_assets": 480},
    ]
    slim = filter_financial_rows(rows, ["净利润"])
    assert slim[-1] == {"year": 2025, "net_profit": 10}
    assert "revenue" not in slim[-1]


def test_narrow_only_when_user_asks():
    intent = classify_query_intent("总资产")
    assert intent.focused_metrics == ["总资产"]
    assert intent.narrow_answer is False
    assert classify_query_intent("我只要净利润").narrow_answer is True


def test_extract_financial_facts():
    stored = {
        "stock_code": "000001",
        "annual_report": {
            "sec_name": "平安银行",
            "report_year": 2025,
            "financial_data": [
                {"year": 2025, "net_profit": 426.33, "total_assets": 59300},
                {"year": 2024, "net_profit": 445.08, "total_assets": 57700},
            ],
        },
    }
    facts = extract_financial_facts(stored, ["总资产"])
    assert facts
    by_year = {row["year"]: row for row in facts["by_source"]["annual"]}
    assert by_year[2025]["total_assets"] == 59300


def test_extract_financial_facts_net_margin_from_pit_rows():
    stored = {
        "stock_code": "300750",
        "pit_financials_cache": {
            "rows": [
                {"year": 2023, "revenue": 400.0, "net_profit": 46.6},
                {"year": 2024, "revenue": 360.0, "net_profit": 54.0},
                {"year": 2025, "revenue": 420.0, "net_profit": 76.2},
            ],
        },
    }
    facts = extract_financial_facts(stored, ["净利率"])
    assert facts is not None
    pit = facts["by_source"]["pit"]
    assert len(pit) == 3
    assert pit[0]["net_profit_margin_pct"] == 11.65
    assert pit[-1]["net_profit_margin_pct"] == 18.14
    assert "revenue" in pit[-1]
    assert facts.get("derived_notes")


def test_filter_financial_rows_net_margin():
    rows = [
        {"year": 2024, "operating_revenue": 100.0, "net_profit": 15.0},
        {"year": 2025, "operating_revenue": 120.0, "net_profit": 24.0},
    ]
    slim = filter_financial_rows(rows, ["净利率"])
    assert len(slim) == 2
    assert slim[0]["net_profit_margin_pct"] == 15.0
    assert slim[1]["net_profit_margin_pct"] == 20.0


def test_extract_financial_facts_roe_and_debt_from_pit():
    stored = {
        "pit_financials_cache": {
            "rows": [
                {
                    "year": 2023,
                    "net_profit_parent_company": 10.0,
                    "equity_parent_company": 80.0,
                    "total_assets": 200.0,
                    "total_liabilities": 80.0,
                },
                {
                    "year": 2024,
                    "net_profit_parent_company": 15.0,
                    "equity_parent_company": 100.0,
                    "total_assets": 250.0,
                    "total_liabilities": 100.0,
                },
            ],
        },
    }
    roe_facts = extract_financial_facts(stored, ["ROE"])
    assert roe_facts is not None
    pit = roe_facts["by_source"]["pit"]
    assert pit[0]["roe_ttm"] == 0.125
    assert pit[1]["roe_ttm"] == 0.1667

    debt_facts = extract_financial_facts(stored, ["资产负债率"])
    pit_debt = debt_facts["by_source"]["pit"]
    assert pit_debt[0]["debt_to_asset_ratio"] == 40.0
    assert pit_debt[1]["debt_to_asset_ratio"] == 40.0


def test_extract_financial_facts_revenue_growth_yoy():
    stored = {
        "pit_financials_cache": {
            "rows": [
                {"year": 2023, "revenue": 100.0},
                {"year": 2024, "revenue": 110.0},
                {"year": 2025, "revenue": 121.0},
            ],
        },
    }
    facts = extract_financial_facts(stored, ["营收增速"])
    pit = facts["by_source"]["pit"]
    assert len(pit) == 3
    assert "operating_revenue_growth_ratio_ttm" not in pit[0]
    assert pit[1]["operating_revenue_growth_ratio_ttm"] == 0.1
    assert pit[2]["operating_revenue_growth_ratio_ttm"] == 0.1


def test_filter_financial_rows_current_and_quick_ratio():
    rows = [
        {
            "year": 2024,
            "current_assets": 150.0,
            "current_liabilities": 100.0,
            "inventory": 30.0,
        },
    ]
    slim = filter_financial_rows(rows, ["流动比率", "速动比率"])
    assert slim[0]["current_ratio"] == 1.5
    assert slim[0]["quick_ratio"] == 1.2
