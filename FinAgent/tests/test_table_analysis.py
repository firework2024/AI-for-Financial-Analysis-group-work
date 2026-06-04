from finagent.table_analysis import (
    analyze_table_duplicates,
    apply_table_dedup,
    classify_table_layout,
    extract_report_tables,
    table_content_similarity,
)


def test_classify_vertical_and_horizontal_layout():
    assert classify_table_layout(["指标", "数值"], [["指标", "数值"], ["ROE", "12%"]]) == "vertical"
    assert (
        classify_table_layout(
            ["维度", "MA20", "MA60", "RSI14"],
            [["维度", "MA20", "MA60", "RSI14"], ["最新", "10", "9", "34"]],
        )
        == "horizontal"
    )


def test_duplicate_margin_table_keeps_capital_section():
    table = (
        "| 指标 | 2025-09-15 | 2026-05-28 |\n"
        "| --- | --- | --- |\n"
        "| 融资余额（亿元） | 134.31 | 220.96 |\n"
        "| 融券余额（亿元） | 1.2 | 1.5 |\n"
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
    analysis = analyze_table_duplicates(sections, plan=plan)
    assert analysis["duplicate_groups"]
    keep = analysis["duplicate_groups"][0]["keep_section"]
    assert keep == "资金与交易结构"
    cleaned = apply_table_dedup(sections, analysis)
    assert "| 融资余额" not in cleaned["宏观利率背景"]
    assert "| 融资余额" in cleaned["资金与交易结构"]


def test_mechanical_table_preferred_over_llm_duplicate():
    llm_table = (
        "| 指标 | 数值 |\n| --- | --- |\n| 毛利率 | 30% |\n| ROE | 12% |\n"
    )
    mech_table = (
        "#### 表 · 同行横向坐标\n\n"
        "同行池口径：测试。\n\n"
        "| 指标 | 本公司 | 行业中位数 | 行业均值 | 行业分位 | 解读 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 毛利率 | 30% | 25% | 26% | 70% | 偏高 |\n"
        "| ROE | 12% | 10% | 11% | 65% | 偏高 |\n"
        "| 资产负债率 | 40% | 45% | 44% | 40% | 稳健 |\n"
    )
    sections = {
        "经营质量分析": f"**核心结论**\n\n{llm_table}\n\n{mech_table}",
    }
    plan = {"sections": [{"name": "经营质量分析", "kind": "operating_quality"}]}
    tables = extract_report_tables(sections, plan=plan)
    assert len(tables) == 2
    mech = next(t for t in tables if t.source == "mechanical")
    llm = next(t for t in tables if t.source == "llm")
    assert mech.info_score > llm.info_score
    analysis = analyze_table_duplicates(sections, plan=plan)
    if analysis["duplicate_groups"]:
        assert analysis["duplicate_groups"][0]["keep_section"] == "经营质量分析"


def test_table_content_similarity_detects_same_metrics():
    rows = [
        ["指标", "2025", "2024"],
        ["营收", "100", "90"],
        ["净利润", "10", "8"],
    ]
    from finagent.table_analysis import ReportTable

    left = ReportTable("a", "章1", "", "llm", "wide", rows[0], rows, 10, 0, 0)
    right = ReportTable("b", "章2", "", "llm", "wide", rows[0], rows, 8, 0, 0)
    assert table_content_similarity(left, right) >= 0.9
