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
    "gov_yield_trend": "国债收益率走势",
    "yield_curve_snapshot": "收益率曲线快照",
    "latest_valuation_snapshot": "最新估值快照",
    "latest_quality_snapshot": "最新质量因子快照",
    "latest_liquidity_snapshot": "最新偿债与流动性快照",
    "latest_growth_snapshot": "最新成长因子快照",
    "margin_enhanced": "融资余额与买卖额",
    "valuation_percentile": "PE/PB 历史分位",
    "industry_dbscan_anomaly": "DBSCAN 同行异常识别",
    "share_structure_pie": "股本结构",
    "dividend_spread": "股息率与无风险利率利差",
    "revenue_profit_trend": "营收与归母净利润趋势",
    "profit_vs_cashflow": "利润与经营现金流对比",
    "free_cashflow_trend": "自由现金流趋势",
    "margin_roe_trend": "毛利率与 ROE",
}

# 量纲差异大、不适合同轴条形图，改在正文中以表格展示
TABLE_SNAPSHOT_SPECS: dict[str, tuple[str, ...]] = {
    "latest_quality_snapshot": (
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "roe_ttm",
    ),
    "latest_valuation_snapshot": (
        "market_cap",
        "pe_ratio_ttm",
        "pb_ratio_ttm",
        "ps_ratio_ttm",
        "dividend_yield_ttm",
    ),
    "latest_liquidity_snapshot": (
        "current_ratio",
        "quick_ratio",
        "debt_to_asset_ratio",
    ),
}
TABLE_SNAPSHOT_KEYS = frozenset(TABLE_SNAPSHOT_SPECS)

# 行业横向对比：量纲不可比，统一以表格展示（本公司 / 行业中位数 / 均值 / 分位）
INDUSTRY_COMPARE_TABLE_SPECS: dict[str, tuple[str, ...]] = {
    "industry_valuation_compare_table": ("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"),
    "industry_profitability_compare_table": (
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "roe_ttm",
    ),
    "industry_growth_leverage_compare_table": (
        "operating_revenue_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "debt_to_asset_ratio",
        "current_ratio",
        "quick_ratio",
    ),
    # 经营质量章节：全量经营类指标一张表（不含 PE/PB/PS）
    "industry_operating_peer_compare_table": (
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "roe_ttm",
        "operating_revenue_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "debt_to_asset_ratio",
        "current_ratio",
        "quick_ratio",
    ),
    "industry_peer_compare_table": (
        "pe_ratio_ttm",
        "pb_ratio_ttm",
        "ps_ratio_ttm",
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "roe_ttm",
        "operating_revenue_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "debt_to_asset_ratio",
        "current_ratio",
        "quick_ratio",
    ),
}
INDUSTRY_COMPARE_TABLE_KEYS = frozenset(INDUSTRY_COMPARE_TABLE_SPECS)

DISABLED_PLACEMENT_TABLE_KEYS = frozenset(
    {
        "technical_snapshot_table",
        # TTM 因子快照与经营质量章 LLM 多年宽表（pit/三表）重复，改由作者自写
        "latest_quality_snapshot",
        "latest_liquidity_snapshot",
    }
)

# 量纲不可比的同行横截面条形图已停用，改由 industry_*_compare_table 展示
DISABLED_INDUSTRY_BAR_CHART_KEYS = frozenset(
    {
        "industry_valuation_compare",
        "industry_profitability_compare",
        "industry_growth_leverage_compare",
    }
)

# 章节写作 prompt 中需屏蔽的图表（与 scope 规则一致）
MARKET_SECTION_BLOCKED_CHART_KEYS = frozenset(
    {
        "valuation_factors",
        "valuation_percentile",
        "latest_valuation_snapshot",
        "profitability_factors",
        "growth_factors",
        "liquidity_factors",
        "debt_ratio_trend",
        "market_cap_trend",
        "revenue_profit_trend",
        "profit_vs_cashflow",
        "margin_balances",
        "margin_enhanced",
        "shibor_rates",
        "gov_yield_trend",
    }
)

OPERATING_QUALITY_BLOCKED_CHART_KEYS = DISABLED_INDUSTRY_BAR_CHART_KEYS | frozenset(
    {
        "valuation_percentile",
        "valuation_factors",
        "latest_valuation_snapshot",
        "dividend_spread",
    }
)


def filter_charts_for_section(charts: dict[str, str], blocked: frozenset[str]) -> dict[str, str]:
    return {name: path for name, path in charts.items() if name not in blocked}


# 批量清理 outputs/charts 时的默认图键（可与 --chart 追加）
DEFAULT_PURGE_OUTPUT_CHART_KEYS = frozenset(
    DISABLED_INDUSTRY_BAR_CHART_KEYS
    | {
        "latest_quality_snapshot",
        "latest_liquidity_snapshot",
        "latest_valuation_snapshot",
    }
)

# 批量清理报告正文中的机械表块（可与 --table 追加）
DEFAULT_PURGE_OUTPUT_TABLE_KEYS = frozenset(DISABLED_PLACEMENT_TABLE_KEYS)

