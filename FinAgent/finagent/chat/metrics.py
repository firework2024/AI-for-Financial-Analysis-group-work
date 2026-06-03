"""对话中单指标聚焦：识别用户要的财报字段并裁剪证据。"""

from __future__ import annotations

import re
from typing import Any

# (中文触发词, 数据库字段, 展示名) — 长词优先匹配
_METRIC_SPECS: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    (("总资产", "资产总计", "资产规模", "资产合计"), ("total_assets",), "总资产"),
    (("总负债", "负债合计", "负债总额"), ("total_liabilities",), "总负债"),
    (
        ("归母净利润", "归属于母公司", "净利润", "净利"),
        ("net_profit_parent_company", "net_profit"),
        "净利润",
    ),
    (("营业收入", "营业总收入", "营收", "收入"), ("revenue", "operating_revenue"), "营业收入"),
    (
        ("经营现金流", "经营活动现金流", "现金流"),
        ("cash_flow_from_operating_activities",),
        "经营现金流",
    ),
    (("净资产", "股东权益", "归属于母公司股东权益"), ("equity_parent_company",), "净资产"),
    (("毛利率",), ("gross_margin", "gross_profit_margin_ttm"), "毛利率"),
    (("归母净利率",), ("net_profit_parent_company_margin_ttm",), "归母净利率"),
    (("净利率", "净利润率"), ("net_profit_margin_ttm",), "净利率"),
    (("净资产收益率", "roe"), ("roe", "roe_ttm"), "ROE"),
    (("资产负债率", "负债率"), ("debt_to_asset_ratio",), "资产负债率"),
    (("流动比率",), ("current_ratio",), "流动比率"),
    (("速动比率",), ("quick_ratio",), "速动比率"),
    (("营收增速", "收入增速", "营业收入增速"), ("operating_revenue_growth_ratio_ttm",), "营收增速"),
    (("净利润增速", "净利增速"), ("net_profit_growth_ratio_ttm", "net_profit_parent_company_growth_ratio_ttm"), "净利润增速"),
    (("营业利润增速",), ("operating_profit_growth_ratio_ttm",), "营业利润增速"),
    (("毛利润增速", "毛利增速"), ("gross_profit_growth_ratio_ttm",), "毛利润增速"),
    (
        ("市盈率", "pe(ttm)", "pe ratio", "动态市盈率"),
        ("pe_ratio_ttm",),
        "市盈率",
    ),
    (("市净率", "pb(ttm)"), ("pb_ratio_ttm",), "市净率"),
    (("市销率", "ps(ttm)"), ("ps_ratio_ttm",), "市销率"),
    (("总市值", "市值"), ("market_cap",), "总市值"),
]

_VALUATION_LABELS = frozenset({"市盈率", "市净率", "市销率", "总市值"})

# 对话 PIT/年报行：除 factor 字段名外，需拉取的原始列（用于逐年推算）
_LABEL_ROW_FIELDS: dict[str, tuple[str, ...]] = {
    "净利率": (
        "revenue",
        "operating_revenue",
        "net_profit",
        "net_profit_parent_company",
        "net_profit_margin_ttm",
        "net_profit_margin_pct",
    ),
    "归母净利率": (
        "revenue",
        "operating_revenue",
        "net_profit_parent_company",
        "net_profit_parent_company_margin_ttm",
        "net_profit_parent_company_margin_pct",
    ),
    "毛利率": (
        "revenue",
        "operating_revenue",
        "gross_profit",
        "cost_of_goods_sold",
        "gross_margin",
        "gross_profit_margin_ttm",
        "gross_profit_margin_pct",
    ),
    "ROE": (
        "net_profit_parent_company",
        "net_profit",
        "equity_parent_company",
        "roe",
        "roe_ttm",
    ),
    "资产负债率": ("total_assets", "total_liabilities", "debt_to_asset_ratio"),
    "流动比率": ("current_assets", "current_liabilities", "current_ratio"),
    "速动比率": ("current_assets", "current_liabilities", "inventory", "quick_ratio"),
    "营收增速": ("revenue", "operating_revenue", "operating_revenue_growth_ratio_ttm"),
    "净利润增速": (
        "net_profit",
        "net_profit_parent_company",
        "net_profit_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
    ),
    "营业利润增速": ("profit_from_operation", "operating_profit_growth_ratio_ttm"),
    "毛利润增速": (
        "gross_profit",
        "revenue",
        "operating_revenue",
        "cost_of_goods_sold",
        "gross_profit_growth_ratio_ttm",
    ),
    "经营现金流": ("cash_flow_from_operating_activities",),
    "营业收入": ("revenue", "operating_revenue"),
}

