from finagent.section_validation import local_validation, section_overlap_review


def test_macro_section_repeating_capital_content_is_flagged():
    sections = {
        "宏观利率背景": "Shibor 1.32%。融资余额220.96亿元持续攀升，融资买入额放大。",
        "资金与交易结构": "融资余额220.96亿元。",
    }
    review = section_overlap_review(sections)
    assert review["section_feedback"].get("宏观利率背景")


def test_non_macro_section_repeating_macro_is_flagged():
    sections = {
        "宏观利率背景": "Shibor 1.32%，10Y 国债 1.74%。",
        "基本面与估值": "Shibor 隔夜 1.32%，国债收益率 1.74%，无风险利率下行。",
    }
    review = section_overlap_review(sections)
    assert review["section_feedback"].get("基本面与估值")


def test_local_validation_merges_overlap_into_structural_feedback():
    validation = local_validation(
        data={},
        charts={f"c{i}": f"p{i}.png" for i in range(8)},
        sections={
            "宏观利率背景": "Shibor 1.32%。融资余额220.96亿元，融资买入放大，两融余额攀升。",
            "资金与交易结构": "融资余额220.96亿元。",
        },
        draft_markdown="",
    )
    assert validation["final_decision"] == "revise"
    assert validation["structural_feedback"]
