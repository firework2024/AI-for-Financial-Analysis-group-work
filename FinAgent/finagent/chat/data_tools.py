"""对话中按需拉取米筐数据快照。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ..cninfo import default_as_of, normalize_stock_code, to_order_book_id
from ..env import load_dotenv

if TYPE_CHECKING:
    from .store import ChatSession

LIVE_DATA_HINTS = (
    "最新",
    "最近",
    "现在",
    "当前",
    "今天",
    "实时",
    "股价",
    "收盘",
    "开盘",
    "融资",
    "pe",
    "pb",
    "rsi",
    "macd",
    "均线",
    "市值",
    "换手率",
    "行情",
    "k线",
    "现价",
    "涨跌",
)

_LIVE_DATA_GENERIC = ("查一下", "帮我看", "拉一下", "更新一下")

_STOCK_ALIASES: dict[str, str] = {
    "阳光电源": "300274",
    "宁德时代": "300750",
    "贵州茅台": "600519",
    "茅台": "600519",
    "平安银行": "000001",
    "万科": "000002",
    "万科a": "000002",
    "比亚迪": "002594",
}


def needs_live_data(query: str) -> bool:
    q = str(query or "").lower()
    if any(hint in q for hint in LIVE_DATA_HINTS):
        return True
    if any(h in q for h in _LIVE_DATA_GENERIC):
        return any(h in q for h in ("股价", "行情", "收盘", "pe", "pb", "融资", "市值", "换手", "最新"))
    return False


def extract_stock_code(text: str, fallback: str | None = None) -> str | None:
    match = re.search(r"\b([036]\d{5})\b", str(text or ""))
    if match:
        return match.group(1)
    return fallback


def resolve_stock_code(query: str, session: ChatSession | None = None) -> str | None:
    """从会话绑定、问题文本、历史消息、知识片段或简称解析股票代码。"""
    if session and session.stock_code:
        return session.stock_code

    code = extract_stock_code(query)
    if code:
        return code

    if session:
        for message in reversed(session.messages):
            if message.role != "user":
                continue
            code = extract_stock_code(message.content)
            if code:
                return code

        for item in session.chunks or []:
            meta = item.get("meta") if isinstance(item, dict) else {}
            chunk_code = str((meta or {}).get("stock_code") or "").strip()
            if re.fullmatch(r"\d{6}", chunk_code):
                return chunk_code
            code = extract_stock_code(str(item.get("text") or "")[:800])
            if code:
                return code

    blob = str(query or "")
    if session:
        blob = " ".join([blob, *[m.content for m in session.messages if m.role == "user"][-4:]])
    code = _code_from_aliases(blob)
    if code:
        return code
    code = _code_from_cninfo_name(blob)
    if code:
        return code
    return _code_from_sec_name(blob)


def _code_from_aliases(text: str) -> str | None:
    q = str(text or "")
    for name, code in sorted(_STOCK_ALIASES.items(), key=lambda item: -len(item[0])):
        if name in q:
            return code
    return None


def _code_from_cninfo_name(text: str) -> str | None:
    try:
        from ..cninfo import lookup_stock_code_by_name

        return lookup_stock_code_by_name(text)
    except Exception:
        return None


def _code_from_sec_name(text: str) -> str | None:
    q = str(text or "").strip()
    if len(q) < 2:
        return None
    try:
        from ..datastore.db import _locked_connect

        with _locked_connect() as conn:
            row = conn.execute(
                """
                SELECT stock_code FROM annual_report_records
                WHERE sec_name IS NOT NULL AND ? LIKE '%' || sec_name || '%'
                ORDER BY report_year DESC
                LIMIT 1
                """,
                (q,),
            ).fetchone()
        return str(row["stock_code"]) if row else None
    except Exception:
        return None


def fetch_market_snapshot(
    stock_code: str,
    *,
    as_of: str | None = None,
    lookback_days: int = 60,
    incremental: bool = True,
) -> dict[str, Any]:
    load_dotenv()
    from pathlib import Path

    code = normalize_stock_code(stock_code)
    order_book_id = to_order_book_id(code)
    as_of_date = default_as_of(as_of)
    market_context = _market_context(as_of_date)
    base: dict[str, Any] = {
        "stock_code": code,
        "order_book_id": order_book_id,
        "as_of": as_of_date.isoformat(),
        "market_context": market_context,
    }

    incremental_after: str | None = None
    if incremental:
        try:
            from ..datastore.db import get_latest_snapshot

            latest = get_latest_snapshot(code)
            if latest and latest.get("end_date"):
                incremental_after = str(latest["end_date"])
        except Exception:
            incremental_after = None

    try:
        from ..multiagent import data_executor_agent

        data = data_executor_agent(
            order_book_id=order_book_id,
            as_of=as_of_date,
            lookback_days=lookback_days,
            output_dir=Path("outputs"),
            incremental_after=incremental_after,
        )
    except Exception as exc:
        fallback = _local_snapshot_fallback(code)
        err_payload = {**base, "error": f"{type(exc).__name__}: {exc}", "source": "rqdata_error"}
        if fallback:
            err_payload.update(fallback)
            err_payload["note"] = "米筐拉取失败，已回退本地数据库最近快照。"
        return err_payload

    price_rows = (data.get("price") or {}).get("rows") or []
    technical = data.get("technical") or {}
    end_date = str(data.get("end_date") or "")
    quote = _build_quote_summary(price_rows, technical, end_date)
    payload = {
        **base,
        "sec_name": data.get("sec_name"),
        "end_date": end_date,
        "source": "rqdata",
        "quote": quote,
        "technical": technical,
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "price_tail": price_rows[-5:],
        "margin_tail": (data.get("securities_margin") or {}).get("rows", [])[-5:],
        "pit_financials_tail": (data.get("pit_financials") or {}).get("rows", [])[-3:],
    }
    if not quote.get("close"):
        fallback = _local_snapshot_fallback(code)
        if fallback:
            payload.update({k: v for k, v in fallback.items() if k not in payload or not payload.get(k)})
            payload["note"] = "米筐未返回有效收盘价，已补充本地数据库快照。"
    return payload


def live_quote_available(live: dict[str, Any] | None) -> bool:
    if not live:
        return False
    quote = live.get("quote") or {}
    if quote.get("close") is not None:
        return True
    tech = live.get("technical") or {}
    return tech.get("latest_close") is not None


def _market_context(as_of_date: date) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "as_of": as_of_date.isoformat(),
        "weekday": as_of_date.weekday(),
        "is_weekend": as_of_date.weekday() >= 5,
    }
    last_trade = _guess_last_trading_date(as_of_date)
    ctx["last_trading_date_guess"] = last_trade.isoformat()
    notes: list[str] = []
    if ctx["is_weekend"]:
        notes.append(
            f"{as_of_date.isoformat()} 为周末，A 股无实时行情；"
            f"最近交易日收盘价见 quote（约 {last_trade.isoformat()}）。"
        )
    try:
        import rqdatac

        from ..multiagent import _init_rqdata

        _init_rqdata(rqdatac)
        if rqdatac.is_trading_date(as_of_date):
            notes.append(f"{as_of_date.isoformat()} 为交易日，quote 对应当日或最近可用收盘。")
        else:
            prev = rqdatac.get_previous_trading_date(as_of_date)
            ctx["last_trading_date"] = str(prev)
            notes.append(f"{as_of_date.isoformat()} 非交易日，行情截至 {prev}。")
    except Exception:
        if not ctx["is_weekend"]:
            notes.append("交易日历以米筐为准；周末请引用最近交易日收盘价。")
    ctx["notes"] = notes
    return ctx


def _guess_last_trading_date(as_of_date: date) -> date:
    cursor = as_of_date
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _build_quote_summary(
    price_rows: list[dict[str, Any]],
    technical: dict[str, Any],
    end_date: str,
) -> dict[str, Any]:
    last_row = price_rows[-1] if price_rows else {}
    prev_row = price_rows[-2] if len(price_rows) >= 2 else {}
    close = technical.get("latest_close")
    if close is None and last_row.get("close") is not None:
        close = last_row.get("close")
    trade_date = end_date or last_row.get("date")
    prev_close = prev_row.get("close")
    change_pct = None
    if close is not None and prev_close not in (None, 0):
        try:
            change_pct = round((float(close) / float(prev_close) - 1) * 100, 4)
        except (TypeError, ValueError):
            change_pct = None
    return {
        "date": trade_date,
        "close": close,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "open": last_row.get("open"),
        "high": last_row.get("high"),
        "low": last_row.get("low"),
        "volume": last_row.get("volume"),
    }


def _local_snapshot_fallback(stock_code: str) -> dict[str, Any] | None:
    try:
        from ..datastore.db import get_latest_snapshot, load_series
        from ..datastore.query import query_stored_data
    except Exception:
        return None

    stored = query_stored_data(stock_code, "股价 收盘 行情", tail=5)
    snapshot = get_latest_snapshot(stock_code)
    if not snapshot and not stored:
        return None

    technical = (stored or {}).get("technical") or (snapshot or {}).get("meta", {}).get("technical") or {}
    factor = (stored or {}).get("factor") or (snapshot or {}).get("meta", {}).get("factor") or {}
    price_rows: list[dict[str, Any]] = []
    if stored and stored.get("series"):
        price_rows = (stored["series"].get("price") or {}).get("rows") or []
    elif snapshot:
        series = load_series(int(snapshot["id"]), ["price"], tail=5)
        price_rows = (series.get("price") or {}).get("rows") or []

    end_date = str((snapshot or {}).get("end_date") or "")
    quote = _build_quote_summary(price_rows, technical, end_date)
    if not quote.get("close") and not technical:
        return None

    return {
        "source": "local_db",
        "end_date": end_date,
        "quote": quote,
        "technical": technical,
        "factor": factor,
        "price_tail": price_rows[-5:],
        "snapshot": {
            "id": (snapshot or {}).get("id"),
            "as_of": (snapshot or {}).get("as_of"),
            "end_date": end_date,
        },
    }
