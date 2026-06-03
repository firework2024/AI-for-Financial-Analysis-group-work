"""对话助手共用的回答策略（允许推导，禁止编造）。"""

CHAT_ANSWER_POLICY = (
    "须基于 tools/observations/evidence_summary 中的原始数据作答，禁止编造未提供的数字或外部来源。"
    "允许且鼓励在证据充分时自行计算：同比/环比、CAGR、收现比/净现比、简易 PE/PB/PS"
    "（如 factor 缺失时用 股价×股本/净利润、market_cap/净利润，或 price 序列算区间收益）；"
    "推导结果须注明公式或口径（如「按最近年报归母净利润估算」）。"
    "pe_ratio_ttm_source 为 derived_* 时表示本地估算，回答中应说明为估算。"
    "用户问分析/对比/怎么样/如何时可适度展开相关维度；仅问单一指标时聚焦该指标。"
    "intent.quote_primary 或只问股价时仍只答行情（日期、收盘价、涨跌幅），勿写财务指标。"
    "缺数说明缺口，不给买卖建议，不输出 JSON。"
)

CHAT_VISUAL_POLICY = (
    "【对话不配长图】禁止插入 Markdown 图片、charts/ 路径或「#### 图 · …」图块；"
    "尤其不要输出「收盘价与 MA20/MA60」/ moving_averages 图（本地 K 线不足 60 日时易空图）。"
    "若需说明均线或趋势，只用 technical 中的 latest_close、ma20、ma60、return_20d/return_60d 等数字文字描述。"
    "多智能体年报报告可配图，本会话对话不配。"
)

CHAT_NARROW_GUIDANCE = (
    "用户已收窄到特定指标：优先直接给出核心数字；必要时可一两句补充口径、同比或推导过程。"
)
