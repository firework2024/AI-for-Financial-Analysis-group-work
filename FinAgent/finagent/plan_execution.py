"""多智能体报告：将 planner 输出的 tools/sections.data 落到采数、写作与出图。"""

from __future__ import annotations

from typing import Any

from .chart_catalog import DEFAULT_SECTION_CHART_CANDIDATES, MARKET_TECH_SECTION

# 米筐工具名 → data_executor 内部并行任务键
TOOL_TO_FETCH_KEYS: dict[str, tuple[str, ...]] = {
    "get_price": ("price",),
    "get_price_change_rate": ("price_change",),
    "get_turnover_rate": ("turnover",),
    "get_capital_flow": ("capital",),
    "get_factor": ("factor", "factor_history"),
    "get_securities_margin": ("margin",),
    "get_dividend": ("dividend",),
    "get_shares": ("shares",),
    "get_instrument_industry": ("industry",),
    "is_suspended": ("suspended",),
    "is_st_stock": ("st_stock",),
    "get_interbank_offered_rate": ("interbank_rate",),
    "get_yield_curve": ("yield_curve",),
}

ALL_FETCH_KEYS: frozenset[str] = frozenset(key for keys in TOOL_TO_FETCH_KEYS.values() for key in keys)

# 工具名 → 写作 prompt 中允许出现的 data 字段（None 表示不裁剪）
TOOL_PROMPT_FIELDS: dict[str, tuple[str, ...] | None] = {
    "get_price": ("price_recent", "technical"),
    "get_price_change_rate": ("price_change_rate_recent",),
    "get_turnover_rate": ("turnover_recent",),
    "get_capital_flow": ("capital_flow",),
    "get_securities_margin": ("securities_margin_recent",),
    "get_factor": ("factor", "factor_history_recent", "industry"),
    "get_dividend": ("dividend_recent",),
    "get_shares": ("shares_recent",),
    "get_instrument_industry": ("industry",),
    "is_suspended": ("status_checks",),
    "is_st_stock": ("status_checks",),
    "get_interbank_offered_rate": ("macro_rate_recent",),
    "get_yield_curve": ("macro_rate_recent",),
    "get_pit_financials_ex": ("pit_financials", "annual_report_context", "mda_crosswalk", "articulation_checks"),
    "all_collected_data": None,
}

PROMPT_ALWAYS_FIELDS = frozenset(
    {
        "section_name",
        "order_book_id",
        "sec_name",
        "date_range",
        "charts",
        "analytical_evidence",
    }
)

TOOL_CHART_KEYS: dict[str, tuple[str, ...]] = {
    "get_price": (
        "price_volume",
        "moving_averages",
        "cumulative_return",
        "drawdown",
        "rolling_volatility",
        "technical_indicators",
        "turnover_amount",
        "nav_curve",
    ),
    "get_price_change_rate": ("daily_return", "cumulative_return", "relative_return"),
    "get_turnover_rate": ("turnover_rate", "turnover_amount"),
    "get_capital_flow": ("capital_flow", "cumulative_capital_flow", "buy_sell_value"),
    "get_securities_margin": ("margin_enhanced", "margin_balances", "margin_activity"),
    "get_factor": (
        "valuation_factors",
        "valuation_percentile",
        "profitability_factors",
        "growth_factors",
        "liquidity_factors",
        "debt_ratio_trend",
        "market_cap_trend",
        "latest_valuation_snapshot",
        "latest_quality_snapshot",
        "latest_liquidity_snapshot",
        "latest_growth_snapshot",
    ),
    "get_dividend": ("dividend_history", "dividend_spread"),
    "get_shares": ("share_structure", "share_structure_pie"),
    "get_interbank_offered_rate": ("shibor_rates",),
    "get_yield_curve": ("gov_yield_trend", "yield_curve_snapshot"),
}

# 自定义章节标题关键词 → 图表候选（与 DEFAULT_SECTION_CHART_CANDIDATES 对齐）
_TITLE_CHART_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("量价", "技术面", "技术因素", "趋势", "K线", "均线"), DEFAULT_SECTION_CHART_CANDIDATES.get(MARKET_TECH_SECTION, ())),
    (("资金", "两融", "融资", "融券", "北向", "成交"), DEFAULT_SECTION_CHART_CANDIDATES.get("资金与交易结构", ())),
    (("基本面", "估值", "盈利", "财务", "股息", "产业", "竞争"), DEFAULT_SECTION_CHART_CANDIDATES.get("基本面与估值", ())),
    (("宏观", "利率", "Shibor", "国债", "yield", "曲线"), DEFAULT_SECTION_CHART_CANDIDATES.get("宏观利率背景", ())),
    (("风险", "局限", "ST", "停牌"), ("latest_liquidity_snapshot",)),
)

# 标题关键词 → 建议 data 工具（LLM 未写 data 时的兜底）
_TITLE_TOOL_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("量价", "技术面", "技术", "趋势"), ("get_price", "get_price_change_rate", "get_turnover_rate")),
    (("资金", "两融", "融资", "融券"), ("get_capital_flow", "get_securities_margin")),
    (("基本面", "估值", "盈利", "财务", "产业", "竞争"), ("get_factor", "get_pit_financials_ex", "get_dividend", "get_shares")),
    (("宏观", "利率", "Shibor", "国债"), ("get_interbank_offered_rate", "get_yield_curve")),
    (("风险", "局限"), ("all_collected_data", "is_suspended", "is_st_stock")),
)


