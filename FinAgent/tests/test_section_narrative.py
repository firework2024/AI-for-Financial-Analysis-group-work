from finagent.chart_catalog import MARKET_TECH_SECTION
from finagent.section_validation import section_narrative_review

GOOD_TECH = """
### 近期价格与量价：震荡下行后放量反弹

短期价格先震荡回落至 402.5 元，随后在放量配合下反弹至 424 元，显示下跌动能有所减弱。

- **关键区间**：5 月 26 日低点 402.5 元，5 月 29 日收于 424 元。
- **量能**：反弹日换手升至 1.25%，高于近期均值。

**对 300750.XSHE 的影响**：量价配合的反弹缓解短期超卖压力，但尚未确认趋势反转。

### 综合判断

短中期呈现「中期涨幅较大、短期回调后修复」格局，需观察能否有效突破 MA20。
"""

BAD_TECH = """
### 近期价格与量价

- **日度价格走势**：截至2026年5月29日，最新收盘价为424.0元，当日上涨2.00%。5月14日为427.0元，5月26日为402.5元，5月27日为414.8元。
- **成交量**：5月27日成交量5337.29万股，5月29日4981.19万股。
"""


def test_narrative_review_passes_conclusion_first_section():
    review = section_narrative_review(sections={MARKET_TECH_SECTION: GOOD_TECH})
    assert review[MARKET_TECH_SECTION]["decision"] == "pass"


def test_narrative_review_flags_data_dump_section():
    review = section_narrative_review(sections={MARKET_TECH_SECTION: BAD_TECH})
    assert review[MARKET_TECH_SECTION]["decision"] == "rewrite"
    assert "结论先行" in review[MARKET_TECH_SECTION]["reason"]
