"""正文驱动的图表/表格编排：Agent 或本地规则决定嵌入哪些视觉元素及 anchor。"""

from __future__ import annotations

import json
from typing import Any

from .chart_catalog import (
    CHART_CAPTIONS,
    CHART_INTERPRETATION_SECTION,
    CHART_SUBHEADING_HINTS,
    MARKET_TECH_SECTION,
    TABLE_ALL_KEYS,
    chart_caption,
    chart_key_allowed_for_placement,
    table_key_allowed_for_placement,
)
from .chart_dynamic import _pick_anchor, _text_matches_hints
from .data_registry import data_available_for_chart
from .llm import llm_json
from .llm_settings import has_llm_api_key
from .multi_report import (
    apply_chart_placement_fixes,
    extract_section_structure,
    local_chart_placement_review,
    suggest_section_for_chart,
)
from .plan_execution import (
    chart_candidates_for_plan_section,
    section_chart_limit_for_plan,
    section_table_limit_for_plan,
    table_candidates_for_plan_section,
)
from .table_blocks import table_caption, table_data_available


def resolve_section_visuals(
    *,
    sections: dict[str, str],
    charts: dict[str, str],
    data: dict[str, Any],
    plan: dict[str, Any] | None = None,
    blocked: set[str] | None = None,
    validation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """根据正文选择图表/表格 → 生成 placement → 规则校验与对齐修正。"""
    blocked = blocked or set()
    if has_llm_api_key():
        need = visual_need_agent(
            data=data,
            sections=sections,
            charts=charts,
            plan=plan,
            blocked=blocked,
            validation=validation,
        )
    else:
        need = local_visual_need(
            data=data,
            sections=sections,
            charts=charts,
            plan=plan,
            blocked=blocked,
        )

    from .runtime_prefs import pref_int

    placement = build_placement_from_visual_need(need, charts=charts, data=data, blocked=blocked)
    review: dict[str, Any] = {}
    max_rounds = pref_int("FINAGENT_CHART_PLACEMENT_MAX_ROUNDS", 2, minimum=1, maximum=5)
    for _ in range(max_rounds):
        review = local_chart_placement_review(
            placement,
            sections=sections,
            charts=charts,
            data=data,
            plan=plan,
        )
        placement = apply_chart_placement_fixes(
            placement,
            review,
            sections=sections,
            charts=charts,
            blocked=blocked,
            data=data,
            plan=plan,
        )
        issues = review.get("issues") if isinstance(review.get("issues"), list) else []
        if not issues:
            break
    meta = {"visual_need": need, "placement_review": review}
    return placement, meta


def local_visual_need(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    charts: dict[str, str],
    plan: dict[str, Any] | None = None,
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    """无 API：按 Plan 节名/kind/data 候选 + 正文关键词挑选图表与表格。"""
    blocked = blocked or set()
    visuals: list[dict[str, Any]] = []
    skip: list[dict[str, str]] = []
    used_charts: set[str] = set()
    used_tables: set[str] = set()

    for section_name in sections:
        if section_name == CHART_INTERPRETATION_SECTION:
            continue
        content = str(sections.get(section_name) or "")
        if not content.strip():
            continue
        structure = extract_section_structure({section_name: content}).get(section_name, [])
        chart_limit = section_chart_limit_for_plan(section_name, plan)
        table_limit = section_table_limit_for_plan(section_name, plan)
        chart_picked = 0
        table_picked = 0

        for table_key in table_candidates_for_plan_section(section_name, plan):
            if table_picked >= table_limit or table_key in used_tables:
                continue
            if not table_key_allowed_for_placement(table_key):
                skip.append({"visual_key": table_key, "kind": "table", "reason": "已禁用机械插入"})
                continue
            if not table_data_available(table_key, data):
                skip.append({"visual_key": table_key, "kind": "table", "reason": "数据不足"})
                continue
            hints = TABLE_SUBHEADING_HINTS.get(table_key, ())
            if hints and not _text_matches_hints(content, hints, structure):
                skip.append({"visual_key": table_key, "kind": "table", "reason": f"{section_name} 正文未涉及"})
                continue
            anchor = _pick_anchor(content, hints, structure)
            visuals.append(
                _visual_item(
                    visual_key=table_key,
                    kind="table",
                    section=section_name,
                    anchor=anchor,
                    reason="本地规则：Plan 候选表 + 正文匹配",
                )
            )
            used_tables.add(table_key)
            table_picked += 1

        for chart_key in chart_candidates_for_plan_section(section_name, plan):
            if chart_picked >= chart_limit or chart_key in used_charts or chart_key in blocked:
                continue
            if not chart_key_allowed_for_placement(chart_key):
                skip.append({"visual_key": chart_key, "kind": "chart", "reason": "已停用条形图，改由表格展示"})
                continue
            if chart_key not in charts:
                if not data_available_for_chart(chart_key, data):
                    skip.append({"visual_key": chart_key, "kind": "chart", "reason": "数据不足或未出图"})
                continue
            hints = CHART_SUBHEADING_HINTS.get(chart_key, ())
            if hints and not _text_matches_hints(content, hints, structure):
                skip.append({"visual_key": chart_key, "kind": "chart", "reason": f"{section_name} 正文未涉及"})
                continue
            anchor = _pick_anchor(content, hints, structure)
            visuals.append(
                _visual_item(
                    visual_key=chart_key,
                    kind="chart",
                    section=section_name,
                    anchor=anchor,
                    reason="本地规则：Plan 候选图 + 正文匹配",
                )
            )
            used_charts.add(chart_key)
            chart_picked += 1

    if not any(v.get("kind") == "chart" for v in visuals) and "price_volume" in charts:
        fallback_section = _fallback_chart_section(sections, plan)
        if fallback_section != CHART_INTERPRETATION_SECTION:
            visuals.append(
                _visual_item(
                    visual_key="price_volume",
                    kind="chart",
                    section=fallback_section,
                    anchor="价格",
                    reason="兜底：至少保留量价图",
                )
            )

    return {"visuals": visuals, "skip": skip, "source": "local"}


def _fallback_chart_section(sections: dict[str, str], plan: dict[str, Any] | None) -> str:
    if MARKET_TECH_SECTION in sections:
        return MARKET_TECH_SECTION
    for name in sections:
        if name == CHART_INTERPRETATION_SECTION:
            continue
        if "price_volume" in chart_candidates_for_plan_section(name, plan):
            return name
    return next(iter(sections), MARKET_TECH_SECTION)


def visual_need_agent(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    charts: dict[str, str],
    plan: dict[str, Any] | None = None,
    blocked: set[str] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = local_visual_need(
        data=data,
        sections=sections,
        charts=charts,
        plan=plan,
        blocked=blocked,
    )
    if not has_llm_api_key():
        return fallback

    blocked = blocked or set()
    structure = extract_section_structure(sections)
    chart_catalog = [
        {
            "visual_key": key,
            "kind": "chart",
            "caption": chart_caption(key),
            "keywords": ", ".join(CHART_SUBHEADING_HINTS.get(key, ())[:5]),
            "available": key in charts and key not in blocked,
        }
        for key in charts
        if key not in blocked
    ]
    table_catalog = [
        {
            "visual_key": key,
            "kind": "table",
            "caption": table_caption(key),
            "keywords": ", ".join(TABLE_SUBHEADING_HINTS.get(key, ())[:5]),
            "available": table_data_available(key, data),
        }
        for key in _all_table_keys()
        if table_key_allowed_for_placement(key)
    ]
    plan_sections = [
        {
            "name": spec.get("name"),
            "kind": spec.get("kind"),
            "data": spec.get("data"),
            "chart_candidates": list(chart_candidates_for_plan_section(str(spec.get("name") or ""), plan)),
        }
        for spec in (plan or {}).get("sections") or []
        if isinstance(spec, dict)
    ]
    try:
        result = llm_json(
            "你是 visual_need_agent。只返回 JSON。"
            "阅读各章节正文，决定需要哪些 chart（PNG）和 table（Markdown 表格）支撑叙述。"
            "优先选用 catalog 中 available=true 的项；正文未讨论的主题不要选。"
            "technical_snapshot_table 已禁用，不得选用；技术指标表由章节作者自行撰写。"
            "每张图/表需指定 section 与 anchor（正文真实小节标题或 **加粗小标题** 短语）。"
            "量纲不可比的多指标用 table 而非 bar 图；同一语义只保留一项。",
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "section_structure": structure,
                    "plan_sections": plan_sections,
                    "chart_catalog": chart_catalog,
                    "table_catalog": table_catalog,
                    "chart_quality_review": (validation or {}).get("chart_quality_review"),
                    "local_need": fallback,
                },
                ensure_ascii=False,
            )[:22000]
            + '\n返回 {"visuals":[{"visual_key","kind":"chart|table","section","anchor","needed":true,"reason"}],'
            + '"skip":[{"visual_key","kind","reason"}]}',
        )
        return _sanitize_visual_need(result, fallback, sections, charts, blocked, plan=plan)
    except Exception as exc:
        fallback["need_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


def build_placement_from_visual_need(
    need: dict[str, Any],
    *,
    charts: dict[str, str],
    data: dict[str, Any],
    blocked: set[str] | None = None,
) -> dict[str, Any]:
    from .runtime_prefs import pref_int

    blocked = blocked or set()
    max_embedded_charts = pref_int("FINAGENT_MAX_EMBEDDED_CHARTS", 10, minimum=2, maximum=20)
    placements: list[dict[str, Any]] = []
    used: set[str] = set()
    embedded_chart_count = 0
    for item in need.get("visuals") or []:
        if not isinstance(item, dict) or not item.get("needed", True):
            continue
        visual_key = str(item.get("visual_key") or item.get("chart_key") or "").strip()
        kind = str(item.get("kind") or "chart").strip()
        if not visual_key or visual_key in used or visual_key in blocked:
            continue
        if kind == "table" and not table_key_allowed_for_placement(visual_key):
            continue
        if kind == "chart" and embedded_chart_count >= max_embedded_charts:
            continue
        if kind == "table":
            if not table_data_available(visual_key, data):
                continue
        elif visual_key not in charts:
            continue
        section = str(item.get("section") or "").strip()
        if not section:
            continue
        placements.append(
            {
                "section": section,
                "charts": [visual_key],
                "anchor": str(item.get("anchor") or "").strip() or None,
                "note": None,
                "kind": kind,
            }
        )
        used.add(visual_key)
        if kind == "chart":
            embedded_chart_count += 1

    unused = [name for name in charts if name not in used and name not in blocked]
    return {"placements": placements, "omitted": sorted(blocked), "unused": unused}


def _visual_item(
    *,
    visual_key: str,
    kind: str,
    section: str,
    anchor: str | None,
    reason: str,
) -> dict[str, Any]:
    caption = table_caption(visual_key) if kind == "table" else chart_caption(visual_key)
    return {
        "visual_key": visual_key,
        "kind": kind,
        "caption": caption,
        "section": section,
        "anchor": anchor,
        "needed": True,
        "reason": reason,
    }


def _all_table_keys() -> set[str]:
    return {key for key in TABLE_ALL_KEYS if table_key_allowed_for_placement(key)}


# re-export for local_visual_need table hints
from .chart_catalog import DISABLED_PLACEMENT_TABLE_KEYS, TABLE_SUBHEADING_HINTS, chart_key_allowed_for_placement  # noqa: E402


def _sanitize_visual_need(
    result: dict[str, Any],
    fallback: dict[str, Any],
    sections: dict[str, str],
    charts: dict[str, str],
    blocked: set[str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid_sections = set(sections.keys()) - {CHART_INTERPRETATION_SECTION}
    visuals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result.get("visuals") or []:
        if not isinstance(item, dict) or not item.get("needed", True):
            continue
        visual_key = str(item.get("visual_key") or item.get("chart_key") or "").strip()
        if not visual_key or visual_key in seen or visual_key in blocked:
            continue
        if visual_key in DISABLED_PLACEMENT_TABLE_KEYS:
            continue
        kind = str(item.get("kind") or ("table" if visual_key in TABLE_ALL_KEYS else "chart")).strip()
        if kind == "chart" and not chart_key_allowed_for_placement(visual_key):
            continue
        if kind == "chart" and visual_key not in charts:
            continue
        if kind == "table" and visual_key not in TABLE_ALL_KEYS:
            continue
        section = str(item.get("section") or "").strip()
        if section not in valid_sections:
            section = suggest_section_for_chart(visual_key, sections, plan=plan) or _fallback_chart_section(sections, plan)
        if section not in valid_sections:
            continue
        seen.add(visual_key)
        visuals.append(
            {
                "visual_key": visual_key,
                "kind": kind,
                "caption": str(item.get("caption") or CHART_CAPTIONS.get(visual_key, visual_key)),
                "section": section,
                "anchor": str(item.get("anchor") or "").strip() or None,
                "needed": True,
                "reason": str(item.get("reason") or ""),
            }
        )
    if not visuals:
        return fallback
    skip = result.get("skip") if isinstance(result.get("skip"), list) else fallback.get("skip", [])
    return {"visuals": visuals, "skip": skip, "source": "llm"}
