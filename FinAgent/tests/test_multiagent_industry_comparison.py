from finagent.multiagent_config import LEGACY_SECTION_TEMPLATES
from finagent.multiagent_data import ensure_technical_from_price_rows
from finagent.section_prompts import compact_data_for_prompt
from finagent.section_validation import local_validation


def _comparison():
    return {
        "industry": {
            "level1_name": "建筑",
            "level2_name": "专业工程",
            "level3_name": "工程服务",
            "selected_level": 3,
            "selected_industry_name": "工程服务",
        },
        "peers": {"effective_count": 6, "candidate_count": 9},
        "metrics": {
            "pe_ratio_ttm": {
                "label": "PE(TTM)",
                "target": 28.0,
                "mean": 18.0,
                "median": 16.0,
                "p25": 12.0,
                "p75": 22.0,
                "percentile": 0.83,
                "relative_label": "处于行业高位，相对不利",
                "valid_count": 6,
            },
            "gross_profit_margin_ttm": {
                "label": "毛利率(TTM)",
                "target": 0.25,
                "mean": 0.18,
                "median": 0.17,
                "p25": 0.12,
                "p75": 0.21,
                "percentile": 0.91,
                "relative_label": "处于行业高位，相对占优",
                "valid_count": 6,
            },
        },
        "relative_signals": [],
        "cluster_anomalies": {
            "method": "DBSCAN",
            "status": "skipped",
            "reason": "有效同行少于 8 家，跳过 DBSCAN。",
        },
        "data_notes": ["有效同行少于 8 家，跳过 DBSCAN。"],
    }


def test_legacy_section_templates_include_operating_quality():
    names = [item["name"] for item in LEGACY_SECTION_TEMPLATES]

    assert "经营质量分析" in names
    assert "基本面与估值" not in names


def test_industry_prompt_brief_guides_writer_without_raw_paths():
    payload = compact_data_for_prompt(
        {"industry_comparison": _comparison()},
        {},
        "经营质量分析",
    )
    brief = payload["industry_comparison_brief"]

    assert "工程服务" in brief
    assert "有效同行 6 家" in brief
    assert "表·同行横向坐标" in brief
    assert "毛利率(TTM)" not in brief
    assert "PE(TTM)" not in brief
    assert "factor_trend" not in brief
    assert "data." not in brief


def test_operating_quality_brief_omits_metric_bullet_list():
    payload = compact_data_for_prompt(
        {"industry_comparison": _comparison()},
        {},
        "经营质量分析",
    )
    brief = payload["industry_comparison_brief"]

    assert "表·同行横向坐标" in brief
    assert "毛利率(TTM)：目标公司" not in brief


def test_prompt_compaction_exposes_compact_industry_summary_only():
    payload = compact_data_for_prompt(
        {
            "industry_comparison": _comparison(),
            "factor": {"pe_ratio_ttm": 28.0, "gross_profit_margin_ttm": 0.25, "dividend_yield_ttm": 0.01},
            "factor_history": {
                "rows": [
                    {"date": "2026-01-01", "pe_ratio_ttm": 28.0, "gross_profit_margin_ttm": 0.25, "dividend_yield_ttm": 0.01}
                ]
            },
            "annual_analysis": {"fundamental_narrative": "不应传入", "financial_analysis": {"reviewed_signals": ["信号"]}},
        },
        {
            "industry_valuation_compare": "charts/industry_valuation_compare.png",
            "industry_profitability_compare": "charts/industry_profitability_compare.png",
            "valuation_factors": "charts/valuation_factors.png",
        },
        "经营质量分析",
    )

    assert payload["industry_comparison"]["industry"]["selected_industry_name"] == "工程服务"
    assert payload["industry_comparison"]["metric_rows"][0]["metric"] == "gross_profit_margin_ttm"
    assert "同行池口径" in payload["industry_comparison_brief"]
    assert "metrics" not in payload["industry_comparison"]
    assert "pe_ratio_ttm" not in payload["factor"]
    assert "dividend_yield_ttm" not in payload["factor"]
    assert "pe_ratio_ttm" not in payload["factor_history_recent"][0]
    assert "fundamental_narrative_analysis" not in payload
    assert "industry_valuation_compare" not in payload["charts"]
    assert "valuation_factors" not in payload["charts"]
    assert "industry_profitability_compare" not in payload["charts"]
    assert "industry_growth_leverage_compare" not in payload["charts"]


