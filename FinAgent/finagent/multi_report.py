from __future__ import annotations

import html
import re
from typing import Any

from .report_format import (
    DISCLAIMER,
    MISSING_LABEL,
    clean_chart_prose,
    disclaimer_lines,
    fmt_num,
    fmt_pct,
    format_generated_at,
    format_generated_at_iso,
    normalize_section_text,
    normalize_sections,
)
from .report_html import chart_grid_html, markdown_to_html, wrap_html_document

CHART_COLUMNS = 2
CHART_CAPTIONS: dict[str, str] = {
    "price_volume": "收盘价与成交量",
    "moving_averages": "收盘价与 MA20/MA60",
    "cumulative_return": "累计收益率",
    "nav_curve": "净值曲线",
    "drawdown": "回撤曲线",
    "technical_indicators": "RSI 与 MACD",
    "turnover_rate": "换手率",
    "capital_flow": "日度净流入",
    "cumulative_capital_flow": "累计净流入",
    "buy_sell_value": "买卖金额对比",
    "margin_balances": "融资融券余额",
    "margin_activity": "融资买入与融券卖出",
    "valuation_factors": "估值因子走势",
    "dividend_history": "分红历史",
    "share_structure": "股本结构",
    "shibor_rates": "Shibor 利率",
    "yield_curve_snapshot": "收益率曲线快照",
    "latest_valuation_snapshot": "最新估值快照",
    "latest_quality_snapshot": "最新质量因子快照",
}

CHART_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("价格与趋势", ("nav_curve", "price_volume", "moving_averages", "cumulative_return", "drawdown", "technical_indicators", "turnover_rate")),
    ("资金与两融", ("capital_flow", "cumulative_capital_flow", "buy_sell_value", "margin_balances", "margin_activity")),
    ("估值与结构", ("valuation_factors", "dividend_history", "share_structure", "latest_valuation_snapshot", "latest_quality_snapshot")),
    ("宏观利率", ("shibor_rates", "yield_curve_snapshot")),
]

CHART_INTERPRETATION_SECTION = "图表解读"

DATA_QUALITY_KEYS: tuple[tuple[str, str], ...] = (
    ("price", "行情"),
    ("capital_flow", "资金流向"),
    ("securities_margin", "两融"),
    ("factor_history", "因子历史"),
    ("pit_financials", "年报三表"),
    ("dividend", "分红"),
    ("shares", "股本"),
    ("interbank_rate", "Shibor"),
    ("yield_curve", "收益率曲线"),
)

CHART_SUBHEADING_HINTS: dict[str, tuple[str, ...]] = {
    "nav_curve": ("价格走势", "净值", "收盘价", "价格", "表现", "近期"),
    "price_volume": ("成交量", "量价", "换手"),
    "moving_averages": ("均线", "MA20", "MA60", "趋势"),
    "turnover_rate": ("换手",),
    "cumulative_return": ("累计收益", "收益率", "区间收益"),
    "drawdown": ("回撤", "最大回撤", "下行", "跌幅"),
    "technical_indicators": ("RSI", "MACD", "动量", "技术指标"),
    "capital_flow": ("净流入", "资金流向", "买卖"),
    "cumulative_capital_flow": ("累计净流入", "累计资金"),
    "buy_sell_value": ("买入", "卖出", "买卖金额"),
    "margin_balances": ("融资余额", "融券余额", "两融余额"),
    "margin_activity": ("融资买入", "融券卖出", "两融交易"),
    "valuation_factors": ("估值", "PE", "PB", "PS"),
    "dividend_history": ("分红", "股息"),
    "share_structure": ("股本", "流通", "总股本"),
    "shibor_rates": ("Shibor", "同业", "短期资金"),
    "yield_curve_snapshot": ("收益率曲线", "国债", "无风险"),
    "latest_valuation_snapshot": ("估值快照", "市值"),
    "latest_quality_snapshot": ("质量因子", "偿债", "盈利能力"),
}

CHART_BRIEF_NOTES: dict[str, str] = {
    "nav_curve": "区间净值走势（期初=1），便于对照价格趋势叙述。",
    "cumulative_return": "区间内累计收益，可与正文收益率表述对照。",
    "drawdown": "价格回撤幅度，反映区间风险暴露。",
    "technical_indicators": "RSI/MACD 等动量与超买超卖参考。",
    "capital_flow": "日度买卖净流入，反映短期资金方向。",
    "cumulative_capital_flow": "累计净流入趋势，观察资金持续性。",
    "buy_sell_value": "买卖金额对比，辅助判断交易结构。",
    "latest_valuation_snapshot": "最新估值因子横截面，注意量纲差异。",
    "latest_quality_snapshot": "盈利与偿债类因子快照。",
}


