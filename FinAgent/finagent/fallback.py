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
) -> list[dict[str, Any]]:
    from .progress import info

    factor_values = factor_values or {}
    enriched: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {"rqdata": 0, "rqdata_factor": 0, "annual_report": 0, "missing": 0}
    for row in rows:
        values: dict[str, dict[str, Any]] = {}
        for field in FIELD_NAMES:
            value = row.get(field)
            if value is not None and not pd.isna(value):
                values[field] = {"value": value, "source": "rqdata"}
                source_counts["rqdata"] += 1
                continue
            factor_value = factor_values.get(row["year"], {}).get(field)
            if factor_value is not None and not pd.isna(factor_value):
                values[field] = {"value": factor_value, "source": "rqdata_factor"}
                source_counts["rqdata_factor"] += 1
                continue
            fallback_value = extract_field_value(annual_report_text, field)
            if fallback_value is None:
                values[field] = {"value": None, "source": "missing"}
                source_counts["missing"] += 1
            else:
                values[field] = {"value": fallback_value, "source": "annual_report"}
                source_counts["annual_report"] += 1
        clean = {key: row.get(key) for key in ("year", "quarter", "info_date", "rice_create_tm", "if_adjusted") if key in row}
        clean["fields"] = values
        enriched.append(clean)
    info(f"数据来源分布: rqdata={source_counts['rqdata']}, rqdata_factor={source_counts['rqdata_factor']}, "
         f"年报回退={source_counts['annual_report']}, 缺失={source_counts['missing']}")
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