TABLE_CAPTIONS: dict[str, str] = {
    "latest_quality_snapshot": "最新盈利质量因子",
    "latest_valuation_snapshot": "最新估值因子",
    "latest_liquidity_snapshot": "最新偿债与流动性",
    "margin_snapshot_table": "融资融券快照",
    "margin_period_table": "两融区间变动",
    "share_structure_table": "股本结构快照",
    "trading_activity_table": "成交活跃度",
    "funding_cost_table": "股息与资金成本",
    "dividend_recent_table": "近期分红记录",
    "industry_valuation_compare_table": "行业估值对比",
    "industry_profitability_compare_table": "行业盈利能力对比",
    "industry_growth_leverage_compare_table": "行业成长与杠杆对比",
    "industry_operating_peer_compare_table": "同行横向坐标",
    "industry_peer_compare_table": "行业横向坐标",
}

TABLE_SUBHEADING_HINTS: dict[str, tuple[str, ...]] = {
    "latest_quality_snapshot": ("盈利", "毛利率", "净利率", "ROE", "财务健康"),
    "latest_valuation_snapshot": ("估值", "市盈率", "市净率", "PE", "PB", "PS"),
    "latest_liquidity_snapshot": ("偿债", "流动比率", "速动", "负债"),
    "margin_snapshot_table": ("融资", "两融", "融券", "杠杆", "融资融券"),
    "margin_period_table": ("融资余额", "近两周", "攀升", "两融", "变动", "区间"),
    "share_structure_table": ("股东", "股本", "流通", "自由流通", "限售"),
    "trading_activity_table": ("成交", "换手", "成交额", "资金流向", "活跃度", "放量"),
    "funding_cost_table": ("分红", "资金成本", "Shibor", "国债", "股息", "无风险"),
    "dividend_recent_table": ("分红", "股息", "派息"),
    "industry_valuation_compare_table": ("行业", "同行", "横向", "估值", "PE", "PB", "PS", "分位", "中位数"),
    "industry_profitability_compare_table": ("行业", "同行", "横向", "毛利率", "净利率", "ROE", "盈利", "分位"),
    "industry_growth_leverage_compare_table": (
        "行业",
        "同行",
        "横向",
        "成长",
        "杠杆",
        "资产负债率",
        "流动比率",
        "速动",
        "分位",
    ),
    "industry_operating_peer_compare_table": (
        "行业",
        "同行",
        "横向",
        "同业",
        "经营质量",
        "毛利率",
        "净利率",
        "ROE",
        "成长",
        "杠杆",
        "分位",
        "中位数",
    ),
    "industry_peer_compare_table": ("行业", "同行", "横向", "分位", "中位数", "均值", "同业"),
}

MAX_TABLES_PER_SECTION = 2
SECTION_TABLE_LIMITS: dict[str, int] = {
    "资金与交易结构": 4,
    "经营质量分析": 4,
    "基本面与估值": 3,
}

DEFAULT_SECTION_TABLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "经营质量分析": ("industry_operating_peer_compare_table",),
    "资金与交易结构": (
        "margin_snapshot_table",
        "margin_period_table",
        "trading_activity_table",
        "share_structure_table",
    ),
    "基本面与估值": (
        "industry_peer_compare_table",
        "industry_valuation_compare_table",
        "latest_valuation_snapshot",
        "latest_growth_snapshot",
    ),
}

