from finagent.chart_dynamic import local_chart_need
from finagent.multi_report import suggest_section_for_chart
from finagent.plan_execution import (
    catalog_key_for_plan_section,
    chart_candidates_for_plan_section,
    section_chart_limit_for_plan,
)
from finagent.visual_placement import local_visual_need


def _operating_quality_plan():
    return {
        "sections": [
            {
                "name": "盈利与现金流质量",
                "kind": "operating_quality",
                "agent": "mda_writer",
                "data": ["get_pit_financials_ex", "get_factor"],
            }
        ]
    }


def _capital_plan():
    return {
        "sections": [
            {
                "name": "北向与两融跟踪",
                "kind": "capital",
                "agent": "capital_flow_writer",
                "data": ["get_capital_flow", "get_securities_margin"],
            }
        ]
    }


def test_chart_candidates_follow_plan_kind_for_custom_section_name():
    plan = _operating_quality_plan()
    keys = chart_candidates_for_plan_section("盈利与现金流质量", plan)
    assert "revenue_profit_trend" in keys
    assert "profit_vs_cashflow" in keys
    assert "profitability_factors" in keys


def test_catalog_key_resolves_custom_name_via_kind():
    plan = _operating_quality_plan()
    assert catalog_key_for_plan_section("盈利与现金流质量", plan) == "经营质量分析"
    assert section_chart_limit_for_plan("盈利与现金流质量", plan) == 5


def test_chart_candidates_for_capital_custom_title():
    plan = _capital_plan()
    keys = chart_candidates_for_plan_section("北向与两融跟踪", plan)
    assert "margin_enhanced" in keys
    assert "capital_flow" in keys
    assert catalog_key_for_plan_section("北向与两融跟踪", plan) == "资金与交易结构"


def test_suggest_section_for_chart_uses_plan_candidates():
    plan = _capital_plan()
    sections = {"北向与两融跟踪": "融资余额与北向资金同步观察。"}
    assert suggest_section_for_chart("margin_enhanced", sections, plan=plan) == "北向与两融跟踪"


def test_local_visual_need_places_chart_in_custom_capital_section():
    plan = _capital_plan()
    sections = {
        "北向与两融跟踪": (
            "近两周融资余额持续攀升，两融杠杆维持高位；"
            "北向资金净流入扩大，买卖金额对比显示主动买盘占优。"
        )
    }
    data = {
        "securities_margin": {
            "rows": [{"date": "2026-05-29", "margin_balance": 1.2e10, "buy_on_margin_value": 5e8}],
            "row_count": 1,
        },
        "capital_flow": {"rows": [{"date": "2026-05-29", "net_inflow": 1e8}], "row_count": 1},
    }
    charts = {"margin_enhanced": "charts/margin_enhanced.png"}
    need = local_visual_need(data=data, sections=sections, charts=charts, plan=plan)
    matched = [
        item
        for item in need.get("visuals") or []
        if item.get("section") == "北向与两融跟踪" and item.get("visual_key") == "margin_enhanced"
    ]
    assert matched, need


def test_local_chart_need_respects_plan_kind_not_catalog_section_keys():
    plan = _capital_plan()
    sections = {
        "北向与两融跟踪": "融资融券余额抬升，融资买入额与融券卖出同步放大，杠杆资金活跃。"
    }
    data = {
        "securities_margin": {
            "rows": [{"date": "2026-05-29", "margin_balance": 1.2e10}],
            "row_count": 1,
        },
        "capital_flow": {"rows": [{"date": "2026-05-29", "net_inflow": 1e8}], "row_count": 1},
    }
    need = local_chart_need(data=data, sections=sections, plan=plan)
    picked = {item["chart_key"]: item["section"] for item in need.get("charts") or []}
    assert picked.get("margin_enhanced") == "北向与两融跟踪" or "capital_flow" in picked
