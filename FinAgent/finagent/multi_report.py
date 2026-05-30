from __future__ import annotations

import html
import re
from typing import Any

from .chart_catalog import (
    CHART_BRIEF_NOTES,
    CHART_CAPTIONS,
    CHART_GROUPS,
    CHART_INTERPRETATION_SECTION,
    CHART_SUBHEADING_HINTS,
    DATA_LIMITATIONS_SECTION,
    DEFAULT_SECTION_CHART_CANDIDATES,
    DEFERRED_SECTIONS,
    MARKET_TECH_SECTION,
    MAX_INLINE_CHARTS_PER_SECTION,
    RISK_SECTION,
    SECTION_INLINE_CHART_LIMITS,
    SYNTHESIS_SECTION,
    chart_caption,
    fallback_chart_note,
)
from .data_capabilities import build_data_capability_inventory, filter_gap_notes
from .data_registry import COLLECTED_SERIES
from .report_format import (
    DISCLAIMER,
    MISSING_LABEL,
    build_report_toc,
    clean_chart_prose,
    dedupe_strings,
    disclaimer_lines,
    fmt_num,
    fmt_pct,
    format_generated_at,
    format_generated_at_iso,
    markdown_section,
    normalize_section_text,
    normalize_sections,
    render_toc_html,
    render_toc_markdown,
    toc_id_map,
)
from .report_html import chart_grid_html, markdown_to_html, wrap_html_document

CHART_COLUMNS = 2

_DATA_LIMITATION_BLOCK = re.compile(
    r"(?m)^#{3,4}\s*数据局限(?:说明)?\s*\n.*?(?=^#{1,4}\s|\Z)",
    re.DOTALL,
)

DATA_QUALITY_KEYS: tuple[tuple[str, str], ...] = tuple(COLLECTED_SERIES.items())


