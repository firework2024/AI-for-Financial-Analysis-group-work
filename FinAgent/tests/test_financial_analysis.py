from finagent.fallback import apply_financial_fallbacks
from finagent.financial_analysis import analyze_financials


def test_financial_agent_output_shape():
    rows = [
        {"year": 2024, "quarter": "2024q4", "revenue": 100.0, "net_profit": 10.0, "net_profit_parent_company": 9.0, "cash_flow_from_operating_activities": 8.0, "cost_of_goods_sold": 60.0, "cash_received_from_sales_of_goods": 90.0, "cash_paid_for_asset": 3.0, "total_assets": 200.0, "total_liabilities": 80.0, "equity_parent_company": 120.0},
        {"year": 2025, "quarter": "2025q4", "revenue": 120.0, "net_profit": 15.0, "net_profit_parent_company": 14.0, "cash_flow_from_operating_activities": 18.0, "cost_of_goods_sold": 65.0, "cash_received_from_sales_of_goods": 130.0, "cash_paid_for_asset": 4.0, "total_assets": 220.0, "total_liabilities": 90.0, "equity_parent_company": 130.0},
    ]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched)
    assert set(result) == {"positive_signals", "negative_signals", "data_notes", "metrics"}
    assert result["positive_signals"]
    joined = "".join(result["positive_signals"] + result["negative_signals"])
    assert "买" not in joined and "卖" not in joined


def test_metric_factor_fallback_fills_missing_metric_only():
    rows = [{"year": 2025, "quarter": "2025q4", "revenue": 100.0}]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched, {2025: {"inventory_turnover": 2.5}})
    assert result["metrics"][0]["inventory_turnover"] == 2.5
    assert result["metrics"][0]["metric_sources"]["inventory_turnover"] == "rqdata_factor"
