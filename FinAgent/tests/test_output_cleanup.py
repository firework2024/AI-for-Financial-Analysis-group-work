from finagent.output_cleanup import strip_chart_blocks, strip_table_blocks


def test_strip_chart_blocks_removes_figure_section():
    text = (
        "正文前\n\n"
        "#### 图 · 行业成长与杠杆对比\n\n"
        "![行业成长与杠杆对比](charts/000001_multi_agent_report/industry_growth_leverage_compare.png)\n\n"
        "**图注** 测试。\n\n"
        "正文后"
    )
    out = strip_chart_blocks(text, {"industry_growth_leverage_compare"})
    assert "industry_growth_leverage_compare.png" not in out
    assert "正文前" in out
    assert "正文后" in out


def test_strip_table_blocks_removes_quality_snapshot_table():
    text = (
        "#### 表 · 最新盈利质量因子\n\n"
        "| 指标 | 数值 |\n"
        "| --- | --- |\n"
        "| 毛利率(TTM) | 12.48% |\n\n"
        "后续正文"
    )
    out = strip_table_blocks(text, {"latest_quality_snapshot"})
    assert "最新盈利质量因子" not in out
    assert "后续正文" in out
