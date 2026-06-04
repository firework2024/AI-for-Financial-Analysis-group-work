from finagent.section_validation import local_validation
from finagent.section_validation import (
    duplicate_table_review,
    rewrite_constraints_for_section,
    section_scope_review,
)


def test_macro_section_with_margin_table_is_scope_flagged():
    sections = {
        "宏观利率背景": (
            "**核心结论**\n\n融资余额220.96亿元。\n\n"
            "| 指标 | 2025-09-15 | 2026-05-28 |\n"
            "| --- | --- | --- |\n"
            "| 融资余额（亿元） | 134.31 | 220.96 |\n\n"
            "Shibor隔夜1.32%，10Y国债1.74%。"
        ),
        "资金与交易结构": "融资余额220.96亿元持续攀升。",
    }
    review = section_scope_review(sections)
    notes = review["section_feedback"].get("宏观利率背景", [])
    assert any("融资余额" in note or "两融" in note for note in notes)
    assert review["structural_feedback"]


def test_market_section_with_pb_is_scope_flagged():
    sections = {
        "量价与技术面": "**核心结论**\n\nPE(TTM)27.7倍，PB6.2倍，RSI34.7。",
        "基本面与估值": "PE(TTM)27.7倍。",
    }
    review = section_scope_review(sections)
    assert "量价与技术面" in review["section_feedback"]
    assert any("PB" in note or "估值" in note for note in review["section_feedback"]["量价与技术面"])


def test_duplicate_margin_table_across_macro_and_capital():
    table = (
        "| 指标 | 2025-09-15 | 2026-05-28 |\n"
        "| --- | --- | --- |\n"
        "| 融资余额（亿元） | 134.31 | 220.96 |\n"
    )
    sections = {
        "资金与交易结构": f"**核心结论**\n\n{table}",
        "宏观利率背景": f"**核心结论**\n\n{table}\n\nShibor 1.32%。",
    }
    plan = {
        "sections": [
            {"name": "宏观利率背景", "kind": "macro"},
            {"name": "资金与交易结构", "kind": "capital"},
        ]
    }
    review = duplicate_table_review(sections, plan=plan)
    assert review["section_feedback"].get("宏观利率背景")


def test_rewrite_constraints_for_macro_lists_forbidden_margin():
    sections = {
        "宏观利率背景": "融资余额220.96亿元",
        "资金与交易结构": "融资余额",
    }
    constraints = rewrite_constraints_for_section(
        "宏观利率背景",
        sections=sections,
        plan={"sections": [{"name": "宏观利率背景", "kind": "macro"}]},
        validation={"structural_feedback": []},
    )
    assert "融资余额" in constraints["forbidden_keywords"]


def test_local_validation_merges_scope_and_duplicate():
    table = (
        "| 指标 | 2025-09-15 | 2026-05-28 |\n"
        "| --- | --- | --- |\n"
        "| 融资余额（亿元） | 134.31 | 220.96 |\n"
    )
    validation = local_validation(
        data={"interbank_rate": {"rows": [{"date": "2026-05-29", "ON": 1.32}], "row_count": 1}},
        charts={f"chart_{i}": f"c{i}.png" for i in range(8)},
        sections={
            "宏观利率背景": f"{table}\n\nShibor 1.32%。",
            "资金与交易结构": table,
        },
        draft_markdown="",
    )
    assert validation["final_decision"] == "revise"
    assert any(item.get("issue") == "duplicate_table" for item in validation["structural_feedback"])
