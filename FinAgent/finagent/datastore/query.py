"""根据用户问题从数据库检索相关原始数据片段。"""

from __future__ import annotations

import re
from typing import Any

from ..data_registry import COLLECTED_SERIES
from .annual_text import search_mda_hits
from .db import META_KEYS, SERIES_KEYS, get_annual_report, get_latest_snapshot, get_pit_financials, load_series

# 问题关键词 → data_key（命中则优先返回对应序列）
_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "price": ("股价", "收盘", "开盘", "高低", "行情", "k线", "均线", "ma", "volume", "成交量", "量价"),
    "price_change_rate": ("涨跌幅", "收益率", "回报", "涨跌"),
    "turnover": ("换手",),
    "capital_flow": ("资金", "净流入", "主力", "买卖"),
    "securities_margin": ("融资", "融券", "两融", "margin"),
    "factor": (
        "pe",
        "pb",
        "ps",
        "估值",
        "roe",
        "市值",
        "因子",
        "股息率",
        "毛利率",
        "净利率",
        "资产负债率",
        "流动比率",
        "速动比率",
        "营收增速",
        "净利润增速",
        "营业利润增速",
    ),
    "factor_history": ("历史pe", "历史pb", "估值走势", "因子历史"),
    "pit_financials": ("营收", "利润", "净利", "资产", "负债", "现金流", "财务", "三表", "毛利率", "roe"),
    "dividend": ("分红", "派息", "除权"),
    "shares": ("股本", "流通股", "总股本"),
    "block_trade": ("大宗",),
    "interbank_rate": ("shibor", "拆借", "同业"),
    "yield_curve": ("收益率曲线", "国债", "期限结构"),
    "index_benchmark": ("基准", "沪深300", "创业板", "相对强弱", "超额"),
    "suspended": ("停牌",),
    "st_stock": ("st",),
    "industry": ("行业", "中信"),
}

_DEFAULT_KEYS = ("price", "factor", "securities_margin", "pit_financials", "turnover")
_OVERVIEW_HINTS = ("概况", "总结", "怎么样", "概览", "整体", "介绍", "基本面", "综合分析")

_ANNUAL_HINTS = ("年报", "年度报告", "mda", "管理层", "经营情况", "董事会", "讨论与分析", "/pdf")
_QUARTER_HINTS = ("一季报", "半年报", "三季报", "季度报告")


def extract_report_year(query: str) -> int | None:
    q = str(query or "")
    patterns = (
        r"(20\d{2})\s*年?\s*(?:度)?\s*(?:annual|年报|年度报告|财务报告)",
        r"(20\d{2})\s*年?\s*(?:一季报|半年报|三季报|季度报告)",
        r"(20\d{2})(?:年)?报",
    )
    for pattern in patterns:
        match = re.search(pattern, q, flags=re.I)
        if match:
            return int(match.group(1))
    return None


_META_FOR_KEYS: dict[str, tuple[str, ...]] = {
    "technical": ("price", "price_change_rate", "turnover", "capital_flow"),
    "factor": ("factor", "factor_history"),
    "industry": ("industry",),
    "industry_l2": ("industry",),
    "benchmark_index": ("index_benchmark",),
}


def query_needs_stored_data(query: str) -> bool:
    """问题是否应触发本地数据库检索（避免仅绑定代码就每次灌入同一套默认序列）。"""
    q = str(query or "").strip()
    if not q:
        return False
    if _select_data_keys(q):
        return True
    if extract_report_year(q):
        return True
    if any(h in q for h in _QUARTER_HINTS):
        return True
    return _mentions_financials(q) or _mentions_annual(q)


