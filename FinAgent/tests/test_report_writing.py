from finagent.report_format import normalize_section_text
from finagent.report_writing import (
    FUNDAMENTAL_NARRATIVE_SECTION,
    build_analytical_evidence,
    section_writing_guide,
    summarize_annual_financial_data,
    summarize_pit_rows,
)


def test_build_analytical_evidence_includes_windows_and_margin():
    data = {
        "stock_code": "600519",
        "order_book_id": "600519.XSHG",
        "start_date": "2025-01-01",
        "end_date": "2026-05-29",
        "technical": {
            "latest_close": 1326.0,
            "ma20": 1333.39,
            "ma60": 1397.84,
            "return_20d": -0.0536,
            "rsi14": 41.04,
        },
        "price": {
            "rows": [
                {"date": "2026-05-20", "close": 1300.0, "volume": 100.0},
                {"date": "2026-05-29", "close": 1326.0, "volume": 764.78},
            ]
        },
        "securities_margin": {
            "rows": [
                {"date": "2026-05-13", "margin_balance": 19062000000, "buy_on_margin_value": 500000000},
                {"date": "2026-05-27", "margin_balance": 20126000000, "buy_on_margin_value": 1466000000},
            ]
        },
    }
    evidence = build_analytical_evidence(data, "量价与技术面")
    assert evidence["price_snapshot"]["vs_ma20_pct"] is not None
    assert evidence["price_windows"]["recent_daily"]
    assert evidence["margin_trajectory"]["peak_buy_on_margin_value"] == 1466000000


def test_summarize_pit_and_annual_rows():
    pit = summarize_pit_rows(
        [
            {"year": 2023, "quarter": "2023q4", "revenue": 140.5, "net_profit_parent_company": 3.67},
            {"year": 2024, "quarter": "2024q4", "revenue": 161.0, "net_profit_parent_company": 2.53},
        ]
    )
    assert len(pit) == 2
    assert pit[0]["revenue"] == 140.5

    annual = summarize_annual_financial_data(
        [
            {
                "year": 2025,
                "fields": {
                    "revenue": {"value": 179.49},
                    "net_profit_parent_company": {"value": -3.53},
                },
            }
        ]
    )
    assert annual[0]["revenue"] == 179.49


def test_section_writing_guide_is_loose_without_fixed_subheadings():
    guide = section_writing_guide("经营质量分析")
    assert "可选用" in guide
    assert "勿套用固定小节清单" in guide
    assert "同行横向坐标" in guide
    assert "MD&A" in guide
    assert "mda_crosswalk" in guide
    macro_guide = section_writing_guide("宏观利率背景")
    assert "macro_rate_brief" in macro_guide
    assert "MD&A" in macro_guide
    market_guide = section_writing_guide("量价与技术面", section_kind="market")
    assert "行业需求" in market_guide or "业务" in market_guide
    assert guide != macro_guide


def test_mda_business_writing_guide_by_kind():
    from finagent.report_writing import mda_business_writing_guide

    oq = mda_business_writing_guide("自定义经营节", section_kind="operating_quality")
    assert "mda_crosswalk" in oq
    val = mda_business_writing_guide("估值分析", section_kind="valuation")
    assert "基本业务" in val or "盈利驱动" in val


def test_normalize_section_text_strips_thinking_blocks():
    text = (
        "<think>内部推理不应出现</think>\n\n"
        "**核心结论**\n\n2025年营收179.49亿元。"
    )
    out = normalize_section_text(text, FUNDAMENTAL_NARRATIVE_SECTION)
    assert "redacted_thinking" not in out
    assert "179.49" in out


def test_ensure_section_lead_conclusion_prepends_core_line():
    from finagent.report_writing import ensure_section_lead_conclusion

    text = "**趋势概览**\n\n近20日股价累计下跌5.36%，显示短期动能不足。"
    out = ensure_section_lead_conclusion(text, "量价与技术面")
    assert out.startswith("**核心结论**")
    assert "5.36%" in out.split("\n\n")[1]


def test_render_multi_markdown_includes_executive_summary():
    from finagent.multi_report import render_multi_markdown

    md = render_multi_markdown(
        summary="贵州茅台短期承压但估值仍处历史中位，收盘1326元、近20日收益-5.36%、PE 20.04倍。",
        plan={"sections": [{"name": "量价与技术面"}]},
        data={
            "stock_code": "600519",
            "sec_name": "贵州茅台",
            "start_date": "2025-01-01",
            "end_date": "2026-05-29",
            "order_book_id": "600519.XSHG",
            "technical": {"latest_close": 1326},
            "factor": {"pe_ratio_ttm": 20.04},
        },
        charts={},
        sections={"量价与技术面": "**核心结论**\n\n近20日收益-5.36%，趋势偏弱。"},
    )
    assert "## 执行摘要" in md
    assert "1326" in md or "-5.36%" in md
    assert "## 核心指标速览" in md
