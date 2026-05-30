from finagent.multi_report import strip_data_limitation_blocks
from finagent.report_format import clean_chart_prose


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