# 展示名 -> (分子, 分母, 输出字段, 乘数 scale, 特殊分子 gross|quick|None)
_DERIVED_ROW_RATIOS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str, float, str | None]] = {
    "净利率": (
        ("net_profit", "net_profit_parent_company"),
        ("revenue", "operating_revenue"),
        "net_profit_margin_pct",
        100.0,
        None,
    ),
    "归母净利率": (
        ("net_profit_parent_company",),
        ("revenue", "operating_revenue"),
        "net_profit_parent_company_margin_pct",
        100.0,
        None,
    ),
    "毛利率": ((), ("revenue", "operating_revenue"), "gross_profit_margin_pct", 100.0, "gross"),
    "资产负债率": (
        ("total_liabilities",),
        ("total_assets",),
        "debt_to_asset_ratio",
        100.0,
        None,
    ),
    "流动比率": (
        ("current_assets",),
        ("current_liabilities",),
        "current_ratio",
        1.0,
        None,
    ),
    "速动比率": ((), ("current_liabilities",), "quick_ratio", 1.0, "quick"),
}

# 展示名 -> (取值字段, 输出增速字段, 是否按毛利口径取值)
_GROWTH_SPECS: dict[str, tuple[tuple[str, ...], str, bool]] = {
    "营收增速": (("revenue", "operating_revenue"), "operating_revenue_growth_ratio_ttm", False),
    "净利润增速": (("net_profit", "net_profit_parent_company"), "net_profit_growth_ratio_ttm", False),
    "营业利润增速": (("profit_from_operation",), "operating_profit_growth_ratio_ttm", False),
    "毛利润增速": (("gross_profit",), "gross_profit_growth_ratio_ttm", True),
}

_FACTOR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "市盈率": ("pe_ratio_ttm",),
    "市净率": ("pb_ratio_ttm",),
    "市销率": ("ps_ratio_ttm",),
    "总市值": ("market_cap",),
    "毛利率": ("gross_profit_margin_ttm", "gross_margin", "gross_profit_margin_pct"),
    "归母净利率": ("net_profit_parent_company_margin_ttm", "net_profit_parent_company_margin_pct"),
    "净利率": ("net_profit_margin_ttm", "net_profit_margin_pct"),
    "ROE": ("roe_ttm", "roe"),
    "资产负债率": ("debt_to_asset_ratio",),
    "流动比率": ("current_ratio",),
    "速动比率": ("quick_ratio",),
    "营收增速": ("operating_revenue_growth_ratio_ttm",),
    "净利润增速": ("net_profit_growth_ratio_ttm", "net_profit_parent_company_growth_ratio_ttm"),
    "营业利润增速": ("operating_profit_growth_ratio_ttm",),
    "毛利润增速": ("gross_profit_growth_ratio_ttm",),
}

_NARROW_HINTS = ("只要", "仅需", "仅", "就够", "别讲", "不要", "直接说", "直接给", "只说", "就答")
_ROW_META_KEYS = ("year", "quarter", "report_year", "sec_name")


def narrow_answer_requested(query: str) -> bool:
    q = str(query or "")
    return any(h in q for h in _NARROW_HINTS)


def _blob_has_pe(blob: str) -> bool:
    if "市盈率" in blob or "pe(ttm)" in blob:
        return True
    return bool(re.search(r"(?<![a-z])pe(?![a-z])", blob))


