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

_FACTOR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "市盈率": ("pe_ratio_ttm",),
    "市净率": ("pb_ratio_ttm",),
    "市销率": ("ps_ratio_ttm",),
    "总市值": ("market_cap",),
    "毛利率": ("gross_profit_margin_ttm", "gross_margin"),
    "归母净利率": ("net_profit_parent_company_margin_ttm",),
    "净利率": ("net_profit_margin_ttm",),
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
