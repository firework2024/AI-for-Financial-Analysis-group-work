"""数据采集与图表模板的单一注册表（避免 multiagent / chart_dynamic / data_capabilities 三处重复映射）。"""

from __future__ import annotations

from typing import Any

# 内部 data dict 键 → 米筐 TOOL_REGISTRY 工具名
DATA_KEY_TO_TOOL: dict[str, str] = {
    "price": "get_price",
    "price_change_rate": "get_price_change_rate",
    "turnover": "get_turnover_rate",
    "index_benchmark": "get_benchmark_index",
    "capital_flow": "get_capital_flow",
    "block_trade": "get_block_trade",
    "securities_margin": "get_securities_margin",
    "dividend": "get_dividend",
    "shares": "get_shares",
    "suspended": "is_suspended",
    "st_stock": "is_st_stock",
    "industry": "get_instrument_industry",
    "industry_l2": "get_instrument_industry(level=2)",
    "interbank_rate": "get_interbank_offered_rate",
    "yield_curve": "get_yield_curve",
    "factor": "get_factor(latest)",
    "factor_history": "get_factor(history)",
    "pit_financials": "get_pit_financials_ex",
}

COLLECTED_SERIES: dict[str, str] = {
    "price": "行情",
    "price_change_rate": "日涨跌幅",
    "index_benchmark": "基准指数",
    "turnover": "换手率",
    "capital_flow": "资金流向",
    "block_trade": "大宗交易",
    "securities_margin": "两融",
    "factor_history": "因子历史",
    "pit_financials": "年报三表",
    "dividend": "分红",
    "shares": "股本",
    "interbank_rate": "Shibor",
    "yield_curve": "收益率曲线",
}

# 参数化出图 / codegen 可用的 data_keys（与 data dict 键一致）
PARAMETRIC_DATA_KEYS: tuple[str, ...] = (
    "price",
    "price_change_rate",
    "index_benchmark",
    "turnover",
    "capital_flow",
    "block_trade",
    "securities_margin",
    "factor_history",
    "interbank_rate",
    "yield_curve",
    "dividend",
    "shares",
)

DATA_KEY_TO_ROWS: dict[str, str] = {key: key for key in PARAMETRIC_DATA_KEYS}

# 固定模板 chart_key → 依赖的 data dict 键
CHART_DATA_SOURCE: dict[str, str] = {
    "price_volume": "price",
    "moving_averages": "price",
    "nav_curve": "price",
    "cumulative_return": "price",
    "drawdown": "price",
    "technical_indicators": "price",
    "daily_return": "price_change_rate",
    "rolling_volatility": "price",
    "relative_return": "index_benchmark",
    "turnover_rate": "turnover",
    "turnover_amount": "price",
    "capital_flow": "capital_flow",
    "cumulative_capital_flow": "capital_flow",
    "buy_sell_value": "capital_flow",
    "block_trade_activity": "block_trade",
    "margin_balances": "securities_margin",
    "margin_activity": "securities_margin",
    "valuation_factors": "factor_history",
    "market_cap_trend": "factor_history",
    "profitability_factors": "factor_history",
    "growth_factors": "factor_history",
    "liquidity_factors": "factor_history",
    "debt_ratio_trend": "factor_history",
    "dividend_history": "dividend",
    "share_structure": "shares",
    "shibor_rates": "interbank_rate",
    "gov_yield_trend": "yield_curve",
    "yield_curve_snapshot": "yield_curve",
    "latest_valuation_snapshot": "factor",
    "latest_quality_snapshot": "factor",
    "latest_liquidity_snapshot": "factor",
    "latest_growth_snapshot": "factor",
    "margin_enhanced": "securities_margin",
    "valuation_percentile": "factor_history",
    "share_structure_pie": "shares",
    "dividend_spread": "yield_curve",
}


def tool_for_data_key(key: str) -> str:
    return DATA_KEY_TO_TOOL.get(key, key)


def benchmark_index_id(order_book_id: str) -> tuple[str, str]:
    """按标的板块选择可比基准指数 (id, 简称)。"""
    code = order_book_id.split(".")[0] if "." in order_book_id else order_book_id
    exchange = order_book_id.split(".")[-1] if "." in order_book_id else "XSHG"
    if code.startswith("688"):
        return "000688.XSHG", "科创50"
    if code.startswith("300"):
        return "399006.XSHE", "创业板指"
    if exchange == "XSHE":
        return "399001.XSHE", "深证成指"
    return "000300.XSHG", "沪深300"


def data_available_for_chart(chart_key: str, data: dict[str, Any]) -> bool:
    data_key = CHART_DATA_SOURCE.get(chart_key)
    if not data_key:
        return True
    value = data.get(data_key)
    if chart_key.startswith("latest_"):
        return isinstance(value, dict) and bool(value)
    if chart_key == "relative_return":
        price_ok = isinstance(data.get("price"), dict) and int(data.get("price", {}).get("row_count") or 0) > 0
        index_ok = isinstance(value, dict) and int(value.get("row_count") or 0) > 0
        return price_ok and index_ok
    return isinstance(value, dict) and int(value.get("row_count") or 0) > 0
