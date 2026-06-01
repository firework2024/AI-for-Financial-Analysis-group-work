from finagent.multi_report import (
    multi_report_display_title,
    resolve_multi_sec_name,
    strip_data_limitation_blocks,
)
from finagent.report_format import build_report_toc, clean_chart_prose, normalize_section_text, polish_field_refs, render_toc_markdown, section_anchor


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


def test_polish_field_refs_strips_inline_source_citations():
    text = "成长性持续承压（来源：reviewed_signals中“收入与归母净利润连续两年下滑”）。"
    out = polish_field_refs(text)
    assert "来源" not in out
    assert "reviewed_signals" not in out
    assert "成长性持续承压" in out


def test_polish_field_refs_drops_data_source_table_column():
    text = (
        "### 核心矛盾汇总\n\n"
        "| 矛盾维度 | 具体表现 | 数据来源 |\n"
        "| --- | --- | --- |\n"
        "| 净现比异常 | 依赖央行借款 | `reviewed_signals` |\n"
    )
    out = polish_field_refs(text)
    assert "数据来源" not in out
    assert "reviewed_signals" not in out
    assert "| 矛盾维度 | 具体表现 |" in out
    assert "依赖央行借款" in out


def test_strip_pipeline_only_sections_from_director():
    from finagent.report_format import strip_pipeline_only_sections

    text = (
        "### 总结\n\n"
        "2025年经营承压。\n\n"
        "---\n\n"
        "### 字段来源概览\n\n"
        "| 分析维度 | 引用字段 |\n"
        "| --- | --- |\n"
        "| 营收 | `revenue` |\n"
    )
    out = strip_pipeline_only_sections(text)
    assert "字段来源概览" not in out
    assert "`revenue`" not in out
    assert "2025年经营承压" in out


def test_normalize_director_strips_embedded_provenance_table():
    text = (
        "好的，以下是分析。\n\n"
        "### 总结\n\n"
        "正文结束。\n\n"
        "### 字段来源概览\n\n"
        "| 维度 | 字段 |\n|---|---|\n| 利润 | `net_profit` |\n"
    )
    out = normalize_section_text(text, "投资总监分析")
    assert "字段来源概览" not in out
    assert "net_profit" not in out
    assert "正文结束" in out


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


def test_resolve_multi_sec_name_from_summary():
    payload = {
        "meta": {"order_book_id": "600519.XSHG"},
        "summary": "贵州茅台（600519.XSHG）近期量价与基本面均承压。",
    }
    assert resolve_multi_sec_name(payload, "600519") == "贵州茅台"


def test_multi_report_display_title_includes_company_name():
    title = multi_report_display_title(stock_code="600519", sec_name="贵州茅台")
    assert title == "600519 贵州茅台 多智能体报告"


def test_strip_llm_revise_preamble_from_summary():
    text = (
        "好的，这是根据您提供的全部输入信息，为您汇总生成的《执行摘要》。\n\n"
        "宁德时代当前呈现“基本面强韧、技术面承压”的格局。"
    )
    out = normalize_section_text(text, "执行摘要")
    assert not out.startswith("好的")
    assert "宁德时代" in out


def test_strip_llm_revise_preamble_from_section():
    text = (
        "好的，这是根据您的反馈重写的《量价与趋势》章节。我已将融资融券内容移除。\n\n"
        "### 近期价格与量价\n\n- **日度价格走势**：截至2026年5月29日"
    )
    out = normalize_section_text(text, "量价与趋势")
    assert "好的" not in out.splitlines()[0]
    assert "### 近期价格与量价" in out


def test_apply_chart_placements_inserts_inline_images():
    from finagent.multi_report import apply_chart_placements, build_default_chart_placement

    sections = {"量价与趋势": "### 量价\n\n正文。"}
    charts = {"price_volume": "charts/test/price_volume.png"}
    placement = build_default_chart_placement(charts=charts, sections=sections)
    result, _ = apply_chart_placements(sections, charts, placement, data={})
    assert "![收盘价与成交量]" in result["量价与趋势"]
    assert "price_volume.png" in result["量价与趋势"]


def test_apply_chart_placements_inserts_quality_snapshot_table():
    from finagent.multi_report import apply_chart_placements

    sections = {"基本面与估值": "### 盈利\n\n正文。"}
    charts = {"valuation_factors": "charts/test/valuation_factors.png"}
    data = {
        "factor": {
            "gross_profit_margin_ttm": 0.2621,
            "net_profit_margin_ttm": 0.1809,
            "roe_ttm": 0.15,
        }
    }
    placement = {
        "placements": [{"section": "基本面与估值", "charts": ["latest_quality_snapshot"], "anchor": None, "note": None}],
        "omitted": [],
    }
    result, _ = apply_chart_placements(sections, charts, placement, data=data)
    body = result["基本面与估值"]
    assert "#### 表 · 最新盈利质量因子" in body
    assert "| 维度 | 毛利率(TTM) | 净利率(TTM) | ROE(TTM) |" in body
    assert "| 最新 | 26.21% | 18.09% | 15.00% |" in body
    assert "| 毛利率(TTM) | 26.21% |" not in body  # 不用 feat 两列「指标|数值」单列表
    assert "latest_quality_snapshot.png" not in body
    assert "**图注**" not in body


