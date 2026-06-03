from finagent.multiagent import _local_validation, _section_overlap_review


def test_macro_section_with_margin_content_is_flagged():
    sections = {
        "宏观利率背景": (
            "**核心结论**\n\n融资余额220亿元持续攀升，PE(TTM)353倍对利率敏感。\n\n"
            "**短端利率**\n\nShibor隔夜1.32%，10Y国债1.74%。"
        ),
        "资金与交易结构": "融资余额220亿元持续攀升，两融余额创新高。",
        "基本面与估值": "PE(TTM)353倍，PB(TTM)33倍。",
    }
    review = _section_overlap_review(sections)
    notes = review["section_feedback"].get("宏观利率背景", [])
    assert any("资金与两融" in note or "融资余额" in note or "估值" in note for note in notes)
    assert review["structural_feedback"]
    assert review["structural_feedback"][0].get("keep_in") in {"资金与交易结构", "基本面与估值"}


def test_non_macro_section_with_shibor_is_flagged_when_macro_exists():
    sections = {
        "宏观利率背景": "Shibor隔夜1.32%，10Y国债1.74%，股息率与无风险利率利差收窄。",
        "基本面与估值": "PE(TTM)20倍；Shibor下行压低折现率，10Y国债1.74%。",
    }
    review = _section_overlap_review(sections)
    assert "基本面与估值" in review["section_feedback"]
    assert any("宏观利率背景" in note for note in review["section_feedback"]["基本面与估值"])


def test_local_validation_merges_overlap_into_structural_feedback():
    validation = _local_validation(
        data={"interbank_rate": {"rows": [{"date": "2026-05-29", "ON": 1.32}], "row_count": 1}},
        charts={f"chart_{i}": f"c{i}.png" for i in range(8)},
        sections={
            "宏观利率背景": "融资余额220亿元。Shibor 1.32%。",
            "资金与交易结构": "融资余额220亿元持续攀升。",
        },
        draft_markdown="",
    )
    assert validation["structural_feedback"]
    assert validation["final_decision"] == "revise"