def resolve_focused_metrics(query: str, *, context: str = "") -> list[str]:
    """返回用户本轮关注的指标展示名（如「净利润」「总资产」），可多选。"""
    q = str(query or "").strip()
    blob = f"{q} {context}".strip().lower()
    if not blob:
        return []
    found: list[str] = []
    if _blob_has_pe(blob):
        found.append("市盈率")
    for hints, _fields, label in _METRIC_SPECS:
        if label in found:
            continue
        for hint in sorted(hints, key=len, reverse=True):
            hl = hint.lower()
            if len(hl) <= 3 and hl in {"pe", "pb", "ps", "roe"}:
                if not re.search(rf"(?<![a-z]){re.escape(hl)}(?![a-z])", blob):
                    continue
            elif hl not in blob:
                continue
            found.append(label)
            break
    return found


def is_valuation_focus(labels: list[str] | None) -> bool:
    return bool(labels) and all(label in _VALUATION_LABELS for label in labels)


def slim_factor_block(factor: dict[str, Any] | None, labels: list[str]) -> dict[str, Any]:
    if not isinstance(factor, dict) or not factor:
        return {}
    if not labels:
        return dict(factor)
    keep: dict[str, Any] = {}
    for label in labels:
        for field in _FACTOR_FIELD_ALIASES.get(label, fields_for_metrics([label])):
            if field in factor and factor[field] is not None:
                keep[field] = factor[field]
    return keep


def extract_valuation_facts(
    live_by_stock: dict[str, Any],
    labels: list[str],
    *,
    sec_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not live_by_stock or not labels:
        return None
    rows: list[dict[str, Any]] = []
    for code, live in live_by_stock.items():
        if not isinstance(live, dict):
            continue
        factor = slim_factor_block(live.get("factor"), labels)
        if not factor and "市盈率" in labels:
            quote = live.get("quote") if isinstance(live.get("quote"), dict) else {}
            pe = quote.get("pe_ttm")
            if pe is not None:
                factor = {"pe_ratio_ttm": pe, "pe_ratio_ttm_source": "eastmoney_quote"}
        if not factor:
            continue
        rows.append(
            {
                "stock_code": code,
                "sec_name": (sec_names or {}).get(code) or live.get("sec_name"),
                "as_of": live.get("end_date") or live.get("as_of"),
                "source": live.get("source"),
                **factor,
            }
        )
    if not rows:
        return None
    return {"metrics": labels, "stocks": rows}


def fields_for_metrics(labels: list[str]) -> list[str]:
    out: list[str] = []
    label_set = set(labels)
    for _hints, fields, label in _METRIC_SPECS:
        if label in label_set:
            for f in fields:
                if f not in out:
                    out.append(f)
    for label in labels:
        for f in _LABEL_ROW_FIELDS.get(label, ()):
            if f not in out:
                out.append(f)
    return out


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _scaled_ratio(numerator: Any, denominator: Any, *, scale: float = 100.0, precision: int = 2) -> float | None:
    num = _safe_float(numerator)
    den = _safe_float(denominator)
    if num is None or den is None or den == 0:
        return None
    return round(scale * num / den, precision)


def _percent_ratio(numerator: Any, denominator: Any) -> float | None:
    return _scaled_ratio(numerator, denominator, scale=100.0, precision=2)


def _growth_ratio(current: Any, previous: Any) -> float | None:
    cur = _safe_float(current)
    prev = _safe_float(previous)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev), 4)


def _average_equity(current: Any, previous: Any) -> float | None:
    cur = _safe_float(current)
    prev = _safe_float(previous)
    if cur is None or cur <= 0:
        return None
    if prev is None or prev <= 0:
        return cur
    return (cur + prev) / 2


def _row_year_key(row: dict[str, Any]) -> tuple[int, str]:
    year = row.get("year") or row.get("report_year") or 0
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = 0
    return year, str(row.get("quarter") or "")


