from finagent.pdf_text import extract_mda


def test_extract_mda_skips_table_of_contents_hit():
    text = (
        "目录\n第三节 管理层讨论与分析................................ 8\n第四节 公司治理........ 23\n"
        + "x" * 3200
        + "第三节 管理层讨论与分析\n一、报告期内公司从事的业务情况\n正文内容\n第四节 公司治理\n"
    )
    result = extract_mda(text)
    assert result.confidence == "high"
    assert "正文内容" in result.mda_text
    assert "目录" not in result.mda_text
