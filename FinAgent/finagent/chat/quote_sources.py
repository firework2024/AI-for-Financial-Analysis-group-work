"""行情直连数据源（东方财富 push2 API），补全网页搜索无法拿到的结构化报价。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import requests

from ..cninfo import classify_stock, normalize_stock_code

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

_SPOT_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SPOT_FIELDS = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86,f116,f117,f162,f167,f168,f169,f170"
_KLINE_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"


def eastmoney_secid(stock_code: str) -> str:
    code = normalize_stock_code(stock_code)
    _, _, suffix = classify_stock(code)
    market = "1" if suffix == "XSHG" else "0"
    return f"{market}.{code}"


def eastmoney_quote_page_url(stock_code: str) -> str:
    code = normalize_stock_code(stock_code)
    _, column, _ = classify_stock(code)
    prefix = "sh" if column == "sh" else "sz"
    return f"https://quote.eastmoney.com/{prefix}{code}.html"


def extract_trade_date_from_query(query: str, *, default_year: int | None = None) -> date | None:
    q = str(query or "")
    year = default_year
    year_match = re.search(r"(20\d{2})\s*年?", q)
    if year_match:
        year = int(year_match.group(1))
    md = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", q)
    if md and year:
        month, day = int(md.group(1)), int(md.group(2))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", q)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    return None


def fetch_eastmoney_quote(stock_code: str, *, trade_date: date | None = None) -> dict[str, Any]:
    """拉取东方财富行情；若指定 trade_date 则优先取该日 K 线收盘，否则取最新快照。"""
    code = normalize_stock_code(stock_code)
    secid = eastmoney_secid(code)
    page_url = eastmoney_quote_page_url(code)

    if trade_date is not None:
        bar = _fetch_daily_bar(secid, trade_date)
        if bar:
            return {**bar, "stock_code": code, "secid": secid, "source": "eastmoney_kline", "page_url": page_url}

    spot = _fetch_spot(secid)
    if spot:
        return {**spot, "stock_code": code, "secid": secid, "source": "eastmoney_spot", "page_url": page_url}
    return {"stock_code": code, "secid": secid, "error": "eastmoney_empty", "page_url": page_url}


def _asks_close_price(query: str) -> bool:
    q = str(query or "")
    return any(h in q for h in ("收盘", "股价", "现价", "最新价", "行情", "涨跌", "多少钱", "价格"))


def _asks_recent_close(query: str) -> bool:
    q = str(query or "")
    return any(
        h in q
        for h in (
            "最近",
            "最新",
            "上一个交易",
            "上个交易",
            "周五",
            "周末",
            "今天",
            "当前",
            "现在",
        )
    )


def _guess_last_trading_date(as_of_date: date) -> date:
    cursor = as_of_date
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def supplement_live_with_web_quote(
    live: dict[str, Any] | None,
    stock_code: str,
    query: str = "",
) -> dict[str, Any]:
    """用东方财富补全/校正 live_data.quote（尤其区分收盘价与昨收）。"""
    payload = dict(live or {})
    quote = payload.get("quote") or {}
    must_refresh = _asks_close_price(query)
    if quote.get("close") is not None and not must_refresh:
        return payload

    trade_date = extract_trade_date_from_query(query, default_year=date.today().year)
    if trade_date is None and (_asks_recent_close(query) or must_refresh):
        trade_date = _guess_last_trading_date(date.today())
    em = fetch_eastmoney_quote(stock_code, trade_date=trade_date)
    if em.get("error") and not em.get("close"):
        payload["eastmoney_attempt"] = em
        return payload

    merged_quote = {
        "date": em.get("date") or payload.get("end_date"),
        "close": em.get("close"),
        "prev_close": em.get("prev_close"),
        "field_notes": QUOTE_FIELD_NOTES,
        "change": em.get("change"),
        "change_pct": em.get("change_pct"),
        "open": em.get("open"),
        "high": em.get("high"),
        "low": em.get("low"),
        "volume": em.get("volume"),
        "amount": em.get("amount"),
        "turnover_rate": em.get("turnover_rate"),
        "pe_ttm": em.get("pe_ttm"),
        "pb": em.get("pb"),
        "market_cap": em.get("market_cap"),
        "float_market_cap": em.get("float_market_cap"),
    }
    payload["quote"] = {k: v for k, v in merged_quote.items() if v is not None}
    payload["source"] = em.get("source") or "eastmoney"
    payload["sec_name"] = em.get("name") or payload.get("sec_name")
    payload["eastmoney"] = em
    payload["note"] = "已通过东方财富 API 补全结构化行情（非搜索引擎摘要）。"
    if payload.get("error"):
        payload.pop("error", None)
    try:
        from .eastmoney_profile import attach_profile_to_live

        payload = attach_profile_to_live(payload, stock_code, query=query)
    except Exception:
        pass
    return payload


QUOTE_FIELD_NOTES = {
    "close": "当日收盘价（回答「某天收盘价/最近收盘价」必须用此字段）",
    "prev_close": "昨收=前一交易日收盘价，不是当日收盘价（勿与 close 混淆）",
}


def format_quote_text(quote: dict[str, Any]) -> str:
    parts = []
    if quote.get("name") or quote.get("stock_code"):
        parts.append(f"{quote.get('name') or ''} {quote.get('stock_code') or ''}".strip())
    if quote.get("date"):
        parts.append(f"交易日 {quote['date']}")
    if quote.get("close") is not None:
        parts.append(f"当日收盘价 {quote['close']} 元")
    if quote.get("change") is not None and quote.get("change_pct") is not None:
        parts.append(f"涨跌 {quote['change']} ({quote['change_pct']}%)")
    for label, key in (
        ("昨收(前一日收盘)", "prev_close"),
        ("今开", "open"),
        ("最高", "high"),
        ("最低", "low"),
        ("换手", "turnover_rate"),
        ("成交额", "amount"),
        ("总市值", "market_cap"),
        ("流通市值", "float_market_cap"),
        ("市盈(动)", "pe_ttm"),
        ("市净", "pb"),
    ):
        if quote.get(key) is not None:
            parts.append(f"{label} {quote[key]}")
    return "；".join(parts)


def _fetch_spot(secid: str) -> dict[str, Any] | None:
    params = {
        "secid": secid,
        "fields": _SPOT_FIELDS,
        "ut": "fa5fd1943c7b386f172d7ef921b690b2",
        "invt": "2",
        "fltt": "2",
    }
    try:
        resp = requests.get(_SPOT_URL, params=params, headers=_EM_HEADERS, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    data = (payload or {}).get("data") or {}
    if not data:
        return None
    return _normalize_spot(data)


def _fetch_daily_bar(secid: str, trade_date: date) -> dict[str, Any] | None:
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": "12",
        "end": trade_date.strftime("%Y%m%d"),
        "fields1": "f1",
        "fields2": _KLINE_FIELDS,
    }
    try:
        resp = requests.get(_KLINE_URL, params=params, headers=_EM_HEADERS, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    klines = ((payload or {}).get("data") or {}).get("klines") or []
    target = trade_date.isoformat()
    for line in reversed(klines):
        row = _parse_kline_row(line)
        if row.get("date") == target:
            return row
    if klines:
        return _parse_kline_row(klines[-1])
    return None


def _parse_kline_row(line: str) -> dict[str, Any]:
    # f51 date, f52 open, f53 close, f54 high, f55 low, f56 volume, f57 amount, f58 amplitude, f59 change%, f60 change, f61 turnover%
    parts = str(line).split(",")
    if len(parts) < 7:
        return {}
    row: dict[str, Any] = {
        "date": parts[0],
        "open": _float(parts[1]),
        "close": _float(parts[2]),
        "close_label": "当日收盘价",
        "high": _float(parts[3]),
        "low": _float(parts[4]),
        "volume": parts[5],
        "amount": parts[6],
    }
    if len(parts) > 8:
        row["change_pct"] = _float(parts[8])
    if len(parts) > 9:
        row["change"] = _float(parts[9])
    if len(parts) > 10:
        row["turnover_rate"] = _float(parts[10])
    return row


def _normalize_spot(data: dict[str, Any]) -> dict[str, Any]:
    close = _float(data.get("f43"))
    prev = _float(data.get("f60"))
    change = _float(data.get("f169"))
    change_pct = _float(data.get("f170"))
    if change is None and close is not None and prev is not None:
        change = round(close - prev, 2)
    if change_pct is None and change is not None and prev not in (None, 0):
        change_pct = round(change / prev * 100, 2)

    trade_date = _parse_em_trade_date(data.get("f86"))

    return {
        "code": str(data.get("f57") or ""),
        "name": str(data.get("f58") or "").strip(),
        "date": trade_date,
        "close": close,
        "close_label": "当日收盘价",
        "prev_close": prev,
        "prev_close_label": "前一交易日收盘(昨收)",
        "open": _float(data.get("f46")),
        "high": _float(data.get("f44")),
        "low": _float(data.get("f45")),
        "change": change,
        "change_pct": change_pct,
        "volume": data.get("f47"),
        "amount": data.get("f48"),
        "turnover_rate": _float(data.get("f168")),
        "pe_ttm": _float(data.get("f162")),
        "pb": _float(data.get("f167")),
        "market_cap": data.get("f116"),
        "float_market_cap": data.get("f117"),
        "updated_at": str(data.get("f86") or ""),
    }


def _parse_em_trade_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if re.fullmatch(r"20\d{10,}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        ts = int(float(text))
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000_000:
        ts //= 1_000_000
    elif ts > 10_000_000_000:
        ts //= 1_000
    if 1_400_000_000 <= ts <= 2_100_000_000:
        from datetime import datetime

        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return None


def _float(value: Any) -> float | None:
    if value is None or value == "-" or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
