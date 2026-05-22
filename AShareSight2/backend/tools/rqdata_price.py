"""A-share price/market data via RQData.

Primary source: rqdatac
Fallback: eastmoney (via cn_hk_market.py)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from backend.utils.ticker_rq import normalize_to_rq, detect_market
from .rqdata_config import init_rqdata

logger = logging.getLogger(__name__)

# Default periods
_DEFAULT_DAYS = 365


def _ensure_init():
    if not init_rqdata():
        raise RuntimeError("RQData not initialized")


def _to_date_str(dt) -> str:
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def get_stock_price(ticker: str) -> Optional[dict[str, Any]]:
    """Get latest stock price snapshot for an A-share ticker.

    Returns dict with: symbol, price, currency, change, change_percent, volume, source, as_of
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac
    except (ImportError, RuntimeError):
        return _fallback_quote(ticker)

    try:
        today = datetime.now()
        end = _to_date_str(today)
        # Get up to 30 trading days to ensure we have at least one
        start = _to_date_str(today - timedelta(days=60))

        df = rqdatac.get_price(
            rq_ticker,
            start_date=start,
            end_date=end,
            frequency="1d",
            fields=["close", "open", "high", "low", "volume", "total_turnover"],
        )

        if df is None or df.empty:
            return _fallback_quote(ticker)

        # If single stock, df may have MultiIndex or flat index
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        # Get last two rows for change calculation
        prices = df["close"].values
        if len(prices) == 0:
            return _fallback_quote(ticker)

        last_price = float(prices[-1])
        prev_close = float(prices[-2]) if len(prices) >= 2 else last_price
        change = last_price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        volume = float(df["volume"].values[-1]) if "volume" in df.columns else 0
        high = float(df["high"].max()) if "high" in df.columns else last_price
        low = float(df["low"].min()) if "low" in df.columns else last_price

        return {
            "ticker": rq_ticker,
            "price": round(last_price, 2),
            "currency": "CNY",
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "change_pct": round(change_pct, 2),
            "volume": volume,
            "open": float(df["open"].values[-1]) if "open" in df.columns else last_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "source": "rqdatac",
            "as_of": datetime.now().isoformat(),
            "fallback_used": False,
        }
    except Exception as exc:
        logger.warning("rqdatac get_stock_price failed for %s: %s", rq_ticker, exc)
        return _fallback_quote(ticker)


def _fallback_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Fallback to eastmoney for quote data."""
    try:
        from .cn_hk_market import fetch_cn_hk_quote_metrics

        result = fetch_cn_hk_quote_metrics(ticker)
        if result:
            result["fallback_used"] = True
            result["source"] = "eastmoney"
            return result
    except Exception as exc:
        logger.info("Eastmoney fallback failed for %s: %s", ticker, exc)
    return None


def get_stock_historical_data(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    frequency: str = "1d",
) -> Optional[list[dict[str, Any]]]:
    """Get historical OHLCV data for an A-share ticker.

    Returns list of {time, open, close, high, low, volume}.
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    if end_date is None:
        end_date = _to_date_str(datetime.now())
    if start_date is None:
        start_date = _to_date_str(datetime.now() - timedelta(days=_DEFAULT_DAYS))

    try:
        _ensure_init()
        import rqdatac

        df = rqdatac.get_price(
            rq_ticker,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            fields=["close", "open", "high", "low", "volume"],
        )
        if df is None or df.empty:
            return _fallback_kline(ticker, start_date, end_date)

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "time": str(row.get("date", row.get("day", "")))[:10],
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": float(row["volume"]),
            })
        return rows
    except Exception as exc:
        logger.warning("rqdatac historical failed for %s: %s", rq_ticker, exc)
        return _fallback_kline(ticker, start_date, end_date)


def _fallback_kline(ticker: str, start_date: str, end_date: str) -> Optional[list[dict]]:
    try:
        from .cn_hk_market import fetch_cn_hk_kline

        return fetch_cn_hk_kline(ticker)
    except Exception as exc:
        logger.info("Eastmoney kline fallback failed: %s", exc)
        return None


