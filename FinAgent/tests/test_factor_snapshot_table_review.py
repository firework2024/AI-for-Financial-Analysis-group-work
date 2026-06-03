from finagent.multiagent import _factor_snapshot_table_section_review


def test_factor_snapshot_review_flags_disabled_mechanical_heading():
    sections = {
        "经营质量分析": (
            "**核心结论**\n\n测试。\n\n#### 表 · 最新盈利质量因子\n\n"
            "| 维度 | 毛利率(TTM) | 净利率(TTM) | ROE(TTM) |\n"
            "| --- | --- | --- | --- |\n"
            "| 最新 | 12.48% | -2.89% | — |"
        )
    }
    feedback = _factor_snapshot_table_section_review(sections)
    assert "经营质量分析" in feedback
    assert any("最新盈利质量因子" in note for note in feedback["经营质量分析"])


def test_factor_snapshot_review_ignores_clean_multi_year_table():
    sections = {
        "经营质量：现金流承压": (
            "**核心结论**\n\n净现比 0.36。\n\n"
            "| 指标 | 2023年 | 2024年 | 2025年 |\n"
            "| --- | --- | --- | --- |\n"
            "| 经营现金流（亿元） | 8.14 | 9.77 | 10.2 |"
        )
    }
    feedback = _factor_snapshot_table_section_review(sections)
    assert not feedback
