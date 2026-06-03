from finagent.multiagent import DEFAULT_SECTIONS, TOOL_REGISTRY, _sanitize_plan, planner_agent
from finagent.multi_report import resolve_multi_report_title
from finagent.narrative_plan import (
    build_plan_data_briefing,
    infer_section_kind,
    is_operating_quality_section,
)
from finagent.plan_execution import sanitize_plan_sections


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
    fallback = {"objective": "x", "tools": list(TOOL_REGISTRY), "sections": DEFAULT_SECTIONS, "risk_controls": []}
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
        default_sections=DEFAULT_SECTIONS,
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