def get_performance_comparison(
    tickers: list[str], period_days: int = 252
) -> Optional[dict[str, float]]:
    """Calculate period returns for a list of tickers."""
    rq_tickers = [t for t in (normalize_to_rq(t) for t in tickers) if t]
    if not rq_tickers:
        return None

    end = _to_date_str(datetime.now())
    start = _to_date_str(datetime.now() - timedelta(days=period_days))

    try:
        _ensure_init()
        import rqdatac

        df = rqdatac.get_price(
            rq_tickers,
            start_date=start,
            end_date=end,
            frequency="1d",
            fields=["close"],
        )
        if df is None or df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        result = {}
        for ticker in rq_tickers:
            tdf = df[df["order_book_id"] == ticker] if "order_book_id" in df.columns else df
            prices = tdf["close"].values
            if len(prices) >= 2:
                result[ticker] = round((float(prices[-1]) / float(prices[0]) - 1) * 100, 2)
        return result
    except Exception as exc:
        logger.warning("Performance comparison failed: %s", exc)
        return None


def get_factor_exposure(
    ticker: str, factor_names: Optional[list[str]] = None
) -> Optional[dict[str, Any]]:
    """Get factor values for a ticker using rqdatac.get_factor().

    If factor_names is None, returns latest available standard factors.
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=30)

        if factor_names is None:
            # Discover available factors
            all_factors = rqdatac.get_all_factor_names()
            if all_factors:
                # Pick common value/financial factors
                candidates = [
                    "pe_ttm", "pb_lf", "ps_ttm", "market_cap",
                    "turnover_20d", "volume_ratio_5d",
                    "ln_capital", "dividend_yield_ratio",
                ]
                factor_names = [f for f in candidates if f in all_factors]

        if not factor_names:
            return None

        df = rqdatac.get_factor(
            rq_ticker,
            factor=factor_names,
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
        )
        if df is None or df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        latest = df.iloc[-1].to_dict() if len(df) > 0 else {}
        return {k: float(v) if isinstance(v, (int, float)) else v for k, v in latest.items()}
    except Exception as exc:
        logger.warning("Factor exposure failed for %s: %s", ticker, exc)
        return None


def get_turnover_rate(ticker: str, days: int = 20) -> Optional[dict[str, float]]:
    """Get turnover rate statistics for a ticker."""
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    end = _to_date_str(datetime.now())
    start = _to_date_str(datetime.now() - timedelta(days=days + 10))

    try:
        _ensure_init()
        import rqdatac

        df = rqdatac.get_turnover_rate(
            rq_ticker,
            start_date=start,
            end_date=end,
        )
        if df is None or df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        rates = df["turnover_rate"].values if "turnover_rate" in df.columns else df.iloc[:, -1].values
        if len(rates) == 0:
            return None

        return {
            "latest": round(float(rates[-1]) * 100, 2),
            "avg_5d": round(float(rates[-5:].mean()) * 100, 2) if len(rates) >= 5 else None,
            "avg_20d": round(float(rates[-20:].mean()) * 100, 2) if len(rates) >= 20 else None,
            "source": "rqdatac",
        }
    except Exception as exc:
        logger.warning("Turnover rate failed for %s: %s", ticker, exc)
        return None


def get_suspension_info(ticker: str) -> Optional[dict[str, Any]]:
    """Check if stock is suspended on recent trading days."""
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    end = _to_date_str(datetime.now())
    start = _to_date_str(datetime.now() - timedelta(days=10))

    try:
        _ensure_init()
        import rqdatac

        df = rqdatac.is_suspended(
            rq_ticker,
            start_date=start,
            end_date=end,
        )
        if df is None or df.empty:
            return {"suspended": False}

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        suspended_dates = df[df.iloc[:, -1] == True]  # noqa: E712
        return {
            "suspended": len(suspended_dates) > 0,
            "suspended_dates": [str(d) for d in suspended_dates.iloc[:, 0].values] if len(suspended_dates) > 0 else [],
        }
    except Exception as exc:
        logger.warning("Suspension check failed for %s: %s", ticker, exc)
        return {"suspended": None, "error": str(exc)}


def is_st_stock(ticker: str) -> Optional[bool]:
    """Check if stock is currently ST or *ST."""
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac

        end = _to_date_str(datetime.now())
        start = _to_date_str(datetime.now() - timedelta(days=5))

        df = rqdatac.is_st_stock(
            rq_ticker,
            start_date=start,
            end_date=end,
        )
        if df is None or df.empty:
            return False

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        return bool(df.iloc[:, -1].any())
    except Exception as exc:
        logger.warning("ST check failed for %s: %s", ticker, exc)
        return None
