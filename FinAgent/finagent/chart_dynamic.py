from __future__ import annotations

"""正文驱动的动态出图流水线。

流程：
1. ``chart_need_agent`` / ``local_chart_need`` — 读章节正文，决定需要哪些图
2. ``chart_plots.chart_agent`` — 已知 chart_key 的固定模板（走 ``chart_style``）
3. ``chart_codegen_agent`` — 按需生成 JSON 绘图规格（声明式“画图函数”）
4. ``execute_parametric_chart`` / ``render_dynamic_chart`` — 解释规格并渲染 PNG
5. ``chart_placement_*`` — 把图嵌入正文章节 + ``chart_figure_notes_agent`` 写图注
"""

import json
import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .data_registry import DATA_KEY_TO_ROWS, data_available_for_chart
from .llm_settings import has_llm_api_key
from .llm import llm_json
from .multi_report import (
    CHART_CAPTIONS,
    CHART_INTERPRETATION_SECTION,
    CHART_SUBHEADING_HINTS,
    DEFAULT_SECTION_CHART_CANDIDATES,
    MARKET_TECH_SECTION,
    extract_section_structure,
    suggest_section_for_chart,
)

KNOWN_CHART_KEYS = frozenset(CHART_CAPTIONS)
FALLBACK_TEMPLATE_KEYS = frozenset({"price_volume", "nav_curve", "moving_averages", "valuation_factors"})
MAX_CHARTS_PER_SECTION = 2


