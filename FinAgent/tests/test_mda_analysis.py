from finagent.mda_analysis import (
    build_articulation_checks,
    build_annual_context_from_store,
    build_mda_financial_crosswalk,
    enrich_financial_analysis_with_mda,
    format_crosswalk_markdown,
)


def test_articulation_detects_profit_cash_divergence():
    metrics = [
        {
            "year": 2024,
            "revenue": 100.0,
            "net_profit_parent_company": 2.0,
            "cash_to_profit": 1.2,
            "cash_to_revenue": 1.05,
            "revenue_growth": 0.1,
            "inventory_growth": 0.05,
        },
        {
            "year": 2025,
            "revenue": 110.0,
            "net_profit_parent_company": 3.0,
            "cash_flow_from_operating_activities": -1.0,
            "cash_to_profit": -0.5,
            "cash_to_revenue": 0.7,
            "revenue_growth": 0.1,
            "net_profit_parent_company_growth": 0.5,
            "cash_flow_from_operating_activities_growth": -1.2,
            "inventory_growth": 0.2,
            "receivable_growth": 0.18,
            "gross_margin": 0.12,
            "free_cash_flow": -5.0,
        },
    ]
    checks = build_articulation_checks(metrics)
    themes = {item["theme"] for item in checks}
    assert "利润与经营现金流背离" in themes
    assert "收入收现比低于1" in themes
    assert "存货增速快于收入" in themes


def test_mda_crosswalk_links_statement_and_mda_text():
    mda = (
        "2025年营业收入179.49亿元，同比增长11.45%。"
        "但归母净利润为-3.53亿元，经营现金流净额18.81亿元，同比下降28.1%。"
        "存货余额65.95亿元，同比增长18.4%。"
    )
    analysis = {
        "metrics": [
            {"year": 2025, "revenue": 179.49, "net_profit_parent_company": -3.53, "cash_to_profit": -5.64, "cash_to_revenue": 0.95}
        ],
        "reviewed_signals": [
            {
                "title": "利润与经营现金流背离",
                "category": "earnings_quality",
                "category_cn": "利润质量",
                "evidence": "2025年净利润亏损",
                "explanation": "利润与现金流不一致",
            }
        ],
    }
    enriched = enrich_financial_analysis_with_mda(analysis, mda)
    crosswalk = enriched["mda_crosswalk"]
    assert crosswalk
    assert any(item.get("mda_hits") for item in crosswalk)
    md = format_crosswalk_markdown(crosswalk, limit=3)
    assert "报表事实" in md
    assert "MD&A 相关表述" in md


def test_annual_context_without_director_still_returns_structured_financial_analysis():
    annual = {
        "stock_code": "600000",
        "sec_name": "测试公司",
        "report_year": 2025,
        "title": "2025年年度报告",
        "mda_text": "公司营业收入增长，但经营现金流承压，应收账款增加。",
        "mda_meta": {},
        "financial_data": [
                {
                    "year": 2024,
                    "quarter": "2024q4",
                    "fields": {
                        "revenue": {"value": 100.0, "source": "rqdata"},
                        "net_profit_parent_company": {"value": 10.0, "source": "rqdata"},
                        "cash_flow_from_operating_activities": {"value": 8.0, "source": "rqdata"},
                },
            },
                {
                    "year": 2025,
                    "quarter": "2025q4",
                    "fields": {
                        "revenue": {"value": 120.0, "source": "rqdata"},
                        "net_profit_parent_company": {"value": 9.0, "source": "rqdata"},
                        "cash_flow_from_operating_activities": {"value": 4.0, "source": "rqdata"},
                },
            },
        ],
    }

    context = build_annual_context_from_store(annual, with_director=False)

    assert context is not None
    assert "_financial_analysis_raw" in context
    assert "investment_director" not in context
    assert "financial_years" in context