def strip_data_limitation_blocks(content: str) -> tuple[str, list[str]]:
    """移除章节内 #### 数据局限 块，返回清理后正文与提取的要点。"""
    collected: list[str] = []

    def _collect(match: re.Match[str]) -> str:
        block = match.group(0)
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ")):
                collected.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("#"):
                collected.append(stripped)
        return ""

    cleaned = _DATA_LIMITATION_BLOCK.sub(_collect, str(content or ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, collected


def strip_all_section_limitations(
    sections: dict[str, str],
    *,
    skip: frozenset[str] | set[str] | None = None,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """从各章正文剥离数据局限，供统一专章汇总。"""
    skip = skip or DEFERRED_SECTIONS
    cleaned: dict[str, str] = {}
    collected: dict[str, list[str]] = {}
    for name, content in sections.items():
        if name in skip:
            cleaned[name] = content
            continue
        body, notes = strip_data_limitation_blocks(str(content))
        cleaned[name] = body
        if notes:
            collected[name] = notes
    return cleaned, collected


def build_unified_data_limitations(
    data: dict[str, Any],
    collected_by_section: dict[str, list[str]] | None = None,
    validation: dict[str, Any] | None = None,
    charts: dict[str, str] | None = None,
) -> str:
    """生成统一的《数据覆盖与局限》章节。"""
    validation = validation or {}
    collected_by_section = collected_by_section or {}
    charts = charts or {}
    capability = build_data_capability_inventory(data, charts)
    quality = build_data_quality_summary(data)
    lines = [
        "### 数据覆盖概况",
        "",
        "| 数据源 | 状态 |",
        "|---|---|",
    ]
    for key, label in DATA_QUALITY_KEYS:
        value = data.get(key)
        row_count = int(value.get("row_count") or 0) if isinstance(value, dict) else 0
        status = "可用" if row_count > 0 else "缺失"
        detail = f"{row_count} 行" if row_count > 0 else "未返回有效记录"
        lines.append(f"| {label} | {status}（{detail}） |")

    lines.extend(["", "| 派生指标（由行情计算） | 状态 |", "|---|---|"])
    for name, info in capability.get("computed", {}).items():
        if info.get("available"):
            fields = ", ".join(info.get("technical_fields") or []) or "见图表"
            lines.append(f"| {name} | 可用（{fields}） |")
        else:
            lines.append(f"| {name} | 缺失（需有效行情） |")

    lines.extend(["", "### 缺失与影响", ""])
    if quality["empty"]:
        impact_map = {
            "资金流向": "无法评估主力/大单方向与资金博弈。",
            "行情": "无法开展价格与技术指标分析。",
            "两融": "无法评估杠杆资金参与度。",
            "因子历史": "无法观察估值与质量因子时序变化。",
            "年报三表": "无法展开盈利能力与杠杆分析。",
        }
        for label in quality["empty"]:
            impact = impact_map.get(label, "相关章节结论需降级为定性或省略。")
            lines.append(f"- **{label}**：{impact}")
    else:
        lines.append("- 本次采集的核心数据源均可用于正文分析。")

    merged_notes: list[str] = []
    for section_name, notes in collected_by_section.items():
        for note in notes:
            prefix = f"（{section_name}）" if section_name else ""
            merged_notes.append(f"{prefix}{note}".strip())
    for item in _string_list_from_validation(validation.get("missing_data_notes")):
        merged_notes.append(item)
    merged_notes = filter_gap_notes(dedupe_strings(merged_notes), data, charts)

    standard_gaps = [
        "未采集 Wind、新闻、券商盈利预测或管理层指引。",
        "未提供行业可比公司估值与景气度对比。",
        "未提供 PE/PB 等估值指标的历史分位数。",
        "pit_financials 仅采集年报 q4 口径，不含单季环比序列。",
        "未覆盖波动率、Beta 等扩展风险度量（回撤/MACD/RSI 已由行情派生）。",
    ]
    lines.extend(["", "### 分析口径与约束", ""])
    for note in merged_notes[:10]:
        lines.append(f"- {note}")
    for gap in standard_gaps:
        if gap not in merged_notes:
            lines.append(f"- {gap}")

    gap_review = validation.get("data_gap_review") if isinstance(validation.get("data_gap_review"), dict) else {}
    refresh_keys = gap_review.get("refresh_keys") or []
    if refresh_keys:
        lines.extend(
            [
                "",
                "### 可重试采集",
                "",
                f"- 以下数据源返回为空，验证 Agent 建议 `refresh_data` 重拉：{', '.join(refresh_keys)}。",
            ]
        )

    unsupported = _string_list_from_validation(validation.get("unsupported_claims"))
    if unsupported:
        lines.extend(["", "### 正文表述边界", ""])
        for item in unsupported[:6]:
            lines.append(f"- 报告不应依赖或暗示以下未采集来源：**{item}**")

    return normalize_section_text("\n".join(lines).strip(), DATA_LIMITATIONS_SECTION)


def _string_list_from_validation(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def analysis_section_names(plan: dict[str, Any]) -> list[str]:
    """综合判断之前的分析章节。"""
    names: list[str] = []
    stop = {SYNTHESIS_SECTION, RISK_SECTION, DATA_LIMITATIONS_SECTION, *DEFERRED_SECTIONS}
    for name in _plan_section_names(plan):
        if name in stop:
            break
        names.append(name)
    return names


def section_digest(sections: dict[str, str], plan: dict[str, Any], *, max_chars: int = 1200) -> list[dict[str, str]]:
    digest: list[dict[str, str]] = []
    for name in analysis_section_names(plan):
        excerpt = str(sections.get(name) or "").strip()
        if not excerpt or excerpt == "_本节暂无可用内容。_":
            continue
        digest.append({"section": name, "excerpt": excerpt[:max_chars]})
    return digest


def build_multi_toc_entries(
    plan: dict[str, Any],
    ordered_sections: list[tuple[str, str]],
) -> list[dict[str, str]]:
    titles = ["执行摘要", "核心指标速览"]
    titles.extend(name for name, _ in ordered_sections)
    titles.extend(["数据与工具说明", "免责声明"])
    return build_report_toc(titles)


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
    toc_entries = build_multi_toc_entries(plan, ordered_sections)
    anchors = toc_id_map(toc_entries)
    body = "\n\n".join(
        f'<a id="{anchors.get(name, name)}"></a>\n\n## {name}\n\n{content}'
        for name, content in ordered_sections
    )
    summary_text = normalize_section_text(summary, "执行摘要")
    quality = build_data_quality_summary(data)
    lines = [
        f"# {data['order_book_id']} 多智能体研究报告",
        "",
    ]
    banner = validation_publish_banner(validation)
    if banner:
        lines.extend([banner, ""])
    lines.extend(render_toc_markdown(toc_entries))
    lines.extend(markdown_section("执行摘要", anchors["执行摘要"], summary_text))
    lines.extend(markdown_section("核心指标速览", anchors["核心指标速览"], "\n".join(_core_metric_table(data))))
    lines.extend([body, ""])
    if not inline_charts and unused_charts is None:
        lines.extend(["## 可视化", *_format_chart_section(charts), ""])
    lines.extend(
        markdown_section(
            "数据与工具说明",
            anchors["数据与工具说明"],
            "\n".join(
                [
                    f"- 数据区间：{data['start_date']} 至 {data['end_date']}",
                    f"- 计划使用的米筐函数：{', '.join(plan.get('tools') or [])}",
                    f"- 数据执行日志：`{data.get('data_log') or data.get('python_script', '')}`",
                    f"- 数据质量：{quality['summary_line']}",
                    f"- 生成时间：{format_generated_at()}",
                ]
            ),
        )
    )
    lines.extend(markdown_section("免责声明", anchors["免责声明"], DISCLAIMER))
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
    toc_entries = build_multi_toc_entries(plan, ordered_sections)
    anchors = toc_id_map(toc_entries)
    summary_text = normalize_section_text(summary, "执行摘要")
    quality = build_data_quality_summary(data)
    title = f"{data['order_book_id']} 多智能体研究报告"
    parts = [f"<h1>{html.escape(title)}</h1>"]
    banner = validation_publish_banner(validation)
    if banner:
        parts.append(f'<aside class="draft-banner">{markdown_to_html(banner, in_section=True)}</aside>')

    parts.append(render_toc_html(toc_entries))

    parts.append(f'<h2 id="{html.escape(anchors["执行摘要"])}">执行摘要</h2>')
    parts.append(f'<section class="section-body">{markdown_to_html(summary_text, in_section=True)}</section>')

    parts.append(f'<h2 id="{html.escape(anchors["核心指标速览"])}">核心指标速览</h2>')
    parts.append(_core_metric_table_html(data))

    for name, content in ordered_sections:
        section_id = anchors.get(name) or html.escape(name)
        parts.append(f'<h2 id="{html.escape(section_id)}">{html.escape(name)}</h2>')
        parts.append(f'<section class="section-body">{markdown_to_html(content, in_section=True)}</section>')

    if not inline_charts and unused_charts is None:
        parts.append("<h2>可视化</h2>")
        parts.extend(_format_chart_section_html(charts))

    parts.append(f'<h2 id="{html.escape(anchors["数据与工具说明"])}">数据与工具说明</h2>')
    parts.append("<ul class=\"meta-list\">")
    parts.append(f"<li>数据区间：{html.escape(str(data['start_date']))} 至 {html.escape(str(data['end_date']))}</li>")
    parts.append(f"<li>计划使用的米筐函数：{html.escape(', '.join(plan.get('tools') or []))}</li>")
    parts.append(
        f"<li>数据执行日志：<code>{html.escape(str(data.get('data_log') or data.get('python_script') or ''))}</code></li>"
    )
    parts.append(f"<li>数据质量：{html.escape(quality['summary_line'])}</li>")
    parts.append(f"<li>生成时间：{html.escape(format_generated_at())}</li>")
    parts.append("</ul>")

    parts.append(
        f'<section class="disclaimer" id="{html.escape(anchors["免责声明"])}">'
        f"<h2>免责声明</h2><p>{html.escape(DISCLAIMER)}</p></section>"
    )
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
    chart_need: dict[str, Any] | None = None,
    chart_pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """分层 JSON：报告可读结构 + 数据摘要，避免整包 time-series rows。"""
    normalized = _ordered_sections_dict(sections, plan)
    validation = validation or {}
    toc_entries = build_multi_toc_entries(plan, list(normalized.items()))
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
        "table_of_contents": toc_entries,
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
        payload["omitted_charts"] = unused_charts
        payload["unused_charts"] = unused_charts
    if figure_notes:
        payload["figure_notes"] = figure_notes
    if chart_need is not None:
        payload["chart_need"] = chart_need
    if chart_pipeline is not None:
        payload["chart_pipeline"] = {
            k: chart_pipeline[k]
            for k in ("need", "mode", "fixed_keys", "parametric", "fallbacks", "errors", "chart_count")
            if k in chart_pipeline
        }
    return payload


def _inline_chart_limit(section: str) -> int:
    return SECTION_INLINE_CHART_LIMITS.get(section, MAX_INLINE_CHARTS_PER_SECTION)


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
        limit = _inline_chart_limit(section)
        picked = [name for name in candidates if name in allowed and name not in used][:limit]
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
        limit = _inline_chart_limit(section)
        for name in candidates:
            if count >= limit:
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


def extract_section_structure(sections: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """提取各章节 #### 小节标题与正文摘要，供图表编排匹配。"""
    structure: dict[str, list[dict[str, str]]] = {}
    for section_name, content in sections.items():
        if section_name == CHART_INTERPRETATION_SECTION:
            continue
        text = str(content or "").strip()
        if not text:
            continue
        subsections: list[dict[str, str]] = []
        current_heading = section_name
        current_excerpt: list[str] = []
        for paragraph in re.split(r"\n\s*\n", text):
            lines = paragraph.splitlines()
            first_line = lines[0].strip() if lines else ""
            if re.match(r"^#{1,6}\s+\S", first_line):
                if current_excerpt:
                    subsections.append(
                        {
                            "heading": current_heading,
                            "excerpt": " ".join(current_excerpt)[:480],
                        }
                    )
                current_heading = re.sub(r"^#{1,6}\s+", "", first_line).strip()
                current_excerpt = []
                body = "\n".join(lines[1:]).strip()
                if body:
                    current_excerpt.append(body[:320])
            else:
                current_excerpt.append(paragraph.strip()[:320])
        if current_excerpt:
            subsections.append(
                {
                    "heading": current_heading,
                    "excerpt": " ".join(current_excerpt)[:480],
                }
            )
        if not subsections:
            subsections.append({"heading": section_name, "excerpt": text[:480]})
        structure[section_name] = subsections
    return structure


def flatten_chart_placements(placement: dict[str, Any]) -> dict[str, Any]:
    """每张图单独一条 placement，便于逐图验证与修正。"""
    flat: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        anchor = str(item.get("anchor") or "").strip() or None
        note = str(item.get("note") or "").strip() or None
        for name in item.get("charts") or []:
            chart_name = str(name).strip()
            if not chart_name or chart_name in seen:
                continue
            seen.add(chart_name)
            flat.append({"section": section, "charts": [chart_name], "anchor": anchor, "note": note})
    result = dict(placement)
    result["placements"] = flat
    return result


def local_chart_placement_review(
    placement: dict[str, Any],
    *,
    sections: dict[str, str],
    charts: dict[str, str],
) -> dict[str, Any]:
    """规则校验：图标题语义与目标章节/小节正文是否匹配。"""
    issues: list[dict[str, Any]] = []
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        content = str(sections.get(section) or "")
        anchor = str(item.get("anchor") or "").strip()
        for chart_name in item.get("charts") or []:
            if chart_name not in charts:
                continue
            caption = _chart_caption(str(chart_name))
            hints = CHART_SUBHEADING_HINTS.get(str(chart_name), ())
            anchor_ok = bool(anchor and anchor in content)
            hint_ok = any(hint in content for hint in hints)
            heading_ok = any(hint in content for hint in hints if hint in content)
            structure = extract_section_structure({section: content}).get(section, [])
            subsection_ok = any(
                any(hint in sub.get("heading", "") or hint in sub.get("excerpt", "") for hint in hints)
                for sub in structure
            )
            if anchor_ok or hint_ok or subsection_ok:
                continue
            issues.append(
                {
                    "chart": str(chart_name),
                    "caption": caption,
                    "section": section,
                    "anchor": anchor or None,
                    "problem": f"图「{caption}」与章节「{section}」正文/小节标题缺乏语义匹配",
                    "suggested_section": suggest_section_for_chart(str(chart_name), sections),
                    "suggested_anchor": hints[0] if hints else None,
                }
            )
    score = max(0, 100 - 12 * len(issues))
    return {
        "passed": not issues,
        "score": score,
        "issues": issues,
        "final_decision": "pass" if not issues else "revise",
    }


def suggest_section_for_chart(chart_name: str, sections: dict[str, str]) -> str | None:
    hints = CHART_SUBHEADING_HINTS.get(chart_name, ())
    best_section: str | None = None
    best_score = 0
    for section_name, content in sections.items():
        if section_name == CHART_INTERPRETATION_SECTION:
            continue
        score = sum(1 for hint in hints if hint in content)
        structure = extract_section_structure({section_name: content}).get(section_name, [])
        score += sum(
            2
            for sub in structure
            if any(hint in sub.get("heading", "") or hint in sub.get("excerpt", "") for hint in hints)
        )
        if score > best_score:
            best_score = score
            best_section = section_name
    if best_section:
        return best_section
    for section_name, candidates in DEFAULT_SECTION_CHART_CANDIDATES.items():
        if chart_name in candidates and section_name in sections:
            return section_name
    return None


def apply_chart_placement_fixes(
    placement: dict[str, Any],
    review: dict[str, Any],
    *,
    sections: dict[str, str],
    charts: dict[str, str],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    """根据验证意见修正 placement（章节、anchor）。"""
    blocked = blocked or set()
    issue_map = {
        str(item.get("chart")): item
        for item in review.get("issues") or []
        if isinstance(item, dict) and item.get("chart")
    }
    fixed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        for chart_name in item.get("charts") or []:
            key = str(chart_name)
            if key not in charts or key in blocked or key in seen:
                continue
            issue = issue_map.get(key)
            section = str(item.get("section") or "").strip()
            anchor = str(item.get("anchor") or "").strip() or None
            note = str(item.get("note") or "").strip() or None
            if issue:
                suggested_section = str(issue.get("suggested_section") or "").strip()
                if suggested_section in sections:
                    section = suggested_section
                suggested_anchor = str(issue.get("suggested_anchor") or "").strip()
                if suggested_anchor and suggested_anchor in str(sections.get(section) or ""):
                    anchor = suggested_anchor
                elif suggested_anchor:
                    anchor = suggested_anchor
            fixed.append({"section": section, "charts": [key], "anchor": anchor, "note": note})
            seen.add(key)
    omitted = sorted({str(name) for name in (placement.get("omitted") or []) if str(name) in charts} | blocked)
    unused = [name for name in charts if name not in seen and name not in blocked]
    return {"placements": fixed, "omitted": omitted, "unused": unused}


def build_chart_catalog(charts: dict[str, str], blocked: set[str] | None = None) -> list[dict[str, str]]:
    blocked = blocked or set()
    catalog: list[dict[str, str]] = []
    for name in charts:
        if name in blocked:
            continue
        hints = CHART_SUBHEADING_HINTS.get(name, ())
        catalog.append(
            {
                "chart_name": name,
                "caption": _chart_caption(name),
                "keywords": ", ".join(hints[:6]),
            }
        )
    return catalog


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
    unused = [name for name in charts if name not in used and name not in set(placement.get("omitted") or [])]
    omitted = sorted({str(name) for name in (placement.get("omitted") or []) if str(name) in charts} | set(unused))
    return result, omitted


def finalize_inline_only_placement(
    placement: dict[str, Any],
    *,
    charts: dict[str, str],
    sections: dict[str, str],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    """尽量将全部图表内嵌到正文章节；无法安置的标记为 omitted，不生成附录章节。"""
    blocked = blocked or set()
    placement = fill_missing_section_placements(
        placement, charts=charts, sections=sections, blocked=blocked
    )
    placements: list[dict[str, Any]] = list(placement.get("placements") or [])
    used: set[str] = set()
    for item in placements:
        if not isinstance(item, dict):
            continue
        for name in item.get("charts") or []:
            key = str(name)
            if key in charts and key not in blocked:
                used.add(key)

    for chart_name in charts:
        if chart_name in blocked or chart_name in used:
            continue
        section = suggest_section_for_chart(chart_name, sections)
        if not section:
            for sec, candidates in DEFAULT_SECTION_CHART_CANDIDATES.items():
                if chart_name in candidates and sec in sections:
                    section = sec
                    break
        if not section:
            continue
        placements.append({"section": section, "charts": [chart_name], "anchor": None, "note": None})
        used.add(chart_name)

    omitted = sorted({str(name) for name in (placement.get("omitted") or []) if str(name) in charts} | blocked)
    unplaced = [name for name in charts if name not in used and name not in blocked]
    return {"placements": placements, "omitted": sorted(set(omitted) | set(unplaced)), "unused": []}


def prune_charts_dict(charts: dict[str, str], omitted: list[str] | set[str]) -> dict[str, str]:
    drop = set(omitted)
    return {name: path for name, path in charts.items() if name not in drop}


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


_chart_caption = chart_caption


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
        "index_benchmark",
        "turnover",
        "capital_flow",
        "block_trade",
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
    normalized = {name: content for name, content in normalized.items() if name != CHART_INTERPRETATION_SECTION}
    order = [name for name in _plan_section_names(plan) if name != CHART_INTERPRETATION_SECTION]
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