def test_local_validation_requests_rewrite_when_fundamental_omits_peer_comparison():
    validation = local_validation(
        data={"industry_comparison": _comparison()},
        charts={"industry_profitability_compare": "charts/industry_profitability_compare.png"},
        sections={"经营质量分析": "盈利能力改善，现金流质量需要结合利润表现观察。"},
        draft_markdown="盈利能力改善，现金流质量需要结合利润表现观察。",
    )

    assert validation["final_decision"] == "revise"
    assert "经营质量分析" in validation["section_feedback"]
    assert any("同行" in item for item in validation["section_feedback"]["经营质量分析"])


def test_local_validation_passes_when_fundamental_uses_peer_comparison():
    validation = local_validation(
        data={"industry_comparison": _comparison()},
        charts={
            "industry_dbscan_anomaly": "charts/industry_dbscan_anomaly.png",
            "price_volume": "charts/price_volume.png",
        },
        sections={
            "经营质量分析": (
                "**核心结论**\n\n同行池工程服务有效6家，经营质量全面占优。\n\n"
                "**同行横向坐标**\n\n毛利率与偿债指标整体处于行业高位；DBSCAN因样本不足跳过。"
            )
        },
        draft_markdown="同行横向坐标 经营质量全面占优",
    )

    assert "经营质量分析" not in validation["section_feedback"]


def test_local_validation_flags_prose_peer_metric_list():
    validation = local_validation(
        data={"industry_comparison": _comparison()},
        charts={"industry_dbscan_anomaly": "charts/industry_dbscan_anomaly.png"},
        sections={
            "经营质量分析": (
                "**同行横向坐标**\n\n"
                "毛利率(TTM)：26.21%，行业中位数15.99%，行业分位91%。\n"
                "净利率(TTM)：18.09%，行业中位数3.17%，行业分位97%。"
            )
        },
        draft_markdown="",
    )

    notes = validation["section_feedback"].get("经营质量分析", [])
    assert any("机械表" in note or "逐条" in note for note in notes)


def test_local_validation_rejects_valuation_language_in_operating_quality():
    validation = local_validation(
        data={"industry_comparison": _comparison()},
        charts={"industry_profitability_compare": "charts/industry_profitability_compare.png"},
        sections={
            "经营质量分析": "同行池采用中信三级行业工程服务，有效同行6家；毛利率处于行业分位91%，高于行业中位数。PE估值分位偏高。DBSCAN因样本不足跳过。"
        },
        draft_markdown="同行池采用中信三级行业工程服务，有效同行6家；毛利率处于行业分位91%，高于行业中位数。PE估值分位偏高。DBSCAN因样本不足跳过。",
    )

    assert any("PE/PB/PS" in item for item in validation["section_feedback"]["经营质量分析"])


def test_cached_payload_recomputes_technical_when_price_history_is_sufficient():
    rows = [{"date": f"2026-01-{i:02d}", "close": float(i), "volume": float(1000 + i)} for i in range(1, 70)]
    payload = {
        "price": {"rows": rows, "row_count": len(rows)},
        "technical": {"latest_close": 69.0},
    }

    ensure_technical_from_price_rows(payload)

    technical = payload.get("technical") or {}
    assert technical.get("latest_close") == 69.0
    assert technical.get("ma20") is not None
    assert technical.get("ma60") is not None
    assert technical.get("return_20d") is not None
    assert technical.get("return_60d") is not None
    assert technical.get("rsi14") is not None
