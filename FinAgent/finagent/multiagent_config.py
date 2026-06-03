"""多智能体报告：工具注册表、因子候选与 legacy 章节模板（配置单一来源）。"""

from __future__ import annotations

from dataclasses import dataclass

from .chart_catalog import MARKET_TECH_SECTION
from .peer_analysis import PEER_FACTOR_CANDIDATES

OPERATING_QUALITY_SECTION = "经营质量分析"

TOOL_REGISTRY = {
    "get_price": "量价行情：open/high/low/close/volume/total_turnover",
    "get_price_change_rate": "日涨跌幅序列，用于收益率和波动分析",
    "get_turnover_rate": "换手率：today/week/month/year/current_year",
    "get_capital_flow": "资金流向：buy_volume/buy_value/sell_volume/sell_value",
    "get_factor": "估值、盈利、偿债、成长和分红因子：market_cap/pe/pb/ps/dividend_yield/margin/debt/liquidity/growth",
    "get_securities_margin": "融资融券：margin_balance/buy_on_margin_value/short_balance/total_balance",
    "get_dividend": "分红方案：现金分红、除权除息日、支付日、报告期",
    "get_shares": "股本结构：total/circulation_a/free_circulation 等",
    "get_instrument_industry": "中信一级行业归属，用于限定可比口径和行业背景",
    "is_suspended": "停牌状态检查",
    "is_st_stock": "ST 状态检查",
    "get_interbank_offered_rate": "Shibor 同业拆借利率，用作宏观流动性背景",
    "get_yield_curve": "中国收益率曲线，用作无风险利率和期限结构背景",
    "get_pit_financials_ex": "年报口径三表财务字段，复用 FinAgent 原有财务数据模块",
}

LEGACY_SECTION_TEMPLATES = [
    {"name": MARKET_TECH_SECTION, "agent": "market_tech_writer", "data": ["get_price", "get_price_change_rate", "get_turnover_rate"]},
    {"name": OPERATING_QUALITY_SECTION, "agent": "fundamental_writer", "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares"]},
    {"name": "资金与交易结构", "agent": "capital_flow_writer", "data": ["get_capital_flow", "get_securities_margin"]},
    {"name": "宏观利率背景", "agent": "macro_rate_writer", "data": ["get_interbank_offered_rate", "get_yield_curve"]},
    {"name": "综合风险与数据局限", "agent": "risk_synthesis_writer", "data": ["all_collected_data", "is_suspended", "is_st_stock"]},
]

FACTOR_CANDIDATES = [
    "market_cap",
    "pe_ratio_ttm",
    "pb_ratio_ttm",
    "ps_ratio_ttm",
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
    "dividend_yield_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "operating_revenue_growth_ratio_ttm",
    "account_receivable_turnover_rate_ttm",
    "current_asset_turnover_ttm",
    *PEER_FACTOR_CANDIDATES,
]


@dataclass
class MultiAgentOptions:
    stock: str
    as_of: str | None = None
    lookback_days: int = 260
    output: str | None = None
    workdir: str = "."
    use_cached_only: bool = False
    force_refresh: bool = False