def render_multi_markdown(
    *,
    summary: str,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    inline_charts: bool = True,
    unused_charts: list[str] | None = None,
    validation: dict[str, Any] | None = None,
) -> str:
    """按固定模版渲染多智能体 Markdown（不含验证 Agent 复核段）。"""
    ordered_sections = _output_section_items(sections, plan, charts)
    body = "\n\n".join(f"## {name}\n\n{content}" for name, content in ordered_sections)
    summary_text = normalize_section_text(summary, "执行摘要")
    quality = build_data_quality_summary(data)
    lines = [
        f"# {data['order_book_id']} 多智能体研究报告",
        "",
    ]
    banner = validation_publish_banner(validation)
    if banner:
        lines.extend([banner, ""])
    lines.extend(
        [
            "## 执行摘要",
            summary_text,
            "",
            "## 核心指标速览",
            *_core_metric_table(data),
            "",
        ]
    )
    lines.extend([body, ""])
    if not inline_charts and unused_charts is None:
        lines.extend(["## 可视化", *_format_chart_section(charts), ""])
    lines.extend(
        [
            "## 数据与工具说明",
            f"- 数据区间：{data['start_date']} 至 {data['end_date']}",
            f"- 计划使用的米筐函数：{', '.join(plan.get('tools') or [])}",
            f"- 数据执行日志：`{data.get('data_log') or data.get('python_script', '')}`",
            f"- 数据质量：{quality['summary_line']}",
            f"- 生成时间：{format_generated_at()}",
            "",
            *disclaimer_lines(),
        ]
    )
    markdown = "\n".join(lines)
    return _fix_legacy_chart_paths(markdown)


