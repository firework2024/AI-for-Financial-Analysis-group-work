"""图表 catalog：caption / 关键词 / 图注 / 章节候选（单一来源）。"""

from __future__ import annotations

from typing import Any

CHART_INTERPRETATION_SECTION = "图表解读"
MARKET_TECH_SECTION = "量价与技术面"
SYNTHESIS_SECTION = "综合判断"
RISK_SECTION = "综合风险"
DATA_LIMITATIONS_SECTION = "数据覆盖与局限"

DEFERRED_SECTIONS = frozenset(
    {
        CHART_INTERPRETATION_SECTION,
        SYNTHESIS_SECTION,
        DATA_LIMITATIONS_SECTION,
    }
)

CHART_CAPTIONS: dict[str, str] = {
    "price_volume": "收盘价与成交量",
    "moving_averages": "收盘价与 MA20/MA60",
    "cumulative_return": "累计收益率",
    "nav_curve": "净值曲线",
    "drawdown": "回撤曲线",
    "technical_indicators": "RSI 与 MACD",
    "daily_return": "日涨跌幅",
    "rolling_volatility": "20 日滚动波动率",
    "relative_return": "相对基准强弱",
    "turnover_rate": "换手率",
    "turnover_amount": "成交额",
    "capital_flow": "日度净流入",
    "cumulative_capital_flow": "累计净流入",
    "buy_sell_value": "买卖金额对比",
    "block_trade_activity": "大宗交易成交额",
    "margin_balances": "融资融券余额",
    "margin_activity": "融资买入与融券卖出",
    "valuation_factors": "估值因子走势",
    "market_cap_trend": "总市值走势",
    "profitability_factors": "盈利能力因子",
    "growth_factors": "成长因子走势",
    "liquidity_factors": "流动性比率",
    "debt_ratio_trend": "资产负债率走势",
    "dividend_history": "分红历史",
    "share_structure": "股本结构",
    "shibor_rates": "Shibor 利率",
    "yield_curve_snapshot": "收益率曲线快照",
    "latest_valuation_snapshot": "最新估值快照",
    "latest_quality_snapshot": "最新质量因子快照",
    "latest_liquidity_snapshot": "最新偿债与流动性快照",
    "latest_growth_snapshot": "最新成长因子快照",
}

CHART_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    (
        "价格与趋势",
        (
            "nav_curve",
            "price_volume",
            "moving_averages",
            "cumulative_return",
            "relative_return",
            "drawdown",
            "technical_indicators",
            "daily_return",
            "rolling_volatility",
            "turnover_rate",
            "turnover_amount",
        ),
    ),
    (
        "资金与两融",
        (
            "capital_flow",
            "cumulative_capital_flow",
            "buy_sell_value",
            "block_trade_activity",
            "margin_balances",
            "margin_activity",
        ),
    ),
    (
        "估值与结构",
        (
            "valuation_factors",
            "market_cap_trend",
            "profitability_factors",
            "growth_factors",
            "liquidity_factors",
            "debt_ratio_trend",
            "dividend_history",
            "share_structure",
            "latest_valuation_snapshot",
            "latest_quality_snapshot",
            "latest_liquidity_snapshot",
            "latest_growth_snapshot",
        ),
    ),
    ("宏观利率", ("shibor_rates", "yield_curve_snapshot")),
]

CHART_SUBHEADING_HINTS: dict[str, tuple[str, ...]] = {
    "nav_curve": ("价格走势", "净值", "收盘价", "价格", "表现", "近期"),
    "price_volume": ("成交量", "量价", "换手"),
    "moving_averages": ("均线", "MA20", "MA60", "趋势"),
    "turnover_rate": ("换手",),
    "turnover_amount": ("成交额", "成交金额", "量价"),
    "cumulative_return": ("累计收益", "收益率", "区间收益"),
    "relative_return": ("相对", "基准", "超额", "强弱", "沪深300", "指数对比"),
    "daily_return": ("日涨跌幅", "波动", "单日"),
    "rolling_volatility": ("波动率", "波动", "风险"),
    "drawdown": ("回撤", "最大回撤", "下行", "跌幅"),
    "technical_indicators": ("RSI", "MACD", "动量", "技术指标"),
    "capital_flow": ("净流入", "资金流向", "买卖"),
    "cumulative_capital_flow": ("累计净流入", "累计资金"),
    "buy_sell_value": ("买入", "卖出", "买卖金额"),
    "block_trade_activity": ("大宗", "大宗交易", "折价"),
    "margin_balances": ("融资余额", "融券余额", "两融余额"),
    "margin_activity": ("融资买入", "融券卖出", "两融交易"),
    "valuation_factors": ("估值", "PE", "PB", "PS"),
    "market_cap_trend": ("市值", "总市值"),
    "profitability_factors": ("盈利", "毛利率", "净利率", "ROE"),
    "growth_factors": ("增长", "成长", "营收", "利润增速"),
    "liquidity_factors": ("流动比率", "速动", "流动性"),
    "debt_ratio_trend": ("负债", "资产负债率", "杠杆"),
    "dividend_history": ("分红", "股息"),
    "share_structure": ("股本", "流通", "总股本"),
    "shibor_rates": ("Shibor", "同业", "短期资金"),
    "yield_curve_snapshot": ("收益率曲线", "国债", "无风险"),
    "latest_valuation_snapshot": ("估值快照", "市值"),
    "latest_quality_snapshot": ("质量因子", "偿债", "盈利能力"),
    "latest_growth_snapshot": ("成长因子", "增长", "增速"),
}

