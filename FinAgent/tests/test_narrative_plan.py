from finagent.multiagent_config import LEGACY_SECTION_TEMPLATES, TOOL_REGISTRY
from finagent.multiagent import _sanitize_plan, planner_agent
from finagent.narrative_plan import build_planner_fallback_sections
from finagent.multi_report import resolve_multi_report_title
from finagent.narrative_plan import (
    build_plan_data_briefing,
    ensure_macro_section_in_plan,
    infer_section_kind,
    is_operating_quality_section,
    macro_data_available,
)
from finagent.plan_execution import sanitize_plan_sections


def test_build_plan_data_briefing_includes_macro_coverage():
    data = {
        "interbank_rate": {"row_count": 60, "rows": [{"date": "2026-05-29", "ON": 1.32}]},
        "yield_curve": {"row_count": 60, "rows": [{"date": "2026-05-29", "10Y": 1.74}]},
    }
    briefing = build_plan_data_briefing(data)
    assert briefing["data_coverage"]["interbank_rate"] == 60
    assert briefing["data_coverage"]["yield_curve"] == 60


def test_ensure_macro_section_in_plan_when_data_available():
    data = {
        "interbank_rate": {"rows": [{"date": "2026-05-29", "ON": 1.32}], "row_count": 1},
        "yield_curve": {"rows": [{"date": "2026-05-29", "10Y": 1.74}], "row_count": 1},
    }
    sections = [
        {"name": "量价与技术面", "agent": "market_tech_writer", "data": ["get_price"], "kind": "market"},
        {"name": "综合风险与数据局限", "agent": "risk_synthesis_writer", "data": ["all_collected_data"], "kind": "risk"},
    ]
    out = ensure_macro_section_in_plan(sections, data)
    names = [item["name"] for item in out]
    assert "宏观利率背景" in names
    assert names.index("宏观利率背景") < names.index("综合风险与数据局限")


def test_ensure_macro_section_skipped_without_data():
    sections = [{"name": "量价与技术面", "agent": "market_tech_writer", "data": ["get_price"], "kind": "market"}]
    out = ensure_macro_section_in_plan(sections, {"interbank_rate": {"rows": [], "row_count": 0}})
    assert [item["name"] for item in out] == ["量价与技术面"]


def test_sanitize_plan_injects_macro_when_llm_omits_it():
    llm_plan = {
        "report_title": "测试",
        "objective": "x",
        "tools": list(TOOL_REGISTRY),
        "sections": [
            {"name": "量价与技术面", "agent": "market_tech_writer", "data": ["get_price"], "kind": "market"},
            {"name": "综合风险与数据局限", "agent": "risk_synthesis_writer", "data": ["all_collected_data"], "kind": "risk"},
        ],
        "risk_controls": [],
    }
    fallback = {"objective": "x", "tools": list(TOOL_REGISTRY), "sections": [], "risk_controls": []}
    data = {
        "interbank_rate": {"rows": [{"date": "2026-05-29", "ON": 1.32}], "row_count": 1},
        "yield_curve": {"rows": [{"date": "2026-05-29", "10Y": 1.74}], "row_count": 1},
    }
    plan = _sanitize_plan(llm_plan, fallback, data=data)
    assert any(item["name"] == "宏观利率背景" for item in plan["sections"])


def test_build_plan_data_briefing_includes_technical_and_pit():
    data = {
        "stock_code": "300750",
        "sec_name": "宁德时代",
        "technical": {"latest_close": 200.5, "return_20d": 0.12, "return_60d": 0.18},
        "factor": {"pe_ratio_ttm": 22.3},
        "pit_financials": {
            "rows": [
                {"year": 2023, "revenue": 4000, "net_profit_parent_company": 440},
                {"year": 2024, "revenue": 3620, "net_profit_parent_company": 507},
            ]
        },
        "price": {"row_count": 120},
    }
    briefing = build_plan_data_briefing(data)
    assert briefing["stock_code"] == "300750"
    assert briefing["technical_highlights"]["latest_close"] == 200.5
    assert len(briefing["pit_summary"]) >= 1
    assert briefing["data_coverage"]["price"] == 120
    assert briefing.get("planning_guidance")
    assert briefing.get("optional_narrative_angles") == briefing.get("narrative_signals")


def test_is_operating_quality_by_kind_not_title():
    plan = {
        "sections": [
            {"name": "基本面与估值", "kind": "valuation", "data": ["get_factor"]},
            {"name": "盈利与现金流质量", "kind": "operating_quality", "data": ["get_pit_financials_ex"]},
        ]
    }
    assert not is_operating_quality_section("基本面与估值", plan)
    assert is_operating_quality_section("盈利与现金流质量", plan)


def test_infer_section_kind_from_title():
    assert infer_section_kind("量价与技术面") == "market"
    assert infer_section_kind("杠杆与资金面") == "capital"
    assert infer_section_kind("经营质量分析") == "operating_quality"


def test_sanitize_plan_preserves_report_title_and_kind():
    llm_plan = {
        "report_title": "300750 宁德时代：成长与估值再平衡",
        "narrative_thesis": "高景气赛道中的估值消化",
        "objective": "聚焦成长与估值",
        "tools": ["get_price"],
        "sections": [
            {
                "name": "趋势与资金",
                "agent": "market_writer",
                "data": ["get_price"],
                "kind": "market",
                "rationale": "20/60日收益分化",
            },
        ],
        "risk_controls": [],
    }
    fallback = {
        "objective": "x",
        "tools": list(TOOL_REGISTRY),
        "sections": build_planner_fallback_sections(None),
        "risk_controls": [],
    }
    plan = _sanitize_plan(llm_plan, fallback)
    assert plan["report_title"] == "300750 宁德时代：成长与估值再平衡"
    assert plan["narrative_thesis"] == "高景气赛道中的估值消化"
    assert plan["sections"][0]["kind"] == "market"


def test_resolve_multi_report_title_prefers_plan():
    title = resolve_multi_report_title(
        plan={"report_title": "600519 茅台：消费韧性观察"},
        stock_code="600519",
        sec_name="贵州茅台",
    )
    assert title == "600519 茅台：消费韧性观察"


def test_resolve_multi_report_title_prefixes_company_when_missing():
    title = resolve_multi_report_title(
        plan={"report_title": "成长与估值再平衡"},
        stock_code="300519",
        sec_name="新光药业",
    )
    assert title == "300519 新光药业：成长与估值再平衡"


def test_sanitize_plan_sections_keeps_rationale():
    plan = sanitize_plan_sections(
        {
            "sections": [
                {
                    "name": "产业链与竞争格局",
                    "agent": "writer",
                    "data": [],
                    "kind": "operating_quality",
                    "rationale": "PIT 显示毛利率改善",
                }
            ]
        },
        legacy_templates=LEGACY_SECTION_TEMPLATES,
        fallback_sections=[],
        allowed_tools=set(TOOL_REGISTRY),
    )
    assert plan[0]["kind"] == "operating_quality"
    assert "毛利率" in plan[0]["rationale"]


def test_planner_agent_without_api_key_uses_fallback():
    import os

    old = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = ""
    try:
        plan = planner_agent(
            stock_code="600519",
            order_book_id="600519.XSHG",
            as_of=__import__("datetime").date(2025, 5, 29),
            lookback_days=180,
            data={"stock_code": "600519", "technical": {"return_20d": 0.05}},
        )
        assert plan.get("sections")
    finally:
        if old is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = old
