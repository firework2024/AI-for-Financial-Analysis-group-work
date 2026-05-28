from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .fields import FIELD_DEFS, FIELD_NAMES


def apply_annual_report_fallback(rows: list[dict[str, Any]], annual_report_text: str) -> list[dict[str, Any]]:
    return apply_financial_fallbacks(rows, annual_report_text, {})


def apply_financial_fallbacks(
    rows: list[dict[str, Any]],
    annual_report_text: str,
    factor_values: dict[int, dict[str, float]] | None = None,
    *,
    annual_report_fields: dict[int, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """合并米筐原始数据、LYR 因子回补、年报回退为一个统一字段结构。

    Parameters
    ----------
    rows : list[dict]
        ``fetch_financials()`` 返回的原始行。
    annual_report_text : str
        年报纯文本（当前未使用，保留 API 兼容）。
    factor_values : dict[int, dict[str, float]] | None
        LYR 因子回补值，key 为年份。
    annual_report_fields : dict[int, dict[str, float]] | None
        从年报第八节财务报表中提取的字段值，
        ``{2025: {"revenue": 172054171890.91, ...}, 2024: {...}}``。
    """
    factor_values = factor_values or {}
    annual_report_fields = annual_report_fields or {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        row_year = row.get("year")
        values: dict[str, dict[str, Any]] = {}
        for field in FIELD_NAMES:
            value = row.get(field)
            if value is not None and not pd.isna(value):
                values[field] = {"value": value, "source": "rqdata"}
                continue
            factor_value = factor_values.get(row_year, {}).get(field)
            if factor_value is not None and not pd.isna(factor_value):
                values[field] = {"value": factor_value, "source": "rqdata_factor"}
                continue
            # 从年报财务报表中回退（按年份精确查找）
            report_val = None
            if row_year in annual_report_fields:
                report_val = annual_report_fields[row_year].get(field)
            if report_val is not None and not pd.isna(report_val):
                values[field] = {"value": report_val, "source": "annual_report"}
            else:
                values[field] = {"value": None, "source": "missing"}
        clean = {key: row.get(key) for key in ("year", "quarter", "info_date", "rice_create_tm", "if_adjusted") if key in row}
        clean["fields"] = values
        enriched.append(clean)
    return enriched


def extract_field_value(text: str, field: str) -> float | None:
    field_def = next((item for item in FIELD_DEFS if item.field == field), None)
    if not field_def:
        return None
    labels = (field_def.cn, *field_def.aliases)
    for label in labels:
        value = _extract_after_label(text, label)
        if value is not None:
            return value
    return None


def _extract_after_label(text: str, label: str) -> float | None:
    escaped = re.escape(label)
    pattern = re.compile(rf"{escaped}[^\n\r]{{0,80}}?(-?\d[\d,]*\.?\d*)")
    match = pattern.search(text)
    if not match:
        return None
    return _parse_number(match.group(1))


def _parse_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None
