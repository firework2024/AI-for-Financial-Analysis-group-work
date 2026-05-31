from __future__ import annotations

import re
from typing import Any

from .fields import FIELD_MAP
from .financial_analysis import consolidate_reviewed_signals
from .report_format import (
    DISCLAIMER,
    build_report_toc,
    dedupe_strings,
    disclaimer_lines,
    fmt_money,
    fmt_pct,
    fmt_table_num,
    format_generated_at,
    format_generated_at_iso,
    markdown_section,
    normalize_section_text,
    render_toc_markdown,
    toc_id_map,
    write_report,
)

ANNUAL_METRIC_KEYS = (
    "year",
    "revenue",
    "net_profit_parent_company",
    "cash_flow_from_operating_activities",
    "gross_margin",
    "cash_to_revenue",
    "cash_to_profit",
    "debt_to_assets",
    "roe",
    "free_cash_flow",
    "revenue_growth",
    "net_profit_parent_company_growth",
    "cash_flow_from_operating_activities_growth",
)

MISSING_FIELDS_PREVIEW = 8
_LLM_PREAMBLE = re.compile(
    r"^(?:好的[，,].*?投资总监.*?(?:\n\n|\n(?=#)))",
    re.DOTALL,
)
_CORE_CONCLUSION = re.compile(
    r"(?:^|\n)(#{1,3}\s*核心结论[^\n]*\n(?:.*?(?=\n#{1,3}\s|\Z)))",
    re.DOTALL,
)