def _first_field_value(row: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        val = _field_value(row, field)
        if val is not None:
            return val
    return None


def _gross_profit_from_row(row: dict[str, Any]) -> float | None:
    direct = _first_field_value(row, ("gross_profit",))
    if direct is not None:
        return _safe_float(direct)
    revenue = _first_field_value(row, ("revenue", "operating_revenue"))
    cost = _first_field_value(row, ("cost_of_goods_sold",))
    if revenue is not None and cost is not None:
        rev_f, cost_f = _safe_float(revenue), _safe_float(cost)
        if rev_f is not None and cost_f is not None:
            return rev_f - cost_f
    return None


def _quick_assets_from_row(row: dict[str, Any]) -> float | None:
    current_assets = _first_field_value(row, ("current_assets",))
    if current_assets is None:
        return None
    assets_f = _safe_float(current_assets)
    if assets_f is None:
        return None
    inventory = _first_field_value(row, ("inventory",))
    inv_f = _safe_float(inventory) if inventory is not None else 0.0
    return assets_f - (inv_f or 0.0)


def _metric_amount(row: dict[str, Any], fields: tuple[str, ...], *, gross: bool = False) -> float | None:
    if gross:
        return _gross_profit_from_row(row)
    value = _first_field_value(row, fields)
    return _safe_float(value) if value is not None else None


def _append_derived_row_metrics(point: dict[str, Any], row: dict[str, Any], labels: list[str]) -> None:
    """用 PIT/年报原始列按年推算比率，避免仅有 factor TTM 而无历史序列。"""
    label_set = set(labels)
    for label, (num_fields, den_fields, out_field, scale, special) in _DERIVED_ROW_RATIOS.items():
        if label not in label_set:
            continue
        if point.get(out_field) is not None:
            continue
        if special == "gross":
            numerator = _gross_profit_from_row(row)
        elif special == "quick":
            numerator = _quick_assets_from_row(row)
        else:
            numerator = _first_field_value(row, num_fields)
        denominator = _first_field_value(row, den_fields)
        row_precision = 4 if scale == 1.0 else 2
        value = _scaled_ratio(numerator, denominator, scale=scale, precision=row_precision)
        if value is not None:
            point[out_field] = value
            point[f"{out_field}_source"] = "derived_pit_row"


def _append_derived_roe(
    point: dict[str, Any],
    row: dict[str, Any],
    prev_row: dict[str, Any] | None,
    labels: list[str],
) -> None:
    if "ROE" not in labels:
        return
    if point.get("roe_ttm") is not None or point.get("roe") is not None:
        return
    profit = _first_field_value(row, ("net_profit_parent_company", "net_profit"))
    equity = _first_field_value(row, ("equity_parent_company",))
    prev_equity = _first_field_value(prev_row, ("equity_parent_company",)) if prev_row else None
    avg_equity = _average_equity(equity, prev_equity)
    roe = _scaled_ratio(profit, avg_equity, scale=1.0, precision=4)
    if roe is not None:
        point["roe_ttm"] = roe
        point["roe_ttm_source"] = "derived_pit_row"


def _append_derived_growth(
    point: dict[str, Any],
    row: dict[str, Any],
    prev_row: dict[str, Any] | None,
    labels: list[str],
) -> None:
    if prev_row is None:
        return
    label_set = set(labels)
    for label, (value_fields, out_field, gross) in _GROWTH_SPECS.items():
        if label not in label_set:
            continue
        if point.get(out_field) is not None:
            continue
        current = _metric_amount(row, value_fields, gross=gross)
        previous = _metric_amount(prev_row, value_fields, gross=gross)
        growth = _growth_ratio(current, previous)
        if growth is not None:
            point[out_field] = growth
            point[f"{out_field}_source"] = "derived_pit_yoy"
        if label == "净利润增速" and point.get("net_profit_parent_company_growth_ratio_ttm") is None:
            parent_cur = _metric_amount(row, ("net_profit_parent_company",), gross=False)
            parent_prev = _metric_amount(prev_row, ("net_profit_parent_company",), gross=False)
            parent_growth = _growth_ratio(parent_cur, parent_prev)
            if parent_growth is not None:
                point["net_profit_parent_company_growth_ratio_ttm"] = parent_growth
                point["net_profit_parent_company_growth_ratio_ttm_source"] = "derived_pit_yoy"


def _enrich_financial_series(
    points: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    labels: list[str],
) -> list[dict[str, Any]]:
    if not points:
        return points
    paired = sorted(zip(raw_rows, points), key=lambda item: _row_year_key(item[0]))
    enriched: list[dict[str, Any]] = []
    for index, (row, point) in enumerate(paired):
        prev_row = paired[index - 1][0] if index > 0 else None
        _append_derived_roe(point, row, prev_row, labels)
        _append_derived_growth(point, row, prev_row, labels)
        enriched.append(point)
    return enriched


def _build_points_from_rows(
    rows: list[dict[str, Any]],
    fields: list[str],
    labels: list[str],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    raw_matched: list[dict[str, Any]] = []
    for row in rows:
        point = _build_financial_point(row, fields, labels)
        if point is not None:
            points.append(point)
            raw_matched.append(row)
    return _enrich_financial_series(points, raw_matched, labels)


def _row_has_metric_facts(point: dict[str, Any]) -> bool:
    meta = set(_ROW_META_KEYS)
    return any(key not in meta and point.get(key) is not None for key in point)


def _build_financial_point(row: dict[str, Any], fields: list[str], labels: list[str]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    point: dict[str, Any] = {}
    for key in _ROW_META_KEYS:
        if key in row and row[key] is not None:
            point[key] = row[key]
    for field in fields:
        val = _field_value(row, field)
        if val is not None:
            point[field] = val
    _append_derived_row_metrics(point, row, labels)
    if not _row_has_metric_facts(point):
        return None
    return point


def _field_value(row: dict[str, Any], field: str) -> Any:
    if field in row and row[field] is not None:
        return row[field]
    nested = row.get("fields")
    if isinstance(nested, dict) and field in nested:
        item = nested[field]
        if isinstance(item, dict):
            return item.get("value")
        return item
    metric = row.get("metric_snapshot")
    if isinstance(metric, dict) and field in metric:
        return metric[field]
    return None


def slim_financial_row(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    slim: dict[str, Any] = {}
    for key in _ROW_META_KEYS:
        if key in row and row[key] is not None:
            slim[key] = row[key]
    for field in fields:
        val = _field_value(row, field)
        if val is not None:
            slim[field] = val
    return slim


def filter_financial_rows(rows: list[dict[str, Any]], labels: list[str]) -> list[dict[str, Any]]:
    fields = fields_for_metrics(labels)
    if not fields:
        return rows
    return _build_points_from_rows(rows, fields, labels)


def extract_financial_facts(
    stored: dict[str, Any] | None,
    labels: list[str],
) -> dict[str, Any] | None:
    """从 data_api.stored 抽出结构化事实，供 LLM 直接引用。"""
    if not stored or not labels:
        return None
    fields = fields_for_metrics(labels)
    if not fields:
        return None

    series: dict[str, list[dict[str, Any]]] = {}
    annual = stored.get("annual_report") or {}
    annual_points = _build_points_from_rows(annual.get("financial_data") or [], fields, labels)
    if annual_points:
        series["annual"] = annual_points

    pit = stored.get("pit_financials_cache") or {}
    pit_points = _build_points_from_rows((pit.get("rows") or [])[-6:], fields, labels)
    if pit_points:
        series["pit"] = pit_points

    if not series:
        return None
    derived_notes: list[str] = []
    label_set = set(labels)
    if label_set & frozenset(_DERIVED_ROW_RATIOS):
        derived_notes.append(
            "比率类：行内无现成 TTM/因子字段时，按同年三表原始列推算；带 % 后缀为百分数，流动/速动比率为倍数。"
        )
    if label_set & (frozenset(_GROWTH_SPECS) | frozenset({"ROE"})):
        derived_notes.append("增速/ROE：与上一年同口径行同比推算（首年无增速）；ROE 分母为归母净资产期初期末均值。")
    return {
        "metrics": labels,
        "fields": fields,
        "by_source": series,
        "stock_code": stored.get("stock_code"),
        "sec_name": annual.get("sec_name"),
        "report_year": annual.get("report_year"),
        "derived_notes": derived_notes,
    }
