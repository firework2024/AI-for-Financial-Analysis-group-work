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
    "factor": ("pe", "pb", "ps", "估值", "roe", "市值", "因子", "股息率"),
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


_ANNUAL_HINTS = ("年报", "mda", "管理层", "经营情况", "董事会", "讨论与分析", "/pdf")


def query_stored_data(stock_code: str, query: str, *, tail: int = 20) -> dict[str, Any] | None:
    """按股票代码与问题检索最新快照中的相关序列；无数据时返回 None。"""
    code = str(stock_code or "").strip()
    if not code:
        return None

    snapshot = get_latest_snapshot(code)
    pit = get_pit_financials(code)
    annual = get_annual_report(code)
    if snapshot is None and pit is None and annual is None:
        return None

    selected_keys = _select_data_keys(query)
    payload: dict[str, Any] = {"stock_code": code, "matched_keys": selected_keys}

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
            if key in meta:
                payload[key] = meta[key]

        series = load_series(int(snapshot["id"]), selected_keys, tail=tail)
        payload["series"] = series
        payload["available_series"] = list(COLLECTED_SERIES.keys())

    if pit and ("pit_financials" in selected_keys or _mentions_financials(query)):
        payload["pit_financials_cache"] = {
            "report_year": pit["report_year"],
            "years": pit["years"],
            "quarters": pit["quarters"],
            "rows": pit["rows"][-tail:] if tail else pit["rows"],
            "fetched_at": pit["fetched_at"],
        }

    if annual and (_mentions_annual(query) or _mentions_financials(query) or snapshot is None):
        payload["annual_report"] = _annual_payload(annual, query, tail=tail)

    return payload


def _annual_payload(annual: dict[str, Any], query: str, *, tail: int) -> dict[str, Any]:
    financial = annual.get("financial_data") or []
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
        "financial_data": financial,
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
    return any(h in q for h in _ANNUAL_HINTS)


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
        return list(_DEFAULT_KEYS)
    return normalized


def _mentions_financials(query: str) -> bool:
    q = str(query or "").lower()
    return any(h in q for h in _QUERY_HINTS["pit_financials"])