CHART_BRIEF_NOTES: dict[str, str] = {
    "nav_curve": "区间净值走势（期初=1），便于对照价格趋势叙述。",
    "cumulative_return": "区间内累计收益，可与正文收益率表述对照。",
    "relative_return": "标的与基准指数归一化净值对比，观察相对强弱。",
    "daily_return": "日度涨跌幅柱状图，反映短期波动节奏。",
    "rolling_volatility": "20 日滚动年化波动率，衡量区间风险水平。",
    "turnover_amount": "日成交额走势，辅助量价分析。",
    "drawdown": "价格回撤幅度，反映区间风险暴露。",
    "technical_indicators": "RSI/MACD 等动量与超买超卖参考。",
    "capital_flow": "日度买卖净流入，反映短期资金方向。",
    "cumulative_capital_flow": "累计净流入趋势，观察资金持续性。",
    "buy_sell_value": "买卖金额对比，辅助判断交易结构。",
    "block_trade_activity": "大宗交易成交额，反映机构/大额交易活跃度。",
    "market_cap_trend": "总市值时间序列，观察规模变化。",
    "profitability_factors": "毛利率、净利率、ROE 等盈利质量因子走势（已换算为 %）。",
    "growth_factors": "利润与营收增长因子，观察成长性变化（已换算为 %）。",
    "liquidity_factors": "流动比率与速动比率，观察短期偿债能力。",
    "debt_ratio_trend": "资产负债率时间序列（米筐返回百分数点）。",
    "latest_valuation_snapshot": "最新估值因子横截面，注意量纲差异。",
    "latest_quality_snapshot": "盈利与偿债类因子快照。",
    "latest_liquidity_snapshot": "偿债与流动性因子快照。",
    "latest_growth_snapshot": "成长类因子快照，可与正文增长表述对照。",
    "shibor_rates": "利率环境变化会影响权益资产折现率与相对吸引力。",
    "yield_curve_snapshot": "利率环境变化会影响权益资产折现率与相对吸引力。",
}

DEFAULT_SECTION_CHART_CANDIDATES: dict[str, tuple[str, ...]] = {
    MARKET_TECH_SECTION: (
        "price_volume",
        "moving_averages",
        "relative_return",
        "technical_indicators",
        "drawdown",
        "nav_curve",
        "turnover_rate",
        "turnover_amount",
        "daily_return",
        "rolling_volatility",
        "cumulative_return",
    ),
    "基本面与估值": (
        "valuation_factors",
        "market_cap_trend",
        "profitability_factors",
        "growth_factors",
        "liquidity_factors",
        "debt_ratio_trend",
        "dividend_history",
        "share_structure",
        "latest_valuation_snapshot",
        "latest_quality_snapshot",
        "latest_liquidity_snapshot",
        "latest_growth_snapshot",
    ),
    "资金与交易结构": (
        "capital_flow",
        "cumulative_capital_flow",
        "buy_sell_value",
        "block_trade_activity",
        "margin_balances",
        "margin_activity",
    ),
    "宏观利率背景": ("shibor_rates", "yield_curve_snapshot"),
}

MAX_INLINE_CHARTS_PER_SECTION = 2
SECTION_INLINE_CHART_LIMITS: dict[str, int] = {MARKET_TECH_SECTION: 4}


def chart_caption(name: str) -> str:
    return CHART_CAPTIONS.get(name, name.replace("_", " "))


def fallback_chart_note(chart_name: str, data: dict[str, Any]) -> str:
    """从同源序列提取曲线形态，生成不含具体数值的图注。"""
    from .chart_pattern import chart_pattern_note

    return chart_pattern_note(chart_name, data)