TABLE_ALL_KEYS = frozenset(
    set(TABLE_SNAPSHOT_KEYS)
    | set(INDUSTRY_COMPARE_TABLE_KEYS)
    | {
        "margin_snapshot_table",
        "margin_period_table",
        "share_structure_table",
        "trading_activity_table",
        "funding_cost_table",
        "dividend_recent_table",
    }
)

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
            "margin_enhanced",
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
            "latest_valuation_snapshot",
            "latest_quality_snapshot",
            "latest_liquidity_snapshot",
            "latest_growth_snapshot",
            "industry_dbscan_anomaly",
        ),
    ),
    ("宏观利率", ("shibor_rates", "gov_yield_trend", "yield_curve_snapshot")),
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
    "margin_enhanced": ("融资", "两融", "融券", "杠杆"),
    "valuation_factors": ("估值", "PE", "PB", "PS"),
    "market_cap_trend": ("市值", "总市值"),
    "profitability_factors": ("盈利", "毛利率", "净利率", "ROE"),
    "growth_factors": ("增长", "成长", "增速", "利润增速"),
    "liquidity_factors": ("流动比率", "速动", "流动性"),
    "debt_ratio_trend": ("负债", "资产负债率", "杠杆"),
    "dividend_history": ("分红", "股息"),
    "share_structure": ("股本", "流通", "总股本"),
    "shibor_rates": ("Shibor", "同业", "短期资金", "银行间"),
    "gov_yield_trend": ("国债", "收益率", "10年", "1年", "期限利差", "无风险"),
    "yield_curve_snapshot": ("收益率曲线", "国债", "无风险"),
    "latest_valuation_snapshot": ("估值快照", "市值"),
    "latest_quality_snapshot": ("质量因子", "偿债", "盈利能力"),
    "latest_growth_snapshot": ("成长因子", "增长", "增速"),
    "valuation_percentile": ("估值", "PE", "PB", "分位"),
    "industry_dbscan_anomaly": ("DBSCAN", "聚类", "异常", "噪声点", "同行", "横向对比"),
    "share_structure_pie": ("股本", "流通", "结构"),
    "dividend_spread": ("股息", "分红", "利差"),
    "revenue_profit_trend": ("营收", "营业收入", "收入", "归母净利润", "净利润"),
    "profit_vs_cashflow": ("现金流", "经营现金流", "净现比"),
    "free_cashflow_trend": ("自由现金流", "资本开支"),
    "margin_roe_trend": ("毛利率", "ROE", "盈利能力"),
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
    "latest_liquidity_snapshot": "偿债与流动性因子快照。",
    "latest_growth_snapshot": "成长类因子快照，可与正文增长表述对照。",
    "industry_dbscan_anomaly": "基于同行横截面因子的 DBSCAN 异常识别，显示目标公司、同行样本和噪声点。",
    "shibor_rates": "利率环境变化会影响权益资产折现率与相对吸引力。",
    "gov_yield_trend": "长端国债收益率下行往往压低 DCF 折现率并抬升高股息资产相对吸引力。",
    "yield_curve_snapshot": "利率环境变化会影响权益资产折现率与相对吸引力。",
    "revenue_profit_trend": "近年营收（柱）与归母净利润（折线）双轴对比，观察收入规模与盈利能力的匹配度。",
    "profit_vs_cashflow": "归母净利润与经营现金流净额多年对比，用于判断利润的现金含量（净现比）。",
    "free_cashflow_trend": "自由现金流多年趋势（正值/负值着色），反映企业可支配现金的变化方向。",
    "margin_roe_trend": "毛利率与 ROE 多年双轴走势，观察盈利能力和股东回报的变动轨迹。",
}

# 对话场景不生成/不嵌入的图（短回看 K 线不足 MA60 窗口时易空图）；年报与 multi_analyze 仍可使用
CHAT_EXCLUDED_CHART_KEYS = frozenset({"moving_averages"})


def chart_allowed_for_chat(chart_key: str) -> bool:
    return str(chart_key or "").strip() not in CHAT_EXCLUDED_CHART_KEYS


_MARKET_TECH_CHART_CANDIDATES: tuple[str, ...] = (
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
)

DEFAULT_SECTION_CHART_CANDIDATES: dict[str, tuple[str, ...]] = {
    MARKET_TECH_SECTION: _MARKET_TECH_CHART_CANDIDATES,
    "经营质量分析": (
        "industry_dbscan_anomaly",
        "revenue_profit_trend",
        "profit_vs_cashflow",
        "market_cap_trend",
        "profitability_factors",
        "growth_factors",
        "liquidity_factors",
        "debt_ratio_trend",
        "dividend_history",
        "latest_quality_snapshot",
        "latest_liquidity_snapshot",
        "latest_growth_snapshot",
        "free_cashflow_trend",
        "margin_roe_trend",
    ),
    "资金与交易结构": (
        "margin_enhanced",
        "capital_flow",
        "cumulative_capital_flow",
        "buy_sell_value",
        "block_trade_activity",
        "margin_balances",
        "margin_activity",
    ),
    "宏观利率背景": ("shibor_rates", "gov_yield_trend", "yield_curve_snapshot"),
    "基本面与估值": (
        "valuation_factors",
        "valuation_percentile",
        "profitability_factors",
        "growth_factors",
        "market_cap_trend",
        "latest_valuation_snapshot",
        "dividend_spread",
    ),
    "量价与趋势": _MARKET_TECH_CHART_CANDIDATES,
    "技术因素": (
        "technical_indicators",
        "drawdown",
        "rolling_volatility",
        "daily_return",
        "cumulative_return",
    ),
}

MAX_INLINE_CHARTS_PER_SECTION = 2
SECTION_INLINE_CHART_LIMITS: dict[str, int] = {
    MARKET_TECH_SECTION: 3,
    "经营质量分析": 3,
    "基本面与估值": 2,
    "量价与趋势": 3,
    "宏观利率背景":21,
    "资金与交易结构": 2,
}


def table_key_allowed_for_placement(table_key: str) -> bool:
    return table_key in TABLE_ALL_KEYS and table_key not in DISABLED_PLACEMENT_TABLE_KEYS


def chart_key_allowed_for_placement(chart_key: str) -> bool:
    return chart_key not in DISABLED_INDUSTRY_BAR_CHART_KEYS


def chart_caption(name: str) -> str:
    return CHART_CAPTIONS.get(name, name.replace("_", " "))


def fallback_chart_note(chart_name: str, data: dict[str, Any]) -> str:
    """从同源序列提取曲线形态，生成不含具体数值的图注。"""
    from .chart_pattern import chart_pattern_note

    return chart_pattern_note(chart_name, data)
