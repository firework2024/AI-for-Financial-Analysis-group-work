from finagent.multiagent import DEFAULT_SECTIONS, TOOL_REGISTRY, _sanitize_plan
from finagent.plan_execution import (
    chart_candidates_for_section,
    chart_keys_for_plan,
    filter_prompt_payload,
    infer_section_tools_from_title,
    plan_collect_tools,
    plan_fetch_keys,
    plan_needs_pit_financials,
    sanitize_plan_sections,
)

ALLOWED = frozenset(TOOL_REGISTRY)


def test_sanitize_plan_preserves_custom_section_order_without_default_fill():
    llm_plan = {
        "objective": "聚焦资金流",
        "tools": ["get_capital_flow", "get_securities_margin"],
        "sections": [
            {
                "name": "资金与交易结构",
                "agent": "capital_flow_writer",
                "data": ["get_capital_flow", "get_securities_margin"],
            },
            {
                "name": "量价与技术面",
                "agent": "market_tech_writer",
                "data": ["get_price"],
            },
        ],
        "risk_controls": ["不写买卖建议"],
    }
    fallback = {"objective": "x", "tools": list(TOOL_REGISTRY), "sections": DEFAULT_SECTIONS, "risk_controls": []}
    plan = _sanitize_plan(llm_plan, fallback)
    names = [item["name"] for item in plan["sections"]]
    assert names == ["资金与交易结构", "量价与技术面"]
    assert "基本面与估值" not in names


def test_sanitize_plan_infers_tools_for_custom_title():
    plan = sanitize_plan_sections(
        {"sections": [{"name": "产业链与竞争格局", "agent": "writer", "data": []}]},
        default_sections=DEFAULT_SECTIONS,
        allowed_tools=ALLOWED,
    )
    custom = plan[0]
    assert custom["name"] == "产业链与竞争格局"
    assert "get_factor" in custom["data"]


def test_chart_candidates_for_custom_title():
    keys = chart_candidates_for_section("产业链盈利与估值对比", ["get_factor"])
    assert "valuation_factors" in keys
    assert "profitability_factors" in keys


def test_infer_section_tools_from_title():
    tools = infer_section_tools_from_title("北向资金与两融观察")
    assert "get_capital_flow" in tools
    assert "get_securities_margin" in tools


def test_plan_fetch_keys_follows_section_data():
    plan = {
        "tools": [],
        "sections": [
            {"name": "宏观利率背景", "agent": "macro_rate_writer", "data": ["get_interbank_offered_rate"]},
        ],
    }
    keys = plan_fetch_keys(plan, allowed_tools=ALLOWED)
    assert keys == frozenset({"interbank_rate"})
    assert "price" not in keys


def test_plan_collect_tools_unions_plan_and_sections():
    plan = {
        "tools": ["get_price"],
        "sections": [{"name": "x", "agent": "a", "data": ["get_factor"]}],
    }
    tools = plan_collect_tools(plan, allowed_tools=ALLOWED)
    assert tools == {"get_price", "get_factor"}


def test_filter_prompt_payload_respects_section_tools():
    payload = {
        "section_name": "资金与交易结构",
        "order_book_id": "688041.XSHG",
        "capital_flow": {"recent_rows": [1]},
        "price_recent": [2],
        "factor": {"pe_ratio_ttm": 20},
    }
    filtered = filter_prompt_payload(payload, ["get_capital_flow"])
    assert "capital_flow" in filtered
    assert "price_recent" not in filtered
    assert "factor" not in filtered


def test_chart_keys_for_plan_maps_tools_and_sections():
    plan = {
        "tools": [],
        "sections": [
            {"name": "杠杆与资金面", "agent": "capital_flow_writer", "data": ["get_securities_margin"]},
        ],
    }
    keys = chart_keys_for_plan(plan, allowed_tools=ALLOWED)
    assert keys is not None
    assert "margin_enhanced" in keys


def test_plan_needs_pit_only_when_requested():
    assert plan_needs_pit_financials(None, allowed_tools=ALLOWED)
    assert plan_needs_pit_financials(
        {"sections": [{"name": "x", "data": ["get_pit_financials_ex"]}]},
        allowed_tools=ALLOWED,
    )
    assert not plan_needs_pit_financials(
        {"sections": [{"name": "x", "data": ["get_price"]}]},
        allowed_tools=ALLOWED,
    )


def test_sanitize_plan_strips_unknown_tools_from_section_data():
    plan = sanitize_plan_sections(
        {"sections": [{"name": "测试节", "agent": "writer", "data": ["get_price", "wind_news"]}]},
        default_sections=DEFAULT_SECTIONS,
        allowed_tools=ALLOWED,
    )
    custom = next(item for item in plan if item["name"] == "测试节")
    assert custom["data"] == ["get_price"]
