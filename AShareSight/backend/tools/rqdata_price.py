"""A-share price tools via rqdatac (Eastmoney fallback)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from backend.utils.ticker_rq import board_type, limit_pct, to_rqdatac_id
from backend.utils.quote import safe_float

from .cn_hk_market import fetch_cn_hk_kline, fetch_cn_hk_quote_metrics
from .rqdata_client import rqdatac_module

logger = logging.getLogger(__name__)


def _ensure_trading_date(rq: Any, d: str | date) -> str:
    if rq.is_trading_date(d):
        return str(d)[:10]
    prev = rq.get_previous_trading_date(d, n=1)
    return str(prev)[:10]


def _latest_close(rq: Any, order_book_id: str) -> dict[str, Any] | None:
    end = _ensure_trading_date(rq, date.today())
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    df = rq.get_price(
        order_book_id,
        start_date=start,
        end_date=end,
        frequency="1d",
        fields=["open", "high", "low", "close", "volume", "total_turnover"],
        adjust_type="pre",
    )
    if df is None or (hasattr(df, "empty") and df.empty):
        return None
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
    elif df.index.name:
        df = df.reset_index()
    row = df.iloc[-1]
    close = safe_float(row.get("close"))
    if close is None:
        return None
    prev_close = safe_float(df.iloc[-2].get("close")) if len(df) > 1 else None
    change = (close - prev_close) if prev_close else None
    change_pct = ((change / prev_close) * 100.0) if change is not None and prev_close else None
    return {
        "open": safe_float(row.get("open")),
        "high": safe_float(row.get("high")),
        "low": safe_float(row.get("low")),
        "close": close,
        "volume": safe_float(row.get("volume")),
        "prev_close": prev_close,
        "change": change,
        "change_percent": change_pct,
        "as_of": str(row.get("date") or end)[:10],
    }


def get_stock_price(ticker: str) -> dict[str, Any] | str:
    """Return structured quote dict (CNY) for agents and APIs."""
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker", "ticker": ticker}

    rq = rqdatac_module()
    if rq is not None:
        try:
            bar = _latest_close(rq, obid)
            if bar:
                inst = None
                try:
                    inst = rq.instruments(obid)
                except Exception:
                    pass
                name = getattr(inst, "symbol", None) or getattr(inst, "abbrev_symbol", None) or obid
                return {
                    "ticker": obid,
                    "name": str(name),
                    "price": bar["close"],
                    "currency": "CNY",
                    "change": bar.get("change"),
                    "change_percent": bar.get("change_percent"),
                    "source": "rqdatac",
                    "as_of": bar.get("as_of"),
                }
        except Exception as exc:
            logger.info("[RQPrice] rqdatac quote failed %s: %s", obid, exc)

    em = fetch_cn_hk_quote_metrics(obid.replace(".XSHG", ".SS").replace(".XSHE", ".SZ").replace(".XBEX", ".BJ"))
    if em:
        lp = em.get("last_price")
        return {
            "ticker": obid,
            "name": em.get("name") or obid,
            "price": lp,
            "currency": "CNY",
            "change_percent": None,
            "source": "eastmoney_quote",
            "as_of": datetime.now().isoformat(),
            "fallback_used": True,
        }
    return {"error": "price_unavailable", "ticker": obid}


def get_stock_historical_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, Any] | str:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}

    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}.get(period, 365)
    end = date.today()
    start = end - timedelta(days=period_days)
    freq = "1d" if interval in {"1d", "1day", "daily"} else "1d"

    rq = rqdatac_module()
    rows: list[dict[str, Any]] = []
    if rq is not None:
        try:
            end_s = _ensure_trading_date(rq, end)
            df = rq.get_price(
                obid,
                start_date=str(start)[:10],
                end_date=end_s,
                frequency=freq,
                fields=["open", "high", "low", "close", "volume"],
                adjust_type="pre",
            )
            if df is not None and not df.empty:
                if isinstance(df.index, pd.MultiIndex):
                    df = df.reset_index()
                else:
                    df = df.reset_index()
                for _, r in df.iterrows():
                    rows.append(
                        {
                            "date": str(r.get("date", ""))[:10],
                            "open": safe_float(r.get("open")),
                            "high": safe_float(r.get("high")),
                            "low": safe_float(r.get("low")),
                            "close": safe_float(r.get("close")),
                            "volume": safe_float(r.get("volume")),
                        }
                    )
        except Exception as exc:
            logger.info("[RQPrice] historical rqdatac failed: %s", exc)

    if not rows:
        short = obid.replace(".XSHG", ".SS").replace(".XSHE", ".SZ").replace(".XBEX", ".BJ")
        klines = fetch_cn_hk_kline(short, limit=min(period_days, 1200))
        rows = [
            {
                "date": k.get("time"),
                "open": k.get("open"),
                "high": k.get("high"),
                "low": k.get("low"),
                "close": k.get("close"),
                "volume": k.get("volume"),
            }
            for k in klines
        ]

    return {"ticker": obid, "period": period, "interval": interval, "rows": rows, "source": "rqdatac" if rq else "eastmoney"}


def get_performance_comparison(tickers: list[str], period: str = "1y") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in tickers:
        hist = get_stock_historical_data(t, period=period)
        if isinstance(hist, dict) and hist.get("rows"):
            closes = [r["close"] for r in hist["rows"] if r.get("close") is not None]
            if len(closes) >= 2 and closes[0]:
                ret = (closes[-1] - closes[0]) / closes[0] * 100.0
                out[to_rqdatac_id(t) or t] = {"return_pct": ret, "source": hist.get("source")}
    return {"comparisons": out}


def get_factor_exposure(ticker: str, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}
    rq = rqdatac_module()
    if rq is None:
        return {"error": "rqdatac_unavailable"}
    end_s = end_date or str(date.today())
    start_s = start_date or (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    try:
        df = rq.get_factor_exposure([obid], start_date=start_s, end_date=end_s)
        if df is None or df.empty:
            return {"ticker": obid, "rows": [], "source": "rqdatac"}
        return {"ticker": obid, "rows": df.reset_index().to_dict(orient="records"), "source": "rqdatac"}
    except Exception as exc:
        return {"error": str(exc), "ticker": obid}


def analyze_historical_drawdowns(ticker: str, period: str = "2y") -> dict[str, Any]:
    hist = get_stock_historical_data(ticker, period=period)
    if not isinstance(hist, dict):
        return {"error": "no_data"}
    closes = [r["close"] for r in hist.get("rows", []) if r.get("close") is not None]
    if len(closes) < 2:
        return {"error": "insufficient_data"}
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            dd = (c - peak) / peak
            max_dd = min(max_dd, dd)
    return {"ticker": hist.get("ticker"), "max_drawdown_pct": max_dd * 100.0, "source": hist.get("source")}


def run_portfolio_stress_test(tickers: list[str], shock_pct: float = -10.0) -> dict[str, Any]:
    results = {}
    for t in tickers:
        q = get_stock_price(t)
        if isinstance(q, dict) and q.get("price"):
            results[to_rqdatac_id(t) or t] = {
                "price": q["price"],
                "stressed_price": float(q["price"]) * (1 + shock_pct / 100.0),
            }
    return {"shock_pct": shock_pct, "positions": results}


def get_limit_board_info(ticker: str) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}
    pct = limit_pct(ticker)
    q = get_stock_price(ticker)
    price = q.get("price") if isinstance(q, dict) else None
    if price is None:
        return {"ticker": obid, "limit_pct": pct, "board": board_type(ticker)}
    up = round(price * (1 + pct), 2)
    down = round(price * (1 - pct), 2)
    dist_up = (up - price) / price * 100 if price else None
    dist_down = (price - down) / price * 100 if price else None
    return {
        "ticker": obid,
        "board": board_type(ticker),
        "limit_up": up,
        "limit_down": down,
        "limit_pct": pct,
        "distance_to_limit_up_pct": dist_up,
        "distance_to_limit_down_pct": dist_down,
        "source": "rqdatac_calc",
    }


def get_suspension_info(ticker: str) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}
    rq = rqdatac_module()
    if rq is None:
        return {"ticker": obid, "suspended": None, "source": "unavailable"}
    try:
        end = _ensure_trading_date(rq, date.today())
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        df = rq.is_suspended(obid, start_date=start, end_date=end)
        suspended = bool(df.iloc[-1]) if df is not None and not df.empty else False
        return {"ticker": obid, "suspended": suspended, "source": "rqdatac"}
    except Exception as exc:
        return {"ticker": obid, "error": str(exc)}


def get_st_status(ticker: str) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}
    rq = rqdatac_module()
    if rq is None:
        return {"ticker": obid, "is_st": None}
    try:
        end = _ensure_trading_date(rq, date.today())
        df = rq.is_st_stock(obid, start_date=end, end_date=end)
        is_st = bool(df.iloc[-1]) if df is not None and not df.empty else False
        return {"ticker": obid, "is_st": is_st, "source": "rqdatac"}
    except Exception as exc:
        return {"ticker": obid, "error": str(exc)}


def _fetch_rqdatac_price(ticker: str) -> dict[str, Any] | None:
    result = get_stock_price(ticker)
    return result if isinstance(result, dict) and result.get("price") else None


def _search_for_price(ticker: str) -> str | None:
    from .search import search

    obid = to_rqdatac_id(ticker) or ticker
    try:
        hits = search(f"{obid} A股 最新股价", max_results=3)
        if hits:
            return str(hits[0]) if not isinstance(hits[0], dict) else hits[0].get("content", str(hits[0]))
    except Exception:
        pass
    return None