def test_apply_chart_placements_inserts_after_bold_subheading():
    from finagent.multi_report import apply_chart_placements

    sections = {
        "资金与交易结构": "**融资融券**\n\n融资余额上升。\n\n**股东与股本结构**\n\n股本稳定。"
    }
    charts = {"margin_enhanced": "charts/test/margin_enhanced.png"}
    placement = {
        "placements": [
            {
                "section": "资金与交易结构",
                "charts": ["margin_enhanced"],
                "anchor": "融资融券",
                "note": None,
            }
        ],
        "omitted": [],
    }
    result, _ = apply_chart_placements(sections, charts, placement, data={})
    body = result["资金与交易结构"]
    assert body.index("#### 图") < body.index("融资余额上升")
    assert "margin_enhanced.png" in body


def test_local_visual_need_picks_margin_for_capital_section():
    from finagent.visual_placement import local_visual_need

    sections = {
        "量价与技术面": "价格与均线分析。",
        "资金与交易结构": "**融资融券**\n\n融资余额从211亿升至221亿。",
        "基本面与估值": "PE 24倍。",
    }
    charts = {"margin_enhanced": "charts/test/margin_enhanced.png", "price_volume": "charts/test/price_volume.png"}
    data = {
        "securities_margin": {
            "row_count": 2,
            "rows": [
                {"date": "2026-05-27", "margin_balance": 22100000000, "buy_on_margin_value": 2100000000},
                {"date": "2026-05-28", "margin_balance": 22000000000, "buy_on_margin_value": 760000000},
            ],
        },
        "factor": {"pe_ratio_ttm": 24.8},
    }
    need = local_visual_need(data=data, sections=sections, charts=charts)
    keys = [item["visual_key"] for item in need.get("visuals") or []]
    assert "margin_enhanced" in keys or "margin_snapshot_table" in keys


def test_section_writing_style_hint_for_risk_section():
    from finagent.report_format import section_writing_style_hint

    hint = section_writing_style_hint("综合风险与数据局限")
    assert "核心结论" in hint
    assert "数据局限" in hint


def test_normalize_core_conclusion_removes_orphan_colon():
    raw = (
        "**核心结论**\n\n"
        "：2025年营收与净利润连续第二年下滑，但经营现金流暴增398.7%，利润与现金流严重背离。\n\n"
        "### 后续章节"
    )
    out = normalize_section_text(raw, "投资总监分析")
    assert "\n\n：2025" not in out
    assert "2025年营收" in out


def test_normalize_section_forces_lead_conclusion():
    text = "**趋势概览**\n\n近20日收益率为-5.36%，显示短期价格处于下行趋势。"
    out = normalize_section_text(text, "量价与技术面")
    assert out.startswith("**核心结论**")


def test_structure_risk_section_splits_topics_and_limitations():
    wall = (
        "截至2026年5月29日，600519.XSHG收盘价为1326.0元，较20日均线折价0.55%，"
        "近20日收益率为-5.36%，显示短期价格处于下行趋势。"
        "基本面方面，截至2026-05-29，600519.XSHG市盈率（TTM）为20.04倍，"
        "毛利率（TTM）高达90.50%，但归母净利润同比增长率为-7.07%。"
        "融资融券方面，截至2026-05-28，融资余额约200.48亿元，融资买入额达14.66亿元。"
        "资金流向数据缺失（row_count为0），无法评估主力资金流向。"
        "宏观利率方面，2026-05-29 Shibor隔夜为1.324%，10年期国债收益率为1.74%。"
        "数据局限包括：1）资金流向数据完全缺失；2）成长性指标缺乏季度环比；3）无行业对比数据。"
    )
    out = normalize_section_text(wall, "综合风险与数据局限")
    assert "**核心结论**" in out
    assert "**基本面**" in out
    assert "**融资融券**" in out
    assert "**宏观利率**" in out
    assert "**数据局限**" in out
    assert "- 资金流向数据完全缺失" in out
    assert "- 成长性指标缺乏季度环比" in out
    assert "1）" not in out


def test_split_long_paragraph_into_shorter_blocks():
    long_para = "第一句内容较长但仍需保留。" * 25
    out = normalize_section_text(long_para, "量价与技术面")
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 2
    assert all(len(p) <= 320 for p in paragraphs)
