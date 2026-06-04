from finagent.section_validation import technical_table_section_review


def test_allows_llm_technical_markdown_tables():
    content = (
        "| 维度 | MA20 | MA60 | RSI |\n| --- | --- | --- | --- |\n| 数值 | 10 | 9 | 34 |\n\n"
        "| 指标 | 数值 | 解读 |\n| --- | --- | --- |\n| MA20 | 10 | 上方 |\n| RSI | 34 | 偏弱 |"
    )
    review = technical_table_section_review({"量价与技术面": content})
    assert not review


def test_passes_single_vertical_technical_table():
    content = (
        "| 指标 | 数值 | 解读 |\n| --- | --- | --- |\n| MA20 | 10 | 上方 |\n| RSI | 34 | 偏弱 |"
    )
    review = technical_table_section_review({"量价与技术面": content})
    assert not review
