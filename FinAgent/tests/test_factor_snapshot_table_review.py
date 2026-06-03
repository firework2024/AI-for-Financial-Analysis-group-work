from finagent.section_validation import factor_snapshot_table_section_review


def test_factor_snapshot_review_flags_disabled_mechanical_heading():
    sections = {
        "经营质量分析": (
            "**核心结论**\n\n"
            "#### 表 · 最新盈利质量因子\n\n"
            "| 维度 | 毛利率(TTM) |\n| --- | --- |\n| 数值 | 25% |"
        )
    }
    feedback = factor_snapshot_table_section_review(sections)
    assert "经营质量分析" in feedback


def test_factor_snapshot_review_ignores_clean_multi_year_table():
    sections = {
        "经营质量分析": (
            "| 指标 | 2023 | 2024 | 2025 |\n"
            "| --- | --- | --- | --- |\n"
            "| 归母净利润 | 1 | 2 | 3 |"
        )
    }
    feedback = factor_snapshot_table_section_review(sections)
    assert not feedback
