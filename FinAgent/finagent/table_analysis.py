"""报告表格结构识别、内容重复检测与保留决策（供 validation_agent 使用）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .chart_catalog import TABLE_CAPTIONS
from .narrative_plan import section_kind_for_name

_CAPTION_TO_KEY = {caption: key for key, caption in TABLE_CAPTIONS.items()}
_MECHANICAL_HEADING = re.compile(r"^#{1,6}\s+表\s*[·•]?\s*(.+?)\s*$")


def _mechanical_caption(line: str) -> str | None:
    stripped = str(line or "").strip()
    if not re.match(r"^#{1,6}\s", stripped) or "表" not in stripped:
        return None
    match = _MECHANICAL_HEADING.match(stripped)
    if match:
        return match.group(1).strip()
    fallback = re.search(r"表\s*[·•]?\s*(.+?)\s*$", stripped)
    return fallback.group(1).strip() if fallback else None
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")

TABLE_KEY_OWNER_KIND: dict[str, str] = {
    "industry_operating_peer_compare_table": "operating_quality",
    "industry_peer_compare_table": "valuation",
    "industry_valuation_compare_table": "valuation",
    "industry_profitability_compare_table": "valuation",
    "industry_growth_leverage_compare_table": "valuation",
    "margin_snapshot_table": "capital",
    "margin_period_table": "capital",
    "trading_activity_table": "capital",
    "share_structure_table": "capital",
    "funding_cost_table": "macro",
    "dividend_recent_table": "valuation",
    "latest_valuation_snapshot": "valuation",
    "latest_quality_snapshot": "operating_quality",
    "latest_liquidity_snapshot": "risk",
}


@dataclass
class ReportTable:
    table_id: str
    section: str
    caption: str
    source: str  # mechanical | llm
    layout: str  # vertical | horizontal | wide
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    info_score: int = 0
    line_start: int = 0
    line_end: int = 0
    table_key: str = ""

    def to_brief(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "section": self.section,
            "caption": self.caption,
            "source": self.source,
            "layout": self.layout,
            "headers": self.headers[:8],
            "row_count": max(0, len(self.rows) - 1),
            "col_count": len(self.headers),
            "info_score": self.info_score,
            "table_key": self.table_key or None,
        }


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_sep_row(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell) <= {"-", ":", " "} for cell in cells)


def classify_table_layout(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return "unknown"
    first = headers[0].strip()
    if first in {"维度", "统计维度"} and len(headers) >= 4:
        return "horizontal"
    if len(headers) >= 4 and any(re.search(r"20\d{2}", cell) for cell in headers[1:]):
        return "wide"
    if len(headers) <= 3 and first in {"指标", "项目", "维度", "统计日期", "除权除息日"}:
        return "vertical"
    return "horizontal" if len(headers) >= 4 else "vertical"


def compute_information_score(
    *,
    headers: list[str],
    rows: list[list[str]],
    source: str,
    caption: str,
    table_key: str,
    section: str,
    plan: dict[str, Any] | None,
) -> int:
    data_rows = [row for row in rows[1:] if row and not _is_sep_row(row)]
    cols = len(headers)
    non_empty = sum(
        1
        for row in data_rows
        for cell in row
        if str(cell).strip() not in ("", "—", "-", "N/A", "数据缺失")
    )
    score = non_empty * 3 + len(data_rows) * 6 + cols * 4
    if caption:
        score += 8
    preferred = TABLE_KEY_OWNER_KIND.get(table_key)
    if preferred and section_kind_for_name(section, plan) == preferred:
        score += 15
    elif table_key and preferred:
        if preferred == "operating_quality" and "经营" in section:
            score += 8
        elif preferred == "valuation" and any(token in section for token in ("估值", "基本面")):
            score += 8
        elif preferred == "capital" and any(token in section for token in ("资金", "两融", "融资")):
            score += 8
        elif preferred == "macro" and any(token in section for token in ("宏观", "利率")):
            score += 8
    return score


def _body_fingerprint(rows: list[list[str]]) -> str:
    parts: list[str] = []
    for row in rows:
        parts.extend(str(cell).strip().lower() for cell in row if str(cell).strip())
    return " ".join(parts)


def table_content_similarity(left: ReportTable, right: ReportTable) -> float:
    if left.caption and right.caption and left.caption == right.caption:
        return 1.0
    ha = "|".join(h.lower() for h in left.headers)
    hb = "|".join(h.lower() for h in right.headers)
    header_sim = SequenceMatcher(None, ha, hb).ratio() if ha and hb else 0.0
    metrics_left = {row[0].strip().lower() for row in left.rows[1:] if row and row[0].strip()}
    metrics_right = {row[0].strip().lower() for row in right.rows[1:] if row and row[0].strip()}
    if metrics_left and metrics_right:
        union = metrics_left | metrics_right
        metric_sim = len(metrics_left & metrics_right) / len(union) if union else 0.0
    else:
        metric_sim = SequenceMatcher(None, _body_fingerprint(left.rows), _body_fingerprint(right.rows)).ratio()
    layout_bonus = 0.08 if left.layout == right.layout else 0.0
    return min(1.0, 0.35 * header_sim + 0.57 * metric_sim + layout_bonus)


def tables_are_duplicate(left: ReportTable, right: ReportTable, *, threshold: float = 0.68) -> bool:
    if left.table_id == right.table_id:
        return False
    if left.caption and right.caption and left.caption == right.caption:
        return True
    if left.table_key and left.table_key == right.table_key:
        return True
    return table_content_similarity(left, right) >= threshold


def _parse_pipe_block(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            break
        cells = _split_row(stripped)
        if _is_sep_row(cells):
            i += 1
            continue
        rows.append(cells)
        i += 1
    return rows, i


def _extract_section_tables(section_name: str, content: str, *, id_prefix: str) -> list[ReportTable]:
    lines = str(content or "").splitlines()
    tables: list[ReportTable] = []
    seq = 0
    i = 0
    while i < len(lines):
        caption = _mechanical_caption(lines[i])
        if caption is not None:
            block_start = i
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            while i < len(lines):
                row = lines[i].strip()
                if row.startswith("|") and row.endswith("|"):
                    break
                i += 1
            if i >= len(lines):
                continue
            rows, i = _parse_pipe_block(lines, i)
            if len(rows) >= 2:
                headers = rows[0]
                table_key = _CAPTION_TO_KEY.get(caption, "")
                layout = classify_table_layout(headers, rows)
                seq += 1
                table_id = f"{id_prefix}-{seq}"
                info = compute_information_score(
                    headers=headers,
                    rows=rows,
                    source="mechanical",
                    caption=caption,
                    table_key=table_key,
                    section=section_name,
                    plan=None,
                )
                tables.append(
                    ReportTable(
                        table_id=table_id,
                        section=section_name,
                        caption=caption,
                        source="mechanical",
                        layout=layout,
                        headers=headers,
                        rows=rows,
                        info_score=info,
                        line_start=block_start,
                        line_end=i,
                        table_key=table_key,
                    )
                )
            continue
        stripped = lines[i].strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            block_start = i
            rows, i = _parse_pipe_block(lines, i)
            if len(rows) >= 2:
                headers = rows[0]
                caption = headers[0] if headers else f"未命名表{seq + 1}"
                layout = classify_table_layout(headers, rows)
                seq += 1
                table_id = f"{id_prefix}-{seq}"
                info = compute_information_score(
                    headers=headers,
                    rows=rows,
                    source="llm",
                    caption="",
                    table_key="",
                    section=section_name,
                    plan=None,
                )
                tables.append(
                    ReportTable(
                        table_id=table_id,
                        section=section_name,
                        caption=caption,
                        source="llm",
                        layout=layout,
                        headers=headers,
                        rows=rows,
                        info_score=info,
                        line_start=block_start,
                        line_end=i,
                    )
                )
            continue
        i += 1
    return tables


def extract_report_tables(sections: dict[str, str], *, plan: dict[str, Any] | None = None) -> list[ReportTable]:
    tables: list[ReportTable] = []
    for section_name, content in sections.items():
        section_tables = _extract_section_tables(section_name, content, id_prefix=section_name)
        for table in section_tables:
            table.info_score = compute_information_score(
                headers=table.headers,
                rows=table.rows,
                source=table.source,
                caption=table.caption,
                table_key=table.table_key,
                section=section_name,
                plan=plan,
            )
        tables.extend(section_tables)
    return tables


def _cluster_duplicates(tables: list[ReportTable]) -> list[list[ReportTable]]:
    parent = {table.table_id: table.table_id for table in tables}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, left in enumerate(tables):
        for right in tables[i + 1 :]:
            if tables_are_duplicate(left, right):
                union(left.table_id, right.table_id)

    groups: dict[str, list[ReportTable]] = {}
    for table in tables:
        groups.setdefault(find(table.table_id), []).append(table)
    return [group for group in groups.values() if len(group) >= 2]


def _owner_rank_boost(table: ReportTable, plan: dict[str, Any] | None) -> int:
    body = _body_fingerprint(table.rows)
    kind = section_kind_for_name(table.section, plan) or ""
    if any(token in body for token in ("融资余额", "融券余额", "两融", "融资买入")):
        if kind == "capital":
            return 25
        if kind == "macro":
            return -25
    if any(token in body for token in ("shibor", "国债", "股息率")):
        if kind == "macro":
            return 20
        if kind == "capital":
            return -10
    if table.table_key:
        preferred = TABLE_KEY_OWNER_KIND.get(table.table_key)
        if preferred and kind == preferred:
            return 30
    return 0


def analyze_table_duplicates(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """识别表格结构、检测内容重复，并给出保留信息量更大表的决策。"""
    tables = extract_report_tables(sections, plan=plan)
    duplicate_groups: list[dict[str, Any]] = []
    delete_ids: set[str] = set()
    section_feedback: dict[str, list[str]] = {}
    structural_feedback: list[dict[str, Any]] = []

    for group in _cluster_duplicates(tables):
        ranked = sorted(
            group,
            key=lambda item: (item.info_score + _owner_rank_boost(item, plan), item.info_score),
            reverse=True,
        )
        keep = ranked[0]
        drop = ranked[1:]
        for item in drop:
            delete_ids.add(item.table_id)

        reason_parts = [
            f"结构={keep.layout}",
            f"来源={keep.source}",
            f"info_score={keep.info_score}",
        ]
        if keep.caption:
            reason_parts.append(f"标题=表·{keep.caption}")

        group_payload = {
            "group_id": keep.table_id,
            "keep_id": keep.table_id,
            "keep_section": keep.section,
            "keep_caption": keep.caption or keep.headers[0] if keep.headers else "",
            "keep_layout": keep.layout,
            "keep_info_score": keep.info_score,
            "delete_ids": [item.table_id for item in drop],
            "members": [item.to_brief() for item in ranked],
            "reason": "；".join(reason_parts),
        }
        duplicate_groups.append(group_payload)

        preview = keep.caption or (keep.headers[0] if keep.headers else "同结构表")
        for item in drop:
            note = (
                f"与《{keep.section}》中「{preview}」内容重复（保留 info_score={keep.info_score} 的"
                f"{keep.layout}表，删本表 info_score={item.info_score}）；请整段删除该表及重复解读。"
            )
            section_feedback.setdefault(item.section, []).append(note)
            structural_feedback.append(
                {
                    "section": item.section,
                    "issue": "duplicate_table",
                    "keep_in": keep.section,
                    "keep_table_id": keep.table_id,
                    "delete_table_id": item.table_id,
                    "rewrite_sections": [item.section],
                    "suggestion": note,
                }
            )

    # 章内同 caption 机械表
    for section_name, content in sections.items():
        captions = [match.strip() for match in re.findall(r"####\s*表\s*[·•]\s*([^\n]+)", str(content or ""))]
        if len(captions) != len(set(captions)):
            dupes = sorted({c for c in captions if captions.count(c) > 1})
            note = f"本章重复出现相同机械表：{', '.join(dupes)}；请只保留 info_score 最高的一张。"
            section_feedback.setdefault(section_name, []).append(note)

    return {
        "table_inventory": [table.to_brief() for table in tables],
        "duplicate_groups": duplicate_groups,
        "delete_table_ids": sorted(delete_ids),
        "section_feedback": section_feedback,
        "structural_feedback": structural_feedback,
    }


def _remove_table_block_lines(lines: list[str], start: int, end: int) -> None:
    del lines[start:end]
    if start < len(lines) and start > 0 and not lines[start - 1].strip():
        if start >= len(lines) or not lines[start].strip():
            del lines[start - 1]


def apply_table_dedup(
    sections: dict[str, str],
    analysis: dict[str, Any],
    *,
    delete_ids: set[str] | None = None,
) -> dict[str, str]:
    """按分析结果删除重复表，保留信息量更大的版本。"""
    delete_ids = delete_ids or set(analysis.get("delete_table_ids") or [])
    if not delete_ids:
        return dict(sections)

    id_to_table: dict[str, ReportTable] = {}
    for table in extract_report_tables(sections):
        id_to_table[table.table_id] = table

    result = dict(sections)
    # 从后往前删，避免行号漂移
    removals: list[tuple[str, int, int]] = []
    for table_id in delete_ids:
        table = id_to_table.get(table_id)
        if not table:
            continue
        removals.append((table.section, table.line_start, table.line_end))

    for section_name in result:
        section_removals = [(s, e) for sec, s, e in removals if sec == section_name]
        if not section_removals:
            continue
        lines = str(result[section_name] or "").splitlines()
        for start, end in sorted(section_removals, key=lambda x: x[0], reverse=True):
            _remove_table_block_lines(lines, start, end)
        result[section_name] = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    return result


def duplicate_table_review(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """兼容旧入口：返回 section_feedback + structural_feedback。"""
    analysis = analyze_table_duplicates(sections, plan=plan)
    return {
        "table_inventory": analysis.get("table_inventory"),
        "duplicate_groups": analysis.get("duplicate_groups"),
        "section_feedback": analysis.get("section_feedback") or {},
        "structural_feedback": analysis.get("structural_feedback") or [],
    }