def query_stored_data(
    stock_code: str,
    query: str,
    *,
    tail: int = 20,
    scope: str = "auto",
) -> dict[str, Any] | None:
    """按股票代码与问题检索最新快照中的相关序列；无数据时返回 None。"""
    code = str(stock_code or "").strip()
    if not code:
        return None

    snapshot = get_latest_snapshot(code)
    pit = get_pit_financials(code)
    report_year = extract_report_year(query)
    annual = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)
    if snapshot is None and pit is None and annual is None:
        return None

    from ..chat.metrics import filter_financial_rows, resolve_focused_metrics

    metric_labels = resolve_focused_metrics(query)
    selected_keys = _select_data_keys(query)
    if scope == "quote":
        selected_keys = [k for k in selected_keys if k in {"price", "price_change_rate", "turnover", "factor", "factor_history"}]
        if not selected_keys:
            selected_keys = ["price", "factor"]
    payload: dict[str, Any] = {"stock_code": code, "matched_keys": selected_keys, "scope": scope}

    if snapshot:
        payload["snapshot"] = {
            "id": snapshot["id"],
            "order_book_id": snapshot["order_book_id"],
            "as_of": snapshot["as_of"],
            "start_date": snapshot.get("start_date"),
            "end_date": snapshot.get("end_date"),
            "source": snapshot.get("source"),
            "created_at": snapshot.get("created_at"),
        }
        meta = snapshot.get("meta") or {}
        for key in META_KEYS:
            if key not in meta:
                continue
            if not selected_keys or _meta_relevant(key, selected_keys):
                payload[key] = meta[key]

        if selected_keys:
            payload["series"] = load_series(int(snapshot["id"]), selected_keys, tail=tail)
            payload["available_series"] = list(COLLECTED_SERIES.keys())

    if pit and ("pit_financials" in selected_keys or _mentions_financials(query)):
        pit_rows = pit["rows"]
        if metric_labels:
            pit_rows = filter_financial_rows(pit_rows, metric_labels)
        if tail:
            pit_rows = pit_rows[-tail:]
        payload["pit_financials_cache"] = {
            "report_year": pit["report_year"],
            "years": pit["years"],
            "quarters": pit["quarters"],
            "rows": pit_rows,
            "fetched_at": pit["fetched_at"],
        }

    if annual and scope != "quote":
        include_annual = (
            scope in {"annual", "fundamentals", "overview"}
            or _mentions_annual(query)
            or _mentions_financials(query)
            or report_year is not None
            or any(h in str(query or "") for h in _QUARTER_HINTS)
            or bool(metric_labels)
        )
        if include_annual:
            payload["annual_report"] = _annual_payload(
                annual, query, tail=tail, metric_labels=metric_labels or None
            )

    if not _payload_has_content(payload):
        return None

    return payload


def _payload_has_content(payload: dict[str, Any]) -> bool:
    if payload.get("series"):
        return True
    if payload.get("pit_financials_cache"):
        return True
    if payload.get("annual_report"):
        return True
    for key in META_KEYS:
        if key in payload:
            return True
    return bool(payload.get("matched_keys"))


def _meta_relevant(meta_key: str, selected_keys: list[str]) -> bool:
    triggers = _META_FOR_KEYS.get(meta_key, ())
    return any(key in selected_keys for key in triggers)


def _annual_payload(annual: dict[str, Any], query: str, *, tail: int, metric_labels: list[str] | None = None) -> dict[str, Any]:
    financial = annual.get("financial_data") or []
    if metric_labels:
        from ..chat.metrics import filter_financial_rows

        financial = filter_financial_rows(financial, metric_labels)
    if tail and len(financial) > tail:
        financial = financial[-tail:]
    mda_text = str(annual.get("mda_text") or "")
    mda_meta = annual.get("mda_meta") or {}
    mda_hits = search_mda_hits(mda_text, query, top_k=4)
    return {
        "report_year": annual.get("report_year"),
        "sec_name": annual.get("sec_name"),
        "title": annual.get("title"),
        "pdf_path": annual.get("pdf_path"),
        "fetched_at": annual.get("fetched_at"),
        "financial_data": financial if (_mentions_financials(query) or _mentions_annual(query)) else [],
        "mda_hits": mda_hits,
        "mda_extraction": {
            "confidence": mda_meta.get("confidence"),
            "start_heading": mda_meta.get("start_heading"),
            "end_heading": mda_meta.get("end_heading"),
            "char_count": mda_meta.get("char_count") or len(mda_text),
        },
        "mda_summary": mda_meta.get("summary"),
    }


def _mentions_annual(query: str) -> bool:
    q = str(query or "").lower()
    return any(h in q for h in _ANNUAL_HINTS) or any(h in q for h in _QUARTER_HINTS)


def _select_data_keys(query: str) -> list[str]:
    q = str(query or "").lower()
    matched: list[str] = []
    for key, hints in _QUERY_HINTS.items():
        for hint in hints:
            if hint in q or (len(hint) <= 4 and re.search(rf"\b{re.escape(hint)}\b", q)):
                matched.append(key)
                break

    normalized: list[str] = []
    for key in matched:
        if key in SERIES_KEYS and key not in normalized:
            normalized.append(key)
        if key == "factor" and "factor_history" not in normalized:
            normalized.append("factor_history")

    if not normalized:
        if any(h in q for h in _OVERVIEW_HINTS):
            return list(_DEFAULT_KEYS)
        return []
    return normalized


def _mentions_financials(query: str) -> bool:
    q = str(query or "").lower()
    return any(h in q for h in _QUERY_HINTS["pit_financials"])