def _fix_legacy_chart_paths(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        alt, url = match.group(1), match.group(2)
        if url.startswith(("http://", "https://", "data:")):
            return match.group(0)
        return f"![{alt}]({_normalize_chart_path(url)})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, text)


def render_multi_html(
    *,
    summary: str,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    inline_charts: bool = True,
    unused_charts: list[str] | None = None,
    validation: dict[str, Any] | None = None,
) -> str:
    """与 render_multi_markdown 结构对称；图表用 HTML img，可直接浏览器打开。"""
    ordered_sections = _output_section_items(sections, plan, charts)
    summary_text = normalize_section_text(summary, "执行摘要")
    quality = build_data_quality_summary(data)
    title = f"{data['order_book_id']} 多智能体研究报告"
    parts = [f"<h1>{html.escape(title)}</h1>"]
    banner = validation_publish_banner(validation)
    if banner:
        parts.append(f'<aside class="draft-banner">{markdown_to_html(banner, in_section=True)}</aside>')

    parts.append("<h2>执行摘要</h2>")
    parts.append(f'<section class="section-body">{markdown_to_html(summary_text, in_section=True)}</section>')

    parts.append("<h2>核心指标速览</h2>")
    parts.append(_core_metric_table_html(data))

    for name, content in ordered_sections:
        parts.append(f"<h2>{html.escape(name)}</h2>")
        parts.append(f'<section class="section-body">{markdown_to_html(content, in_section=True)}</section>')

    if not inline_charts and unused_charts is None:
        parts.append("<h2>可视化</h2>")
        parts.extend(_format_chart_section_html(charts))

    parts.append("<h2>数据与工具说明</h2>")
    parts.append("<ul class=\"meta-list\">")
    parts.append(f"<li>数据区间：{html.escape(str(data['start_date']))} 至 {html.escape(str(data['end_date']))}</li>")
    parts.append(f"<li>计划使用的米筐函数：{html.escape(', '.join(plan.get('tools') or []))}</li>")
    parts.append(
        f"<li>数据执行日志：<code>{html.escape(str(data.get('data_log') or data.get('python_script') or ''))}</code></li>"
    )
    parts.append(f"<li>数据质量：{html.escape(quality['summary_line'])}</li>")
    parts.append(f"<li>生成时间：{html.escape(format_generated_at())}</li>")
    parts.append("</ul>")

    parts.append(f'<section class="disclaimer"><h2>免责声明</h2><p>{html.escape(DISCLAIMER)}</p></section>')
    return wrap_html_document(title=title, body_html="\n".join(parts))


def build_multi_json_payload(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None,
    summary: str,
    output_markdown: str,
    output_json: str,
    output_html: str | None = None,
    chart_placement: dict[str, Any] | None = None,
    unused_charts: list[str] | None = None,
    figure_notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """分层 JSON：报告可读结构 + 数据摘要，避免整包 time-series rows。"""
    normalized = _ordered_sections_dict(sections, plan)
    validation = validation or {}
    payload: dict[str, Any] = {
        "meta": {
            "report_type": "multi_analyze",
            "order_book_id": data.get("order_book_id"),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "output_markdown": output_markdown,
            "output_json": output_json,
            "output_html": output_html,
            "generated_at": format_generated_at_iso(),
            "data_log": data.get("data_log") or data.get("python_script"),
            **_validation_meta(validation),
        },
        "summary": normalize_section_text(summary, "执行摘要"),
        "sections": normalized,
        "charts": {name: _normalize_chart_path(path) for name, path in charts.items()},
        "validation": validation,
        "plan": {
            "objective": plan.get("objective"),
            "tools": plan.get("tools"),
            "risk_controls": plan.get("risk_controls"),
            "sections": [item.get("name") for item in plan.get("sections") or [] if isinstance(item, dict)],
        },
        "data_summary": build_data_summary(data),
    }
    if chart_placement is not None:
        payload["chart_placement"] = chart_placement
    if unused_charts is not None:
        payload["unused_charts"] = unused_charts
    if figure_notes:
        payload["figure_notes"] = figure_notes
    return payload


DEFAULT_SECTION_CHART_CANDIDATES: dict[str, tuple[str, ...]] = {
    "量价与趋势": ("nav_curve", "price_volume", "moving_averages", "turnover_rate", "cumulative_return"),
    "基本面与估值": ("valuation_factors", "dividend_history", "share_structure", "latest_valuation_snapshot"),
    "资金与交易结构": ("capital_flow", "cumulative_capital_flow", "buy_sell_value", "margin_balances", "margin_activity"),
    "技术因素": ("nav_curve", "technical_indicators", "drawdown"),
    "宏观利率背景": ("shibor_rates", "yield_curve_snapshot"),
    "图表解读": (),
}
MAX_INLINE_CHARTS_PER_SECTION = 2


def build_default_chart_placement(
    *,
    charts: dict[str, str],
    sections: dict[str, str],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    blocked = blocked or set()
    allowed = [name for name in charts if name not in blocked]
    placements: list[dict[str, Any]] = []
    used: set[str] = set()
    for section, candidates in DEFAULT_SECTION_CHART_CANDIDATES.items():
        if section not in sections or section == CHART_INTERPRETATION_SECTION:
            continue
        picked = [name for name in candidates if name in allowed and name not in used][:MAX_INLINE_CHARTS_PER_SECTION]
        if not picked:
            continue
        placements.append({"section": section, "charts": picked, "anchor": None, "note": None})
        used.update(picked)
    omitted = [name for name in charts if name in blocked]
    unused = [name for name in charts if name not in used and name not in blocked]
    return {"placements": placements, "omitted": omitted, "unused": unused}


def normalize_chart_placement(
    placement: dict[str, Any],
    *,
    charts: dict[str, str],
    sections: dict[str, str],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    blocked = blocked or set()
    valid_sections = set(sections.keys())
    seen: set[str] = set()
    placements: list[dict[str, Any]] = []
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        if section not in valid_sections or section == CHART_INTERPRETATION_SECTION:
            continue
        chart_names: list[str] = []
        for name in item.get("charts") or []:
            key = str(name).strip()
            if key in charts and key not in blocked and key not in seen:
                chart_names.append(key)
                seen.add(key)
        if not chart_names:
            continue
        anchor = str(item.get("anchor") or "").strip() or None
        note = str(item.get("note") or "").strip() or None
        placements.append({"section": section, "charts": chart_names, "anchor": anchor, "note": note})
    omitted = sorted({str(name) for name in (placement.get("omitted") or []) if str(name) in charts} | blocked)
    unused = [name for name in charts if name not in seen and name not in blocked]
    return {"placements": placements, "omitted": omitted, "unused": unused}


def fill_missing_section_placements(
    placement: dict[str, Any],
    *,
    charts: dict[str, str],
    sections: dict[str, str],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    """在 LLM 编排结果上补全未覆盖章节的图表，避免大量图表仅堆在附录。"""
    blocked = blocked or set()
    placements: list[dict[str, Any]] = list(placement.get("placements") or [])
    used: set[str] = set()
    section_counts: dict[str, int] = {}
    for item in placements:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "")
        names = [str(name) for name in item.get("charts") or [] if str(name) in charts and str(name) not in blocked]
        if not names:
            continue
        used.update(names)
        section_counts[section] = section_counts.get(section, 0) + len(names)

    for section, candidates in DEFAULT_SECTION_CHART_CANDIDATES.items():
        if section not in sections or section == CHART_INTERPRETATION_SECTION:
            continue
        count = section_counts.get(section, 0)
        for name in candidates:
            if count >= MAX_INLINE_CHARTS_PER_SECTION:
                break
            if name not in charts or name in blocked or name in used:
                continue
            placements.append({"section": section, "charts": [name], "anchor": None, "note": None})
            used.add(name)
            count += 1
        section_counts[section] = count

    unused = [name for name in charts if name not in used and name not in blocked]
    omitted = sorted({str(name) for name in (placement.get("omitted") or []) if str(name) in charts} | blocked)
    return {"placements": placements, "omitted": omitted, "unused": unused}


def apply_chart_placements(
    sections: dict[str, str],
    charts: dict[str, str],
    placement: dict[str, Any],
    figure_notes: dict[str, str] | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    figure_notes = figure_notes or {}
    data = data or {}
    result = {
        name: clean_chart_prose(_strip_embedded_chart_blocks(normalize_section_text(content, name)))
        for name, content in sections.items()
    }
    used: set[str] = set()
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "")
        if section not in result or section == CHART_INTERPRETATION_SECTION:
            continue
        chart_names = [name for name in item.get("charts") or [] if name in charts]
        anchor = str(item.get("anchor") or "").strip() or None
        placement_note = str(item.get("note") or "").strip() or None
        for chart_name in chart_names:
            note = figure_notes.get(chart_name) or placement_note or fallback_chart_note(chart_name, data)
            block = _format_figure_block(chart_name, charts[chart_name], note)
            if not block:
                continue
            result[section] = _insert_chart_block(
                result[section],
                block,
                anchor=anchor,
                chart_name=chart_name,
            )
            used.add(chart_name)
    unused = list(placement.get("unused") or [])
    if not unused:
        omitted = set(placement.get("omitted") or [])
        unused = [name for name in charts if name not in used and name not in omitted]
    return result, unused


def build_chart_interpretation_section(
    unused_charts: list[str],
    charts: dict[str, str],
    figure_notes: dict[str, str] | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> str:
    """收录未嵌入正文的小节图表，采用研报式「图 + 图注」排版。"""
    figure_notes = figure_notes or {}
    data = data or {}
    items = [name for name in unused_charts if name in charts]
    if not items:
        return "_本次图表均已嵌入正文相关小节，无额外图表。_"
    lines = ["以下图表未在前文章节嵌入，供补充阅读。", ""]
    for name in items:
        note = figure_notes.get(name) or fallback_chart_note(name, data)
        lines.append(_format_figure_block(name, charts[name], note))
        lines.append("")
    return normalize_section_text("\n".join(lines).strip(), CHART_INTERPRETATION_SECTION)


def _format_inline_chart_block(
    chart_names: list[str],
    charts: dict[str, str],
    *,
    note: str | None = None,
    figure_notes: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    blocks: list[str] = []
    figure_notes = figure_notes or {}
    data = data or {}
    for name in chart_names:
        if name not in charts:
            continue
        caption_note = figure_notes.get(name) or (note if len(chart_names) == 1 else None) or fallback_chart_note(name, data)
        blocks.append(_format_figure_block(name, charts[name], caption_note))
    return "\n\n".join(blocks)


def _insert_chart_block(
    content: str,
    block: str,
    anchor: str | None = None,
    chart_name: str | None = None,
) -> str:
    content = content.strip()
    if not block:
        return content
    if _section_contains_chart_block(content, block):
        return content
    anchor_text = str(anchor or "").strip()
    if anchor_text:
        inserted = _insert_before_text(content, anchor_text, block)
        if inserted != content:
            return inserted
    if chart_name:
        hints = CHART_SUBHEADING_HINTS.get(chart_name, ())
        if hints:
            inserted = _insert_after_section_heading(content, hints, block)
            if inserted:
                return inserted
            inserted = _insert_before_related_paragraph(content, hints, block)
            if inserted:
                return inserted
    return _append_chart_block(content, block)


def _insert_before_text(content: str, anchor_text: str, block: str) -> str:
    paragraphs = re.split(r"\n\s*\n", content)
    for index, paragraph in enumerate(paragraphs):
        if anchor_text in paragraph:
            paragraphs.insert(index, block)
            return "\n\n".join(paragraphs).strip()
    return content


def _insert_after_section_heading(content: str, hints: tuple[str, ...], block: str) -> str | None:
    paragraphs = re.split(r"\n\s*\n", content)
    for index, paragraph in enumerate(paragraphs):
        lines = paragraph.splitlines()
        first_line = lines[0].strip() if lines else ""
        if not re.match(r"^#{1,6}\s+\S", first_line):
            continue
        if not any(hint in first_line or hint in paragraph for hint in hints):
            continue
        paragraphs.insert(index + 1, block)
        return "\n\n".join(paragraphs).strip()
    return None


def _insert_before_related_paragraph(content: str, hints: tuple[str, ...], block: str) -> str | None:
    paragraphs = re.split(r"\n\s*\n", content)
    for index, paragraph in enumerate(paragraphs):
        first_line = paragraph.splitlines()[0].strip() if paragraph.splitlines() else ""
        if re.match(r"^#{1,6}\s+\S", first_line):
            continue
        if any(hint in paragraph for hint in hints):
            paragraphs.insert(index, block)
            return "\n\n".join(paragraphs).strip()
    return None


def _insert_after_text(content: str, anchor_text: str, block: str) -> str:
    paragraphs = re.split(r"\n\s*\n", content)
    for index, paragraph in enumerate(paragraphs):
        if anchor_text in paragraph:
            paragraphs.insert(index + 1, block)
            return "\n\n".join(paragraphs).strip()
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if anchor_text in line:
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            lines[insert_at:insert_at] = ["", block]
            return "\n".join(lines).strip()
    return content


def _insert_after_subheading_hints(content: str, hints: tuple[str, ...], block: str) -> str | None:
    paragraphs = re.split(r"\n\s*\n", content)
    for index, paragraph in enumerate(paragraphs):
        lines = paragraph.splitlines()
        first_line = lines[0].strip() if lines else ""
        is_heading = bool(re.match(r"^#{1,6}\s+\S", first_line))
        matched = any(hint in paragraph for hint in hints)
        if not matched:
            continue
        if is_heading:
            insert_at = index + 1
            if insert_at < len(paragraphs):
                next_para = paragraphs[insert_at]
                next_first = next_para.splitlines()[0].strip() if next_para.splitlines() else ""
                if next_first and not re.match(r"^#{1,6}\s+\S", next_first):
                    insert_at += 1
            paragraphs.insert(insert_at, block)
            return "\n\n".join(paragraphs).strip()
        paragraphs.insert(index + 1, block)
        return "\n\n".join(paragraphs).strip()
    return None


def _section_contains_chart_block(content: str, block: str) -> bool:
    paths = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", block)
    if not paths:
        paths = re.findall(r'<img src="([^"]+)"', block)
    if not paths:
        return False
    return any(path in content for path in paths)


def _strip_embedded_chart_blocks(content: str) -> str:
    """移除旧版 HTML 图表块，便于重新嵌入 Markdown 图片。"""
    cleaned = re.sub(r"\n*<table width=\"100%\">.*?</table>\n*", "\n\n", content, flags=re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _chart_caption(name: str) -> str:
    return CHART_CAPTIONS.get(name, name.replace("_", " "))


def _format_chart_markdown(name: str, path: str) -> list[str]:
    return [_format_figure_block(name, path, CHART_BRIEF_NOTES.get(name, _chart_caption(name)))]


def _format_figure_block(chart_name: str, path: str, note: str | None = None) -> str:
    caption = _chart_caption(chart_name)
    safe_path = _normalize_chart_path(path)
    lines = [f"#### 图 · {caption}", "", f"![{caption}]({safe_path})", ""]
    caption_note = str(note or CHART_BRIEF_NOTES.get(chart_name) or "").strip()
    if caption_note:
        lines.append(f"**图注** {caption_note}")
    return "\n".join(lines).strip()


def fallback_chart_note(chart_name: str, data: dict[str, Any]) -> str:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    stock = str(data.get("order_book_id") or "目标标的")
    if chart_name == "price_volume":
        return (
            f"{stock} 最新收盘价 {fmt_num(technical.get('latest_close'))}，"
            f"20 日均量 {fmt_num(technical.get('avg_volume_20d'))}。"
            "图中可观察价格变动与成交量是否同步放大或缩量。"
        )
    if chart_name == "moving_averages":
        return (
            f"{stock} 收盘价 {fmt_num(technical.get('latest_close'))}，"
            f"MA20 {fmt_num(technical.get('ma20'))}，MA60 {fmt_num(technical.get('ma60'))}。"
            "可对照价格与均线位置判断短期/中期趋势强弱。"
        )
    if chart_name == "cumulative_return":
        return (
            f"{stock} 近 20 日收益 {fmt_pct(technical.get('return_20d'))}，"
            f"近 60 日收益 {fmt_pct(technical.get('return_60d'))}。"
            "累计收益曲线反映区间内趋势方向与波动幅度。"
        )
    if chart_name == "drawdown":
        return f"{stock} 回撤曲线展示区间内价格由高点回落的幅度，用于衡量阶段性下行风险。"
    if chart_name == "valuation_factors":
        return (
            f"{stock} 当前 PE(TTM) {fmt_num(factor.get('pe_ratio_ttm'))}，"
            f"PB(TTM) {fmt_num(factor.get('pb_ratio_ttm'))}，"
            f"股息率 {fmt_pct(factor.get('dividend_yield_ttm'))}。"
            "估值因子走势用于观察指标随时间的变化。"
        )
    if chart_name == "margin_balances":
        return f"{stock} 融资融券余额变化反映杠杆资金在该标的上的参与程度与方向。"
    if chart_name == "margin_activity":
        return f"{stock} 融资买入与融券卖出活动反映杠杆交易的短期活跃程度。"
    if chart_name in {"shibor_rates", "yield_curve_snapshot"}:
        return "利率环境变化会影响权益资产折现率与相对吸引力，需结合标的估值一并理解。"
    return CHART_BRIEF_NOTES.get(chart_name, f"{_chart_caption(chart_name)}。")


def _append_chart_block(content: str, block: str) -> str:
    return f"{content.rstrip()}\n\n{block}".strip()


def _insert_after_first_heading(content: str, block: str) -> str:
    """无 anchor 时，尽量插在章节首个小标题之后，而非整节末尾。"""
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+\S", line.strip()):
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            lines[insert_at:insert_at] = ["", block, ""]
            return "\n".join(lines).strip()
    return f"{content}\n\n{block}".strip()


def build_data_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "technical": data.get("technical"),
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "pit_financials": data.get("pit_financials"),
        "data_quality": build_data_quality_summary(data),
        "inventory": {},
    }
    series_keys = (
        "price",
        "price_change_rate",
        "turnover",
        "capital_flow",
        "securities_margin",
        "dividend",
        "shares",
        "suspended",
        "st_stock",
        "interbank_rate",
        "yield_curve",
        "factor_history",
    )
    for key in series_keys:
        value = data.get(key)
        if isinstance(value, dict):
            summary["inventory"][key] = _summarize_series(value, tail=8)
    return summary


def build_data_quality_summary(data: dict[str, Any]) -> dict[str, Any]:
    available: list[str] = []
    empty: list[str] = []
    for key, label in DATA_QUALITY_KEYS:
        value = data.get(key)
        row_count = int(value.get("row_count") or 0) if isinstance(value, dict) else 0
        if row_count > 0:
            available.append(label)
        else:
            empty.append(label)
    if empty:
        summary_line = f"{len(available)} 项可用；缺失 {', '.join(empty)}"
    else:
        summary_line = f"全部 {len(available)} 项数据源可用"
    return {
        "available": available,
        "empty": empty,
        "summary_line": summary_line,
    }


def _ordered_section_items(sections: dict[str, str], plan: dict[str, Any]) -> list[tuple[str, str]]:
    normalized = normalize_sections(sections)
    order = _plan_section_names(plan)
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for name in order:
        if name in normalized:
            items.append((name, normalized[name]))
            seen.add(name)
    for name, content in normalized.items():
        if name not in seen:
            items.append((name, content))
    return items


def _output_section_items(
    sections: dict[str, str],
    plan: dict[str, Any],
    charts: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    _ = charts
    return _ordered_section_items(sections, plan)


def _ordered_sections_dict(sections: dict[str, str], plan: dict[str, Any]) -> dict[str, str]:
    return dict(_ordered_section_items(sections, plan))


def _plan_section_names(plan: dict[str, Any]) -> list[str]:
    plan_sections = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    return [str(item.get("name")) for item in plan_sections if isinstance(item, dict) and item.get("name")]


def _format_chart_section(charts: dict[str, str]) -> list[str]:
    if not charts:
        return ["本次未生成图表。"]
    normalized = {name: _normalize_chart_path(path) for name, path in charts.items()}
    lines: list[str] = []
    used: set[str] = set()
    for group_name, names in CHART_GROUPS:
        items = [(name, normalized[name]) for name in names if name in normalized]
        if not items:
            continue
        lines.append(f"### {group_name}")
        lines.extend(_format_chart_grid(items))
        lines.append("")
        used.update(name for name, _ in items)
    remaining = [(name, normalized[name]) for name in normalized if name not in used]
    if remaining:
        lines.append("### 其他图表")
        lines.extend(_format_chart_grid(remaining))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines or ["本次未生成图表。"]


def _format_chart_section_html(charts: dict[str, str]) -> list[str]:
    if not charts:
        return ["<p>本次未生成图表。</p>"]
    normalized = {name: _normalize_chart_path(path) for name, path in charts.items()}
    parts: list[str] = []
    used: set[str] = set()
    for group_name, names in CHART_GROUPS:
        items = [(_chart_caption(name), normalized[name]) for name in names if name in normalized]
        if not items:
            continue
        parts.append(f"<h3 class=\"chart-group\">{html.escape(group_name)}</h3>")
        parts.append(chart_grid_html(items))
        used.update(name for name in names if name in normalized)
    remaining = [(_chart_caption(name), normalized[name]) for name in normalized if name not in used]
    if remaining:
        parts.append("<h3 class=\"chart-group\">其他图表</h3>")
        parts.append(chart_grid_html(remaining))
    return parts or ["<p>本次未生成图表。</p>"]


def _core_metric_table_html(data: dict[str, Any]) -> str:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    industry = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    margin = _latest_margin_snapshot(data)
    rows = [
        ("中信一级行业", _industry_label(industry)),
        ("最新收盘价", fmt_num(technical.get("latest_close"))),
        ("MA20", fmt_num(technical.get("ma20"))),
        ("MA60", fmt_num(technical.get("ma60"))),
        ("20 日收益率", fmt_pct(technical.get("return_20d"))),
        ("60 日收益率", fmt_pct(technical.get("return_60d"))),
        ("RSI14", fmt_num(technical.get("rsi14"))),
        ("20 日均量", fmt_num(technical.get("avg_volume_20d"))),
        ("PE(TTM)", fmt_num(factor.get("pe_ratio_ttm"))),
        ("PB(TTM)", fmt_num(factor.get("pb_ratio_ttm"))),
        ("PS(TTM)", fmt_num(factor.get("ps_ratio_ttm"))),
        ("股息率(TTM)", fmt_pct(factor.get("dividend_yield_ttm"))),
        ("总市值", fmt_num(factor.get("market_cap"))),
        ("融资余额", fmt_num(margin.get("margin_balance"))),
        ("融资买入额", fmt_num(margin.get("buy_on_margin_value"))),
    ]
    body = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>" for label, value in rows
    )
    return (
        '<table class="metrics"><thead><tr><th>指标</th><th>数值</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _format_chart_grid(items: list[tuple[str, str]]) -> list[str]:
    """Markdown 单列图片；双列表格内嵌图片在多数 IDE 预览中无法显示。"""
    lines: list[str] = []
    for name, path in items:
        lines.extend(_format_chart_markdown(name, path))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _normalize_chart_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").lstrip("./")
    if normalized.startswith(("http://", "https://", "data:")):
        return normalized
    prefix = "FinAgent/outputs/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    return normalized


def validation_passed(validation: dict[str, Any] | None) -> bool:
    if not validation:
        return True
    final_decision = str(validation.get("final_decision") or "")
    score = validation.get("score")
    try:
        score_value = int(float(score))
    except (TypeError, ValueError):
        score_value = 0
    action_items = validation.get("action_items") if isinstance(validation.get("action_items"), list) else []
    unsupported = validation.get("unsupported_claims") if isinstance(validation.get("unsupported_claims"), list) else []
    feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
    has_feedback = any(isinstance(v, list) and v for v in feedback.values())
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_rewrite = any(isinstance(v, dict) and v.get("decision") == "rewrite" for v in relevance.values())
    return (
        final_decision in {"pass", "pass_after_revision"}
        and score_value >= 70
        and not action_items
        and not unsupported
        and not has_feedback
        and not has_rewrite
    )


def validation_publish_banner(validation: dict[str, Any] | None) -> str | None:
    if validation_passed(validation):
        return None
    validation = validation or {}
    score = validation.get("score", "N/A")
    decision = validation.get("final_decision", "N/A")
    return (
        f"> **草稿状态**：验证评分 {score}，结论 `{decision}`。"
        " 本报告尚未通过验证 Agent 复核，请勿对外发布。"
    )


def _validation_meta(validation: dict[str, Any]) -> dict[str, Any]:
    action_items = validation.get("action_items") if isinstance(validation.get("action_items"), list) else []
    unsupported = validation.get("unsupported_claims") if isinstance(validation.get("unsupported_claims"), list) else []
    final_decision = str(validation.get("final_decision") or "")
    passed = validation_passed(validation)
    return {
        "validation_passed": passed,
        "publish_ready": passed,
        "validation_decision": final_decision or None,
        "validation_score": validation.get("score"),
        "validation_issue_count": len(action_items) + len(unsupported),
    }


def _summarize_series(value: dict[str, Any], *, tail: int) -> dict[str, Any]:
    rows = value.get("rows") if isinstance(value.get("rows"), list) else []
    return {
        "row_count": value.get("row_count", len(rows)),
        "columns": value.get("columns"),
        "net_buy_value_sum": value.get("net_buy_value_sum"),
        "recent_rows": rows[-tail:] if rows else [],
    }


def _core_metric_table(data: dict[str, Any]) -> list[str]:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    industry = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    margin = _latest_margin_snapshot(data)
    rows = [
        ("中信一级行业", _industry_label(industry)),
        ("最新收盘价", fmt_num(technical.get("latest_close"))),
        ("MA20", fmt_num(technical.get("ma20"))),
        ("MA60", fmt_num(technical.get("ma60"))),
        ("20 日收益率", fmt_pct(technical.get("return_20d"))),
        ("60 日收益率", fmt_pct(technical.get("return_60d"))),
        ("RSI14", fmt_num(technical.get("rsi14"))),
        ("20 日均量", fmt_num(technical.get("avg_volume_20d"))),
        ("PE(TTM)", fmt_num(factor.get("pe_ratio_ttm"))),
        ("PB(TTM)", fmt_num(factor.get("pb_ratio_ttm"))),
        ("PS(TTM)", fmt_num(factor.get("ps_ratio_ttm"))),
        ("股息率(TTM)", fmt_pct(factor.get("dividend_yield_ttm"))),
        ("总市值", fmt_num(factor.get("market_cap"))),
        ("融资余额", fmt_num(margin.get("margin_balance"))),
        ("融资买入额", fmt_num(margin.get("buy_on_margin_value"))),
    ]
    lines = ["| 指标 | 数值 |", "|---|---:|"]
    lines.extend(f"| {label} | {value} |" for label, value in rows)
    return lines


def _industry_label(industry: dict[str, Any]) -> str:
    for key, value in industry.items():
        if "industry" in str(key).lower() and value not in (None, ""):
            return str(value)
    for value in industry.values():
        if value not in (None, ""):
            return str(value)
    return MISSING_LABEL


def _latest_margin_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    margin = data.get("securities_margin")
    if not isinstance(margin, dict):
        return {}
    rows = margin.get("rows")
    if not isinstance(rows, list) or not rows:
        return {}
    latest = rows[-1]
    if not isinstance(latest, dict):
        return {}
    return latest
