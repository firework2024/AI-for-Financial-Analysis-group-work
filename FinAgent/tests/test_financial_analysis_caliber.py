"""financial_analysis._metrics_for_row 教科书口径回归（与 data_tools 归母/均值原则对齐）。"""

from finagent.fallback import apply_financial_fallbacks
from finagent.financial_analysis import analyze_financials


def _metrics(rows: list[dict]) -> list[dict]:
    enriched = apply_financial_fallbacks(rows, "")
    return analyze_financials(enriched)["metrics"]


def test_gross_margin_quick_ratio_and_debt_ratio():
    metrics = _metrics(
        [
            {
                "year": 2024,
                "quarter": "2024q4",
                "revenue": 1_000.0,
                "cost_of_goods_sold": 600.0,
                "current_assets": 600.0,
                "current_liabilities": 300.0,
                "inventory": 150.0,
                "total_assets": 2_000.0,
                "total_liabilities": 800.0,
                "equity_parent_company": 1_200.0,
                "net_profit": 120.0,
                "net_profit_parent_company": 100.0,
            }
        ]
    )
    row = metrics[0]
    assert row["gross_margin"] == 0.4
    assert row["quick_ratio"] == 1.5
    assert row["debt_to_assets"] == 0.4


def test_roe_uses_parent_profit_not_total_net_profit():
    metrics = _metrics(
        [
            {
                "year": 2024,
                "quarter": "2024q4",
                "revenue": 1_000.0,
                "net_profit": 120.0,
                "net_profit_parent_company": 100.0,
                "equity_parent_company": 900.0,
                "total_assets": 2_000.0,
            }
        ]
    )
    assert metrics[0]["roe"] == 100.0 / 900.0
    assert metrics[0]["roe"] != 120.0 / 900.0


def test_roe_missing_when_parent_profit_or_equity_missing():
    metrics = _metrics(
        [
            {
                "year": 2024,
                "quarter": "2024q4",
                "revenue": 1_000.0,
                "net_profit": 120.0,
                "equity_parent_company": 900.0,
                "total_assets": 2_000.0,
            }
        ]
    )
    assert metrics[0]["roe"] is None


def test_roe_and_roa_use_average_denominators_from_second_year():
    metrics = _metrics(
        [
            {
                "year": 2023,
                "quarter": "2023q4",
                "revenue": 800.0,
                "net_profit": 80.0,
                "net_profit_parent_company": 70.0,
                "equity_parent_company": 700.0,
                "total_assets": 1_500.0,
                "cost_of_goods_sold": 500.0,
            },
            {
                "year": 2024,
                "quarter": "2024q4",
                "revenue": 1_000.0,
                "net_profit": 120.0,
                "net_profit_parent_company": 100.0,
                "equity_parent_company": 900.0,
                "total_assets": 2_000.0,
                "cost_of_goods_sold": 600.0,
            },
        ]
    )
    assert metrics[0]["roe"] == 70.0 / 700.0
    assert metrics[1]["roe"] == 100.0 / 800.0
    assert metrics[0]["roa"] == 80.0 / 1_500.0
    assert metrics[1]["roa"] == 120.0 / 1_750.0
    assert metrics[1]["asset_turnover"] == 1_000.0 / 1_750.0


def test_metric_factor_fallback_does_not_override_computed_roe():
    rows = [
        {
            "year": 2023,
            "quarter": "2023q4",
            "net_profit_parent_company": 70.0,
            "equity_parent_company": 700.0,
            "total_assets": 1_500.0,
            "net_profit": 80.0,
        },
        {
            "year": 2024,
            "quarter": "2024q4",
            "net_profit_parent_company": 100.0,
            "equity_parent_company": 900.0,
            "total_assets": 2_000.0,
            "net_profit": 120.0,
        },
    ]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched, {2024: {"roe": 0.99}})
    assert result["metrics"][1]["roe"] == 100.0 / 800.0
    assert "roe" not in result["metrics"][1].get("metric_sources", {})