def dynamic_chart_pipeline(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    output_dir: Path,
    plan: dict[str, Any],
    markdown_base: Path,
    validation: dict[str, Any] | None = None,
    chart_agent_fn: Callable[..., dict[str, str]],
    prior_need: dict[str, Any] | None = None,
    replan_only: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    """正文驱动出图：need → 固定模板子集 / 参数化图 → 失败回退。"""
    validation = validation or {}
    if prior_need and replan_only:
        need = prior_need
        need["replan_only"] = True
    elif has_llm_api_key():
        need = chart_need_agent(data=data, sections=sections, plan=plan, validation=validation)
    else:
        need = local_chart_need(data=data, sections=sections, plan=plan)

    if replan_only and prior_need:
        prev_keys = _need_chart_keys(prior_need)
        new_keys = _need_chart_keys(need)
        if new_keys == prev_keys:
            need = prior_need

    fixed_keys = _collect_fixed_template_keys(need)
    meta: dict[str, Any] = {
        "need": need,
        "fixed_keys": sorted(fixed_keys),
        "parametric": [],
        "fallbacks": [],
        "errors": [],
    }

    if not has_llm_api_key():
        all_charts = chart_agent_fn(data=data, output_dir=output_dir)
        charts = {k: v for k, v in all_charts.items() if k in fixed_keys}
        meta["mode"] = "fixed_subset"
    else:
        charts = {}
        if fixed_keys:
            all_charts = chart_agent_fn(data=data, output_dir=output_dir, only_keys=fixed_keys)
            charts.update(all_charts)
        for spec in need.get("charts") or []:
            if not isinstance(spec, dict) or not spec.get("needed", True):
                continue
            chart_key = str(spec.get("chart_key") or "").strip()
            if chart_key in charts:
                continue
            if chart_key in KNOWN_CHART_KEYS:
                continue
            path, render_meta = render_dynamic_chart(
                spec,
                data=data,
                output_dir=output_dir,
                chart_agent_fn=chart_agent_fn,
            )
            if path:
                charts[chart_key] = path
                meta["parametric"].append({"chart_key": chart_key, **render_meta})
                continue
            fallback = render_meta.get("fallback") or closest_fallback_chart_key(item)
            meta["fallbacks"].append({"requested": chart_key, "used": fallback, "reason": render_meta.get("mode") or "parametric_failed"})
            if fallback not in charts:
                partial = chart_agent_fn(data=data, output_dir=output_dir, only_keys={fallback})
                charts.update(partial)

    charts = {
        name: _to_markdown_path(path, markdown_base)
        for name, path in charts.items()
    }
    meta["chart_count"] = len(charts)
    return charts, meta


def local_chart_need(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """无 API：按章节正文关键词 + 默认候选决定子集。"""
    _ = plan
    charts: list[dict[str, Any]] = []
    skip: list[dict[str, str]] = []
    used: set[str] = set()

    for section_name, candidates in DEFAULT_SECTION_CHART_CANDIDATES.items():
        if section_name == CHART_INTERPRETATION_SECTION or section_name not in sections:
            continue
        content = str(sections.get(section_name) or "")
        if not content.strip():
            continue
        structure = extract_section_structure({section_name: content}).get(section_name, [])
        picked = 0
        for chart_key in candidates:
            if picked >= MAX_CHARTS_PER_SECTION or chart_key in used:
                continue
            if not data_available_for_chart(chart_key, data):
                continue
            hints = CHART_SUBHEADING_HINTS.get(chart_key, ())
            if hints and not _text_matches_hints(content, hints, structure):
                skip.append({"chart_key": chart_key, "reason": f"{section_name} 正文未涉及相关主题"})
                continue
            anchor = _pick_anchor(content, hints, structure)
            charts.append(
                {
                    "chart_key": chart_key,
                    "caption": CHART_CAPTIONS.get(chart_key, chart_key),
                    "section": section_name,
                    "anchor": anchor,
                    "needed": True,
                    "reason": "本地规则：正文与图类型匹配",
                    "fallback_template": chart_key,
                }
            )
            used.add(chart_key)
            picked += 1

    if not charts and data_available_for_chart("price_volume", data):
        charts.extend(
            [
                {
                    "chart_key": "price_volume",
                    "caption": CHART_CAPTIONS["price_volume"],
                    "section": MARKET_TECH_SECTION if MARKET_TECH_SECTION in sections else next(iter(sections), MARKET_TECH_SECTION),
                    "anchor": "价格",
                    "needed": True,
                    "fallback_template": "price_volume",
                },
                {
                    "chart_key": "nav_curve",
                    "caption": CHART_CAPTIONS.get("nav_curve", "净值曲线"),
                    "section": MARKET_TECH_SECTION if MARKET_TECH_SECTION in sections else next(iter(sections), MARKET_TECH_SECTION),
                    "anchor": "走势",
                    "needed": True,
                    "fallback_template": "nav_curve",
                },
            ]
        )

    return {"charts": charts, "skip": skip, "source": "local"}


def chart_need_agent(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any],
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = local_chart_need(data=data, sections=sections, plan=plan)
    if not has_llm_api_key():
        return fallback

    structure = extract_section_structure(sections)
    inventory = {
        key: {"row_count": value.get("row_count") if isinstance(value, dict) else None}
        for key, value in data.items()
        if isinstance(value, dict) and "row_count" in value
    }
    catalog = [
        {"chart_key": key, "caption": caption, "keywords": ", ".join(CHART_SUBHEADING_HINTS.get(key, ())[:5])}
        for key, caption in CHART_CAPTIONS.items()
    ]
    try:
        result = llm_json(
            "你是 chart_need_agent。只返回 JSON。"
            "阅读各章节正文结构，决定需要哪些图支撑叙述；不需要的放入 skip。"
            "优先使用 catalog 中已有 chart_key（如 price_volume、nav_curve）；"
            "同一语义只保留一张；每张图需指定 section 与 anchor（正文真实短语/小节标题）。"
            "禁止要求未采集数据；量纲不可比的多指标不要同一图。",
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "section_structure": structure,
                    "data_inventory": inventory,
                    "chart_catalog": catalog,
                    "chart_quality_review": (validation or {}).get("chart_quality_review"),
                    "local_need": fallback,
                },
                ensure_ascii=False,
            )[:20000]
            + '\n返回 {"charts":[{"chart_key","caption","section","anchor","needed",true,"reason","fallback_template"}],'
            + '"skip":[{"chart_key","reason"}]}',
        )
        return _sanitize_chart_need(result, fallback, sections)
    except Exception as exc:
        fallback["need_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


def _data_inventory_for_codegen(data: dict[str, Any]) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for key, row_key in DATA_KEY_TO_ROWS.items():
        block = data.get(row_key) if isinstance(data.get(row_key), dict) else {}
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        columns: list[str] = []
        if rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())
        inventory[key] = {
            "row_count": block.get("row_count", len(rows)),
            "columns": columns[:20],
        }
    return inventory


