from finagent.section_validation import (
    peer_compare_table_section_review,
    section_has_prose_peer_metric_list,
    section_mentions_peer_comparison,
)


def test_section_has_prose_peer_metric_list_detects_enumeration():
    content = (
        "**同行横向坐标**\n\n"
        "毛利率 25.3%，行业中位数 17.2%，行业分位 91%。\n"
        "ROE 12.1%，行业中位数 8.5%，行业分位 75%。"
    )
    assert section_has_prose_peer_metric_list(content)


def test_section_has_prose_peer_metric_list_passes_table_first_heading():
    content = "**同行横向坐标**\n\n经营质量全面优于同行中位区间。"
    assert section_mentions_peer_comparison(content, table_first=True)


def test_peer_compare_table_review_flags_prose_list():
    review = peer_compare_table_section_review(
        {
            "经营质量分析": (
                "**同行横向坐标**\n\n"
                "毛利率 25.3%，行业中位数 17.2%，行业分位 91%。\n"
                "ROE 12.1%，行业中位数 8.5%，行业分位 75%。"
            )
        }
    )
    assert "经营质量分析" in review