def section_tools_from_plan(plan: dict[str, Any] | None, section_name: str) -> list[str]:
    if not plan:
        return []
    for spec in plan.get("sections") or []:
        if isinstance(spec, dict) and str(spec.get("name") or "") == section_name:
            return [str(item) for item in (spec.get("data") or []) if isinstance(item, str)]
    return []


def infer_section_tools_from_title(section_name: str) -> list[str]:
    tools: list[str] = []
    seen: set[str] = set()
    for keywords, candidates in _TITLE_TOOL_KEYWORDS:
        if any(token in section_name for token in keywords):
            for tool in candidates:
                if tool not in seen:
                    seen.add(tool)
                    tools.append(tool)
    return tools


def chart_candidates_for_section(section_name: str, section_tools: list[str] | None = None) -> tuple[str, ...]:
    """精确节名、标题关键词、本节 data 工具 → 图表候选（多智能体出图/插图共用）。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(*names: str) -> None:
        for name in names:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)

    if section_name in DEFAULT_SECTION_CHART_CANDIDATES:
        add(*DEFAULT_SECTION_CHART_CANDIDATES[section_name])
    for keywords, candidates in _TITLE_CHART_KEYWORDS:
        if any(token in section_name for token in keywords):
            add(*candidates)
    for tool in section_tools or ():
        add(*TOOL_CHART_KEYS.get(tool, ()))
    return tuple(ordered)


def plan_collect_tools(plan: dict[str, Any], *, allowed_tools: set[str]) -> set[str]:
    allowed = set(allowed_tools) | {"all_collected_data"}
    tools: set[str] = set()
    for name in plan.get("tools") or []:
        if isinstance(name, str) and name in allowed:
            tools.add(name)
    for spec in plan.get("sections") or []:
        if not isinstance(spec, dict):
            continue
        for name in spec.get("data") or []:
            if isinstance(name, str) and name in allowed:
                tools.add(name)
    return tools


def plan_fetch_keys(plan: dict[str, Any] | None, *, allowed_tools: set[str]) -> frozenset[str]:
    if not plan:
        return ALL_FETCH_KEYS
    tools = plan_collect_tools(plan, allowed_tools=allowed_tools)
    if not tools:
        tools = set(allowed_tools)
    if "all_collected_data" in tools:
        return ALL_FETCH_KEYS
    keys: set[str] = set()
    for tool in tools:
        if tool == "get_pit_financials_ex":
            continue
        keys.update(TOOL_TO_FETCH_KEYS.get(tool, ()))
    if "price_change" in keys:
        keys.add("price")
    return frozenset(keys)


def plan_needs_pit_financials(plan: dict[str, Any] | None, *, allowed_tools: set[str]) -> bool:
    if not plan:
        return True
    tools = plan_collect_tools(plan, allowed_tools=allowed_tools)
    return "all_collected_data" in tools or "get_pit_financials_ex" in tools


def sanitize_plan_sections(
    plan: dict[str, Any],
    *,
    default_sections: list[dict[str, Any]],
    allowed_tools: set[str],
) -> list[dict[str, Any]]:
    """保留 LLM 规划的章节数与顺序；仅校验工具白名单，不强制补默认五节。"""
    allowed = set(allowed_tools) | {"all_collected_data"}
    default_by_name = {str(item["name"]): item for item in default_sections}
    default_agents = {str(item["name"]): str(item.get("agent") or "section_writer") for item in default_sections}

    raw = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for spec in raw:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "").strip()
        if not name or name in seen:
            continue
        default = default_by_name.get(name)
        agent = str(spec.get("agent") or default_agents.get(name) or "section_writer").strip()
        data = [str(item) for item in (spec.get("data") or []) if isinstance(item, str) and item in allowed]
        if not data and default:
            data = list(default.get("data") or [])
        if not data:
            data = infer_section_tools_from_title(name)
        sanitized.append({"name": name, "agent": agent, "data": data})
        seen.add(name)

    return sanitized or [dict(item) for item in default_sections]


def filter_prompt_payload(payload: dict[str, Any], section_tools: list[str] | None) -> dict[str, Any]:
    if not section_tools or "all_collected_data" in section_tools:
        return payload
    allowed = set(PROMPT_ALWAYS_FIELDS)
    for tool in section_tools:
        fields = TOOL_PROMPT_FIELDS.get(tool)
        if fields is None:
            return payload
        allowed.update(fields)
    return {key: value for key, value in payload.items() if key in allowed}


def chart_keys_for_plan(plan: dict[str, Any] | None, *, allowed_tools: set[str]) -> set[str] | None:
    if not plan:
        return None
    tools = plan_collect_tools(plan, allowed_tools=allowed_tools)
    if "all_collected_data" in tools:
        return None
    keys: set[str] = set()
    for spec in plan.get("sections") or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "")
        section_tools = [str(item) for item in (spec.get("data") or []) if isinstance(item, str)]
        keys.update(chart_candidates_for_section(name, section_tools))
    return keys or None