def _load_chart_frame(data: dict[str, Any], data_key: str) -> pd.DataFrame | None:
    row_key = DATA_KEY_TO_ROWS.get(data_key, data_key)
    rows = data.get(row_key, {}).get("rows") if isinstance(data.get(row_key), dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    frame = pd.DataFrame(rows)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame


def _apply_chart_transform(frame: pd.DataFrame, y_fields: list[str], transform: str) -> pd.DataFrame:
    frame = frame.copy()
    transform = str(transform or "none")
    if not y_fields:
        return frame
    primary = y_fields[0]
    if transform == "normalize_base_1":
        base = frame[primary].iloc[0]
        if base and pd.notna(base) and base != 0:
            frame[primary] = frame[primary] / base
    elif transform == "cumulative":
        frame[primary] = pd.to_numeric(frame[primary], errors="coerce").fillna(0).cumsum()
    elif transform == "pct_change":
        frame[primary] = pd.to_numeric(frame[primary], errors="coerce").pct_change()
    elif transform == "rolling_mean_20":
        frame[primary] = pd.to_numeric(frame[primary], errors="coerce").rolling(20).mean()
    return frame


def chart_codegen_agent(spec: dict[str, Any], *, data: dict[str, Any]) -> dict[str, Any]:
    """按需生成参数化绘图规格（声明式“画图函数”，由 execute_parametric_chart 解释执行）。"""
    enriched = dict(spec)
    chart_key = str(enriched.get("chart_key") or "")
    template = str(enriched.get("fallback_template") or chart_key)
    if template in KNOWN_CHART_KEYS:
        enriched["fallback_template"] = template
        enriched["use_fixed"] = True
        return enriched

    if not has_llm_api_key():
        enriched.setdefault("chart_type", "line")
        enriched.setdefault("data_keys", ["price"])
        enriched.setdefault("y_fields", ["close"])
        enriched.setdefault("transform", "none")
        return enriched

    try:
        result = llm_json(
            "你是 chart_codegen_agent（按需画图 Agent）。只返回 JSON，不要写 Python 代码。"
            "为自定义 chart_key 生成参数化绘图规格；若与 catalog 已有 fixed 图语义等价，请设 fallback_template 为 catalog 中的 chart_key。"
            "chart_type 允许: line|bar|fill|hbar|dual_line。"
            "transform 允许: none|normalize_base_1|cumulative|pct_change|rolling_mean_20。"
            "data_keys/y_fields 必须来自 data_inventory；不同量纲不要放在同一 bar 图。"
            "title 用中文短标题。",
            json.dumps(
                {
                    "spec": spec,
                    "order_book_id": data.get("order_book_id"),
                    "data_inventory": _data_inventory_for_codegen(data),
                    "known_templates": sorted(KNOWN_CHART_KEYS),
                },
                ensure_ascii=False,
            )[:10000]
            + '\n返回 {"chart_key","chart_type","data_keys","y_fields","transform","title","ylabel","fallback_template"}',
        )
        if isinstance(result, dict):
            enriched.update({k: v for k, v in result.items() if v is not None})
    except Exception:
        pass
    enriched.setdefault("chart_type", "line")
    enriched.setdefault("data_keys", ["price"])
    enriched.setdefault("y_fields", ["close"])
    enriched.setdefault("transform", "none")
    return enriched


def execute_parametric_chart(spec: dict[str, Any], *, data: dict[str, Any], output_dir: Path) -> str | None:
    """将 chart_codegen_agent 的 JSON 规格渲染为 PNG（统一走 chart_style）。"""
    if spec.get("use_fixed") or spec.get("fallback_template") in KNOWN_CHART_KEYS:
        return None
    from .chart_style import (
        PALETTE,
        SERIES_COLORS,
        add_zero_line,
        chart_title,
        close_figure,
        label,
        new_figure,
        save_chart,
        setup_matplotlib,
        style_axes,
        style_legend,
        style_twin_axes,
    )

    setup_matplotlib()
    chart_key = re.sub(r"[^\w\-]+", "_", str(spec.get("chart_key") or "custom_chart"))[:48]
    data_keys = spec.get("data_keys") if isinstance(spec.get("data_keys"), list) else ["price"]
    data_key = str(data_keys[0] if data_keys else "price")
    frame = _load_chart_frame(data, data_key)
    if frame is None or frame.empty:
        return None

    y_fields = [str(f) for f in (spec.get("y_fields") or ["close"]) if str(f) in frame.columns]
    if not y_fields:
        numeric_cols = [c for c in frame.columns if c not in {"date", "quarter"} and pd.api.types.is_numeric_dtype(frame[c])]
        if not numeric_cols:
            return None
        y_fields = [str(numeric_cols[0])]

    for col in y_fields:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = _apply_chart_transform(frame, y_fields, str(spec.get("transform") or "none"))

    output_dir.mkdir(parents=True, exist_ok=True)
    stock = str(data.get("order_book_id") or "")
    title = str(spec.get("title") or spec.get("caption") or chart_key)
    if stock and not title.startswith(stock):
        title = chart_title(stock, chart_key, extra=title if title != chart_key else None)
    ylabel = str(spec.get("ylabel") or label(y_fields[0]))
    chart_type = str(spec.get("chart_type") or "line")

    try:
        x = frame["date"] if "date" in frame.columns else range(len(frame))
        if chart_type == "dual_line" and len(y_fields) >= 2:
            fig, ax1 = new_figure()
            ax1.plot(x, frame[y_fields[0]], color=PALETTE["primary"], linewidth=2, zorder=3, label=label(y_fields[0]))
            ax2 = ax1.twinx()
            second = y_fields[1]
            if second == "volume" and second in frame.columns:
                ax2.bar(x, frame[second], color=PALETTE["muted"], alpha=0.22, width=0.85, zorder=1)
                ax2.set_ylabel(label("volume"), color="#94A3B8", fontsize=9)
            else:
                ax2.plot(x, frame[second], color=PALETTE["accent"], linewidth=1.6, zorder=3, label=label(second))
                ax2.set_ylabel(label(second), color="#94A3B8", fontsize=9)
            style_axes(ax1, title=title, ylabel=label(y_fields[0]), date_axis="date" in frame.columns)
            style_twin_axes(ax2)
        elif chart_type == "hbar":
            labels = (
                frame["quarter"].astype(str)
                if "quarter" in frame.columns
                else (frame["date"].dt.date.astype(str) if "date" in frame.columns else [str(i) for i in range(len(frame))])
            )
            fig, ax = new_figure(figsize=(10.2, max(4.2, 0.45 * len(frame) + 2.2)))
            y_pos = range(len(frame))
            ax.barh(list(y_pos), frame[y_fields[0]], color=PALETTE["secondary"], alpha=0.88, height=0.58, zorder=2)
            ax.set_yticks(list(y_pos))
            ax.set_yticklabels(list(labels))
            ax.invert_yaxis()
            style_axes(ax, title=title, xlabel=ylabel)
        else:
            fig, ax = new_figure()
            if chart_type == "bar":
                colors = [PALETTE["up"] if v >= 0 else PALETTE["down"] for v in frame[y_fields[0]].fillna(0)]
                ax.bar(x, frame[y_fields[0]], color=colors, alpha=0.82, width=0.82, zorder=2)
                add_zero_line(ax)
            elif chart_type == "fill":
                ax.fill_between(x, frame[y_fields[0]], 0, color=PALETTE["negative"], alpha=0.28, zorder=2)
            else:
                for idx, field in enumerate(y_fields[:3]):
                    ax.plot(
                        x,
                        frame[field],
                        label=label(field),
                        color=PALETTE["secondary"] if idx == 0 else SERIES_COLORS[(idx + 1) % len(SERIES_COLORS)],
                        linewidth=1.7,
                        zorder=3,
                    )
                if len(y_fields) > 1:
                    style_legend(ax)
            style_axes(ax, title=title, ylabel=ylabel, date_axis="date" in frame.columns and chart_type != "hbar")

        path = output_dir / f"{chart_key}.png"
        save_chart(fig, path)
        close_figure(fig)
        if path.stat().st_size < 100:
            return None
        return str(path)
    except Exception:
        return None


def render_dynamic_chart(
    spec: dict[str, Any],
    *,
    data: dict[str, Any],
    output_dir: Path,
    chart_agent_fn: Callable[..., dict[str, str]],
) -> tuple[str | None, dict[str, Any]]:
    """统一出图入口：fixed 模板 → 参数化规格 → 最近似模板回退。"""
    meta: dict[str, Any] = {"spec": spec}
    enriched = chart_codegen_agent(spec, data=data)
    meta["enriched"] = enriched
    if enriched.get("use_fixed") or str(enriched.get("fallback_template") or "") in KNOWN_CHART_KEYS:
        template = str(enriched.get("fallback_template") or enriched.get("chart_key") or "")
        partial = chart_agent_fn(data=data, output_dir=output_dir, only_keys={template})
        path = partial.get(template)
        if path:
            meta["mode"] = "fixed_template"
            return path, meta
    path = execute_parametric_chart(enriched, data=data, output_dir=output_dir)
    if path:
        meta["mode"] = "parametric"
        return path, meta
    fallback = closest_fallback_chart_key(enriched)
    meta["mode"] = "fallback"
    meta["fallback"] = fallback
    partial = chart_agent_fn(data=data, output_dir=output_dir, only_keys={fallback})
    return partial.get(fallback), meta


def closest_fallback_chart_key(spec: dict[str, Any]) -> str:
    template = str(spec.get("fallback_template") or spec.get("chart_key") or "")
    if template in KNOWN_CHART_KEYS:
        return template
    transform = str(spec.get("transform") or "")
    if transform == "normalize_base_1":
        return "nav_curve"
    if transform == "cumulative_return":
        return "cumulative_return"
    data_keys = spec.get("data_keys") if isinstance(spec.get("data_keys"), list) else []
    if "factor_history" in data_keys:
        return "valuation_factors"
    if "securities_margin" in data_keys:
        return "margin_balances"
    if "capital_flow" in data_keys:
        return "capital_flow"
    if "interbank_rate" in data_keys or "yield_curve" in data_keys:
        return "shibor_rates"
    caption = str(spec.get("caption") or "")
    for key, hints in CHART_SUBHEADING_HINTS.items():
        if any(h in caption for h in hints):
            return key
    return "price_volume"


def build_placement_from_chart_need(need: dict[str, Any], charts: dict[str, str]) -> dict[str, Any]:
    placements: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in need.get("charts") or []:
        if not isinstance(item, dict) or not item.get("needed", True):
            continue
        chart_key = str(item.get("chart_key") or item.get("fallback_template") or "").strip()
        if chart_key not in charts or chart_key in used:
            continue
        section = str(item.get("section") or "").strip()
        if not section:
            continue
        placements.append(
            {
                "section": section,
                "charts": [chart_key],
                "anchor": str(item.get("anchor") or "").strip() or None,
                "note": str(item.get("caption") or "").strip() or None,
            }
        )
        used.add(chart_key)
    unused = [name for name in charts if name not in used]
    return {"placements": placements, "omitted": [], "unused": unused}


def _sanitize_chart_need(result: dict[str, Any], fallback: dict[str, Any], sections: dict[str, str]) -> dict[str, Any]:
    valid_sections = set(sections.keys()) - {CHART_INTERPRETATION_SECTION}
    charts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result.get("charts") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("needed", True):
            continue
        chart_key = str(item.get("chart_key") or item.get("fallback_template") or "").strip()
        if not chart_key or chart_key in seen:
            continue
        section = str(item.get("section") or "").strip()
        if section not in valid_sections:
            section = suggest_section_for_chart(chart_key, sections) or MARKET_TECH_SECTION
        if section not in valid_sections:
            continue
        seen.add(chart_key)
        charts.append(
            {
                "chart_key": chart_key,
                "caption": str(item.get("caption") or CHART_CAPTIONS.get(chart_key, chart_key)),
                "section": section,
                "anchor": str(item.get("anchor") or "").strip() or None,
                "needed": True,
                "reason": str(item.get("reason") or ""),
                "fallback_template": chart_key if chart_key in KNOWN_CHART_KEYS else str(item.get("fallback_template") or ""),
            }
        )
    if not charts:
        return fallback
    skip = result.get("skip") if isinstance(result.get("skip"), list) else fallback.get("skip", [])
    return {"charts": charts, "skip": skip, "source": "llm"}


def _collect_fixed_template_keys(need: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in need.get("charts") or []:
        if not isinstance(item, dict) or not item.get("needed", True):
            continue
        for candidate in (item.get("chart_key"), item.get("fallback_template")):
            key = str(candidate or "").strip()
            if key in KNOWN_CHART_KEYS:
                keys.add(key)
    return keys


def _need_chart_keys(need: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in need.get("charts") or []:
        if isinstance(item, dict) and item.get("needed", True):
            keys.add(str(item.get("chart_key") or ""))
    return keys


def _text_matches_hints(content: str, hints: tuple[str, ...], structure: list[dict[str, str]]) -> bool:
    if any(h in content for h in hints):
        return True
    return any(
        any(h in sub.get("heading", "") or h in sub.get("excerpt", "") for h in hints) for sub in structure
    )


def _pick_anchor(content: str, hints: tuple[str, ...], structure: list[dict[str, str]]) -> str | None:
    for sub in structure:
        heading = sub.get("heading", "")
        if any(h in heading for h in hints):
            return heading[:40]
    for hint in hints:
        if hint in content:
            return hint
    return hints[0] if hints else None


def _to_markdown_path(path: str, base_dir: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(base_dir.resolve())
    except Exception:
        rel = Path(path)
    return rel.as_posix()
