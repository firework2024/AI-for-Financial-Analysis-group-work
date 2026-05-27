from finagent.fallback import apply_financial_fallbacks
from finagent.financial_analysis import analyze_financials


def test_financial_agent_output_shape():
    rows = [
        {"year": 2024, "quarter": "2024q4", "revenue": 100.0, "net_profit": 10.0, "net_profit_parent_company": 9.0, "cash_flow_from_operating_activities": 8.0, "cost_of_goods_sold": 60.0, "cash_received_from_sales_of_goods": 90.0, "cash_paid_for_asset": 3.0, "total_assets": 200.0, "total_liabilities": 80.0, "equity_parent_company": 120.0},
        {"year": 2025, "quarter": "2025q4", "revenue": 120.0, "net_profit": 15.0, "net_profit_parent_company": 14.0, "cash_flow_from_operating_activities": 18.0, "cost_of_goods_sold": 65.0, "cash_received_from_sales_of_goods": 130.0, "cash_paid_for_asset": 4.0, "total_assets": 220.0, "total_liabilities": 90.0, "equity_parent_company": 130.0},
    ]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched)
    assert set(result) == {
        "positive_signals",
        "negative_signals",
        "key_risks",
        "reviewed_signals",
        "raw_signals",
        "data_notes",
        "metrics",
    }
    assert result["positive_signals"]
    assert "structured_signals" in result["raw_signals"]
    assert "compound_signals" in result["raw_signals"]
    assert "signal_summary" in result["raw_signals"]
    joined = "".join(result["positive_signals"] + result["negative_signals"])
    assert "买" not in joined and "卖" not in joined


def test_metric_factor_fallback_fills_missing_metric_only():
    rows = [{"year": 2025, "quarter": "2025q4", "revenue": 100.0}]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched, {2025: {"inventory_turnover": 2.5}})
    assert result["metrics"][0]["inventory_turnover"] == 2.5
    assert result["metrics"][0]["metric_sources"]["inventory_turnover"] == "rqdata_factor"


def test_compound_and_high_risk_signals_are_preserved_in_local_review():
    rows = [
        {
            "year": 2023,
            "quarter": "2023q4",
            "revenue": 100.0,
            "net_profit": 10.0,
            "net_profit_parent_company": 10.0,
            "net_profit_deduct_non_recurring_pnl": 9.0,
            "cash_flow_from_operating_activities": 12.0,
            "cash_received_from_sales_of_goods": 100.0,
            "cash_paid_for_asset": 5.0,
            "cost_of_goods_sold": 60.0,
            "total_assets": 180.0,
            "total_liabilities": 80.0,
            "current_assets": 90.0,
            "current_liabilities": 60.0,
            "equity_parent_company": 100.0,
            "inventory": 30.0,
            "bill_accts_receivable": 20.0,
        },
        {
            "year": 2024,
            "quarter": "2024q4",
            "revenue": 110.0,
            "net_profit": 12.0,
            "net_profit_parent_company": 12.0,
            "net_profit_deduct_non_recurring_pnl": 11.0,
            "cash_flow_from_operating_activities": 10.0,
            "cash_received_from_sales_of_goods": 95.0,
            "cash_paid_for_asset": 6.0,
            "cost_of_goods_sold": 70.0,
            "total_assets": 200.0,
            "total_liabilities": 95.0,
            "current_assets": 100.0,
            "current_liabilities": 70.0,
            "equity_parent_company": 105.0,
            "inventory": 40.0,
            "bill_accts_receivable": 25.0,
        },
        {
            "year": 2025,
            "quarter": "2025q4",
            "revenue": 130.0,
            "net_profit": 14.0,
            "net_profit_parent_company": 15.0,
            "net_profit_deduct_non_recurring_pnl": 10.0,
            "cash_flow_from_operating_activities": 6.0,
            "cash_received_from_sales_of_goods": 70.0,
            "cash_paid_for_asset": 20.0,
            "cost_of_goods_sold": 88.0,
            "total_assets": 220.0,
            "total_liabilities": 130.0,
            "current_assets": 105.0,
            "current_liabilities": 100.0,
            "equity_parent_company": 110.0,
            "inventory": 60.0,
            "bill_accts_receivable": 45.0,
            "selling_expense": 8.0,
        },
    ]
    enriched = apply_financial_fallbacks(rows, "")
    result = analyze_financials(enriched)

    compound_metrics = {item["metric"] for item in result["raw_signals"]["compound_signals"]}
    assert "revenue_growth_vs_cash_flow" in compound_metrics
    assert "profit_growth_vs_cash_flow" in compound_metrics
    assert any(
        item["polarity"] == "negative"
        and item["severity"] == "high"
        and "cash_to_profit" in item["metrics"]
        for item in result["reviewed_signals"]
    )
    assert any("现金流质量风险" == item for item in result["key_risks"])
