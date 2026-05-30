from finagent.datastore.annual_text import normalize_mda_text, search_mda_hits


def test_normalize_mda_text_preserves_paragraphs():
    raw = "第一段内容。\n\n第二段内容。\n\n\n第三段。"
    normalized = normalize_mda_text(raw)
    assert "\n\n" in normalized
    assert "第一段" in normalized and "第三段" in normalized


def test_search_mda_hits_keeps_newlines():
    text = "管理层讨论与分析\n\n公司本期营收稳步增长。\n\n资产质量保持稳定。"
    hits = search_mda_hits(text, "营收增长")
    assert hits
    assert "营收" in hits[0]["text"]
