from finagent.multiagent import _technical_table_section_review


def test_flags_duplicate_technical_tables():
    content = """
**核心结论**

| 维度 | 最新收盘价 | MA20 | MA60 | RSI14 |
| --- | --- | --- | --- | --- |
| 最新 | 285.94 | 316.61 | 267.57 | 37.43 |

| 指标 | 数值 | 解读 |
| --- | --- | --- |
| 最新收盘价 | 285.94 | 截至2026-06-03 |
| MA20 | 316.61 | 当前价格低于均线 |
"""
    review = _technical_table_section_review({"量价与技术面": content})
    notes = review.get("量价与技术面", [])
    assert any("重复" in note or "横表" in note for note in notes)


def test_passes_single_vertical_technical_table():
    content = """
| 指标 | 数值 | 解读 |
| --- | --- | --- |
| 最新收盘价 | 285.94 | 截至2026-06-03 |
| MA20 | 316.61 | 当前价格低于20日均线 |
| MA60 | 267.57 | 当前价格高于60日均线 |
| RSI14 | 37.43 | 偏弱，未超卖 |
"""
    review = _technical_table_section_review({"量价与技术面": content})
    assert not review
