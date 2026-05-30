from finagent.multi_report import strip_data_limitation_blocks
from finagent.report_format import build_report_toc, clean_chart_prose, polish_field_refs, render_toc_markdown, section_anchor


def test_polish_field_refs_removes_redundant_metadata():
    text = (
        "根据dividend_recent数据，目标股票（300750.XSHE）在2025年第四季度（quarter为2025q4）"
        "合计每股派发现金红利69.57元（21.78元+47.79元）。"
    )
    out = polish_field_refs(text)
    assert "dividend_recent" not in out
    assert "quarter" not in out
    assert "2025q4" not in out
    assert "69.57元" in out


def test_polish_field_refs_keeps_needed_field_tag():
    text = "融资余额 `margin_balance` 持续上升。"
    out = polish_field_refs(text)
    assert "`margin_balance`" in out


def test_build_report_toc_assigns_unique_ids():
    entries = build_report_toc(["执行摘要", "核心指标", "执行摘要"])
    assert len(entries) == 3
    ids = [item["id"] for item in entries]
    assert len(set(ids)) == 3


def test_render_toc_markdown_contains_links():
    entries = build_report_toc(["执行摘要", "核心指标速览"])
    text = "\n".join(render_toc_markdown(entries))
    assert "## 目录" in text
    assert f"(#{entries[0]['id']})" in text


def test_section_anchor_is_stable_slug():
    used = set()
    assert section_anchor("量价与趋势", used) == section_anchor("量价与趋势", set())
    first = section_anchor("测试", used)
    second = section_anchor("测试", used)
    assert first != second


def test_strip_data_limitation_blocks():
    text = "### 分析\n\n正文内容。\n\n#### 数据局限\n\n- 缺少行业对比\n- 未采集资金流向\n\n### 其他"
    cleaned, notes = strip_data_limitation_blocks(text)
    assert "#### 数据局限" not in cleaned
    assert "缺少行业对比" in notes
    assert "正文内容" in cleaned


def test_clean_chart_path_in_backticks():
    text = "请参考 `charts/600519_multi_agent_report/moving_averages.png` 图表，该图展示了均线。"
    out = clean_chart_prose(text)
    assert "`charts/600519_multi_agent_report/moving_averages.png`" not in out
    assert "请参考" not in out
    assert "该图展示了均线" not in out


def test_clean_chart_name_with_parentheses():
    text = (
        "price_volume 图表（charts/600519_multi_agent_report/price_volume.png）"
        "和 moving_averages 图表（charts/600519_multi_agent_report/moving_averages.png）直观展示"
    )
    out = clean_chart_prose(text)
    assert "charts/" not in out
    assert "price_volume 图表" not in out


def test_clean_embedded_markdown_image():
    text = "如下所示\n\n![price volume](charts/600519_multi_agent_report/price_volume.png)\n\n正文继续。"
    out = clean_chart_prose(text)
    assert "![price volume]" not in out
    assert "正文继续" in out