def render_markdown(result: dict[str, Any], *, order_book_id: str | None = None) -> str:
    report = result["annual_report"]
    analysis = result["financial_analysis"]
    mda = result.get("mda") or {}
    director = normalize_section_text(result.get("investment_director"), "投资总监分析")
    executive = _extract_executive_summary(director)
    display_signals = analysis.get("display_signals") or consolidate_reviewed_signals(analysis.get("reviewed_signals") or [])
    provenance = build_field_provenance(result.get("financial_data") or [])

    data_notes = dedupe_strings(analysis.get("data_notes") or [])
    toc_entries = build_annual_toc_entries(data_notes)
    anchors = toc_id_map(toc_entries)

    source_lines = [
        f"- 股票代码：{report['stock_code']}",
        f"- 报告年份：{report.get('report_year', '—')}",
        *( [f"- 米筐代码：{order_book_id}"] if order_book_id else [] ),
        f"- 年报标题：{report['title']}",
        f"- PDF：{report['pdf_url']}",
        *( [f"- 本地 PDF：`{report['local_pdf']}`"] if report.get("local_pdf") else [] ),
        f"- MD&A 提取置信度：{mda.get('confidence', '—')}",
        f"- 生成时间：{format_generated_at()}",
    ]
    metrics_table = [
        "| 年份 | 营收 | 归母净利润 | 经营现金流 | 毛利率 | 收现比 | 净现比 | 资产负债率 | ROE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in analysis.get("metrics") or []:
        metrics_table.append(
            "| {year} | {revenue} | {np} | {ocf} | {gm} | {cr} | {cp} | {da} | {roe} |".format(
                year=metric["year"],
                revenue=fmt_money(metric.get("revenue")),
                np=fmt_money(metric.get("net_profit_parent_company")),
                ocf=fmt_money(metric.get("cash_flow_from_operating_activities")),
                gm=fmt_pct(metric.get("gross_margin"), style="ratio"),
                cr=fmt_table_num(metric.get("cash_to_revenue")),
                cp=fmt_table_num(metric.get("cash_to_profit")),
                da=fmt_pct(metric.get("debt_to_assets"), style="ratio"),
                roe=fmt_pct(metric.get("roe"), style="ratio"),
            )
        )

    lines = [
        f"# {report.get('sec_name') or report['stock_code']} 年报智能体分析",
        "",
        *render_toc_markdown(toc_entries),
        *markdown_section("年报来源", anchors["年报来源"], "\n".join(source_lines)),
        *markdown_section("执行摘要", anchors["执行摘要"], executive),
        *markdown_section("核心指标", anchors["核心指标"], "\n".join(metrics_table)),
        *markdown_section("审核后重点信号", anchors["审核后重点信号"], "\n".join(_format_display_signals(display_signals))),
        *markdown_section("投资总监分析", anchors["投资总监分析"], director),
        *markdown_section("MD&A 摘要", anchors["MD&A 摘要"], _mda_brief_text(mda)),
    ]
    if data_notes:
        lines.extend(markdown_section("数据说明", anchors["数据说明"], "\n".join(f"- {item}" for item in data_notes)))
    lines.extend(
        markdown_section("字段来源概览", anchors["字段来源概览"], "\n".join(_format_provenance_lines(provenance)))
    )
    lines.extend(markdown_section("免责声明", anchors["免责声明"], DISCLAIMER))
    return "\n".join(lines) + "\n"


def build_annual_toc_entries(data_notes: list[str] | None = None) -> list[dict[str, str]]:
    titles = [
        "年报来源",
        "执行摘要",
        "核心指标",
        "审核后重点信号",
        "投资总监分析",
        "MD&A 摘要",
    ]
    if data_notes:
        titles.append("数据说明")
    titles.extend(["字段来源概览", "免责声明"])
    return build_report_toc(titles)


def build_annual_json_payload(
    *,
    result: dict[str, Any],
    order_book_id: str | None,
    output_markdown: str,
    output_json: str,
) -> dict[str, Any]:
    """分层 JSON：与 multi-analyze 对称，避免 dump 全量 financial_data / MD&A。"""
    report = result["annual_report"]
    analysis = result["financial_analysis"]
    mda = result.get("mda") or {}
    director = normalize_section_text(result.get("investment_director"), "投资总监分析")
    data_notes = dedupe_strings(analysis.get("data_notes") or [])
    return {
        "meta": {
            "report_type": "annual_analyze",
            "stock_code": report.get("stock_code"),
            "sec_name": report.get("sec_name"),
            "report_year": report.get("report_year"),
            "order_book_id": order_book_id,
            "output_markdown": output_markdown,
            "output_json": output_json,
            "generated_at": format_generated_at_iso(),
            "pdf_url": report.get("pdf_url"),
            "local_pdf": report.get("local_pdf"),
            "mda_confidence": mda.get("confidence"),
        },
        "summary": director,
        "executive_summary": _extract_executive_summary(director),
        "mda": _mda_for_json(mda),
        "signals": {
            "reviewed_signals": analysis.get("reviewed_signals") or [],
            "display_signals": analysis.get("display_signals") or consolidate_reviewed_signals(analysis.get("reviewed_signals") or []),
            "positive_signals": analysis.get("positive_signals") or [],
            "negative_signals": analysis.get("negative_signals") or [],
            "key_risks": analysis.get("key_risks") or [],
            "data_notes": dedupe_strings(analysis.get("data_notes") or []),
            "articulation_checks": analysis.get("articulation_checks") or [],
            "mda_crosswalk": analysis.get("mda_crosswalk") or [],
        },
        "metrics": _slim_metrics(analysis.get("metrics") or []),
        "field_provenance": build_field_provenance(result.get("financial_data") or []),
        "table_of_contents": build_annual_toc_entries(data_notes),
    }


def build_field_provenance(financial_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provenance: list[dict[str, Any]] = []
    for row in financial_data:
        counts = {"rqdata": 0, "rqdata_factor": 0, "annual_report": 0, "missing": 0}
        missing_fields: list[str] = []
        for field, item in row.get("fields", {}).items():
            source = str(item.get("source") or "missing")
            if source not in counts:
                source = "missing"
            counts[source] += 1
            if source == "missing":
                label = FIELD_MAP[field].cn if field in FIELD_MAP else field
                missing_fields.append(label)
        provenance.append(
            {
                "year": row.get("year"),
                "counts": counts,
                "missing_fields": missing_fields[:MISSING_FIELDS_PREVIEW],
                "missing_fields_total": len(missing_fields),
            }
        )
    return provenance


def _format_display_signals(display_signals: list[dict[str, Any]]) -> list[str]:
    if not display_signals:
        return ["- 未形成可展示的结构化审核信号。"]
    lines: list[str] = []
    for item in display_signals:
        severity = str(item.get("severity") or "")
        category = str(item.get("category_cn") or item.get("category") or "")
        summary = str(item.get("summary") or "").strip().rstrip("。")
        evidence = str(item.get("evidence") or "").strip().rstrip("。")
        if not summary:
            continue
        head = f"**[{severity}/{category}]** {summary}"
        merged = int(item.get("merged_count") or 1)
        if evidence and merged <= 1 and evidence not in summary:
            lines.append(f"- {head}（{evidence}）。")
        else:
            lines.append(f"- {head}。")
    return lines or ["- 未形成可展示的结构化审核信号。"]


def _format_provenance_lines(provenance: list[dict[str, Any]]) -> list[str]:
    if not provenance:
        return ["- 暂无字段来源信息。"]
    lines: list[str] = []
    for row in provenance:
        counts = row.get("counts") or {}
        year = row.get("year")
        base = (
            f"- {year} 年：米筐 {counts.get('rqdata', 0)} 项，"
            f"因子回补 {counts.get('rqdata_factor', 0)} 项，"
            f"年报回退 {counts.get('annual_report', 0)} 项，"
            f"缺失 {counts.get('missing', 0)} 项"
        )
        missing = row.get("missing_fields") or []
        total_missing = int(row.get("missing_fields_total") or len(missing))
        if missing:
            suffix = "、".join(missing)
            if total_missing > len(missing):
                suffix += f" 等 {total_missing} 项"
            lines.append(f"{base}（{suffix}）。")
        else:
            lines.append(f"{base}。")
    return lines


def _extract_executive_summary(director: str) -> str:
    text = _LLM_PREAMBLE.sub("", director.strip()).strip()
    match = _CORE_CONCLUSION.search(text)
    if match:
        block = match.group(1).strip()
        block = re.sub(r"^#{1,3}\s*核心结论[^\n]*\n?", "", block).strip()
        if block:
            return block
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return "_暂无执行摘要。_"
    first = paragraphs[0]
    if len(first) > 600:
        return first[:600].rstrip() + "…"
    if len(paragraphs) >= 2 and len(first) < 200:
        combined = f"{first}\n\n{paragraphs[1]}"
        return combined[:600].rstrip() + ("…" if len(combined) > 600 else "")
    return first


def _mda_brief_text(mda: dict[str, Any]) -> str:
    text = normalize_section_text(mda.get("summary"), "MD&A 摘要")
    if text == "_本节暂无可用内容。_":
        return "_未能生成 MD&A 摘要。_"
    return text


def _mda_for_json(mda: dict[str, Any]) -> dict[str, Any]:
    brief = str(mda.get("summary") or "").strip()
    return {
        "confidence": mda.get("confidence"),
        "start_heading": mda.get("start_heading"),
        "end_heading": mda.get("end_heading"),
        "summary_brief": brief,
        "raw_preview_length": len(str(mda.get("raw_preview") or "")),
    }


def _slim_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slimmed: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        slimmed.append({key: metric.get(key) for key in ANNUAL_METRIC_KEYS if key in metric})
    return slimmed