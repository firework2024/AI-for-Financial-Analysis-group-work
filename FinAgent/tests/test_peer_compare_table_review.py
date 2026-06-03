from finagent.multiagent import _peer_compare_table_section_review, _section_has_prose_peer_metric_list


def test_detects_prose_peer_metric_enumeration():
    text = """
**同行横向坐标**

毛利率(TTM)：26.21%，行业中位数15.99%，行业分位91%。
净利率(TTM)：18.09%，行业中位数3.17%，行业分位97%。
"""
    assert _section_has_prose_peer_metric_list(text)


def test_passes_qualitative_peer_heading_only():
    text = """
**同行横向坐标**

经营质量全面占优，盈利与偿债指标整体处于行业高位。
"""
    assert not _section_has_prose_peer_metric_list(text)


def test_peer_compare_table_review_flags_prose_list():
    review = _peer_compare_table_section_review(
        {
            "经营质量分析": (
                "**同行横向坐标**\n"
                "毛利率(TTM)：26.21%，行业中位数15.99%，行业分位91%。\n"
                "净利率(TTM)：18.09%，行业中位数3.17%，行业分位97%。"
            )
        }
    )
    assert "经营质量分析" in review
