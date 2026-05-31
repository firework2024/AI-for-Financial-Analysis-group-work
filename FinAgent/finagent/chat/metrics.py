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
    (("毛利率",), ("gross_margin",), "毛利率"),
    (("净资产收益率", "roe"), ("roe", "roe_ttm"), "ROE"),
]

_NARROW_HINTS = ("只要", "仅需", "仅", "就够", "别讲", "不要", "直接说", "直接给", "只说", "就答")
_ROW_META_KEYS = ("year", "quarter", "report_year", "sec_name")


def narrow_answer_requested(query: str) -> bool:
    q = str(query or "")
    return any(h in q for h in _NARROW_HINTS)


def resolve_focused_metrics(query: str, *, context: str = "") -> list[str]:
    """返回用户本轮关注的指标展示名（如「净利润」「总资产」），可多选。"""
    blob = f"{context} {query}".strip().lower()
    if not blob:
        return []
    found: list[str] = []
    for hints, _fields, label in _METRIC_SPECS:
        for hint in sorted(hints, key=len, reverse=True):
            if hint.lower() in blob:
                if label not in found:
                    found.append(label)
                break
    return found


def fields_for_metrics(labels: list[str]) -> list[str]:
    out: list[str] = []
    label_set = set(labels)
    for _hints, fields, label in _METRIC_SPECS:
        if label in label_set:
            for f in fields:
                if f not in out:
                    out.append(f)
    return out


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
    return [slim_financial_row(row, fields) for row in rows if isinstance(row, dict)]


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
    for row in annual.get("financial_data") or []:
        if not isinstance(row, dict):
            continue
        year = row.get("year") or row.get("report_year")
        point: dict[str, Any] = {"year": year}
        for field in fields:
            val = _field_value(row, field)
            if val is not None:
                point[field] = val
        if len(point) > 1:
            series.setdefault("annual", []).append(point)

    pit = stored.get("pit_financials_cache") or {}
    for row in (pit.get("rows") or [])[-6:]:
        if not isinstance(row, dict):
            continue
        year = row.get("year") or row.get("quarter")
        point: dict[str, Any] = {"year": year}
        for field in fields:
            val = _field_value(row, field)
            if val is not None:
                point[field] = val
        if len(point) > 1:
            series.setdefault("pit", []).append(point)

    if not series:
        return None
    return {
        "metrics": labels,
        "fields": fields,
        "by_source": series,
        "stock_code": stored.get("stock_code"),
        "sec_name": annual.get("sec_name"),
        "report_year": annual.get("report_year"),
    }
