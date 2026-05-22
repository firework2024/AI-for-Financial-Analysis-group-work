"""A-share Dashboard data service — rqdatac as primary, Eastmoney as fallback."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from backend.dashboard.cache import dashboard_cache
from backend.utils.quote import safe_float
from backend.utils.ticker_rq import normalize_to_rq, detect_market, extract_code

logger = logging.getLogger(__name__)

_SOURCE_RELIABILITY_WEIGHTS = {
    "eastmoney": 0.70,
    "sina": 0.60,
    "10jqka": 0.62,
    "cls.cn": 0.72,
    "caixin": 0.88,
    "yicai": 0.85,
    "cninfo": 0.90,
    "stcn": 0.80,
    "nbd": 0.78,
    "rqdatac": 0.92,
}

_HIGH_IMPACT_KEYWORDS = {
    "业绩预告", "业绩快报", "预增", "预减", "扭亏",
    "立案", "调查", "处罚", "停牌",
    "并购", "重组", "借壳", "定增",
    "减持", "增持", "回购", "质押",
    "分红", "送转", "配股",
    "涨停", "跌停", "异动",
}


def _ensure_rq():
    from backend.tools.rqdata_config import init_rqdata
    if not init_rqdata():
        raise RuntimeError("RQData not initialized")


def _to_date(dt=None) -> str:
    if dt is None:
        dt = datetime.now()
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


# ── OHLCV Frame Cache ────────────────────────────────────
_OHLCV_FRAME_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_OHLCV_CACHE_TTL = 60.0


def _load_ohlcv_frame(symbol: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Load OHLCV DataFrame for technical analysis. TTL-cached."""
    cache_key = f"{symbol}:{period}:{interval}"
    now = datetime.now().timestamp()
    if cache_key in _OHLCV_FRAME_CACHE:
        ts, df = _OHLCV_FRAME_CACHE[cache_key]
        if now - ts < _OHLCV_CACHE_TTL:
            return df

    rq_ticker = normalize_to_rq(symbol)
    if not rq_ticker:
        return None

    try:
        _ensure_rq()
        import rqdatac

        end = datetime.now()
        days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}.get(period, 365)
        start = end - timedelta(days=days + 30)

        df = rqdatac.get_price(
            rq_ticker,
            start_date=_to_date(start),
            end_date=_to_date(end),
            frequency="1d",
            fields=["close", "open", "high", "low", "volume"],
        )
        if df is not None and not df.empty:
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index()
            _OHLCV_FRAME_CACHE[cache_key] = (now, df)
            return df
    except Exception as exc:
        logger.warning("rqdatac OHLCV failed for %s: %s", symbol, exc)

    # Eastmoney fallback
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_kline
        rows = fetch_cn_hk_kline(symbol)
        if rows:
            df = pd.DataFrame(rows)
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
                df = df.set_index("time")
            _OHLCV_FRAME_CACHE[cache_key] = (now, df)
            return df
    except Exception as exc:
        logger.warning("Eastmoney OHLCV fallback failed: %s", exc)
    return None


# ── Snapshot ─────────────────────────────────────────────
def fetch_snapshot(symbol: str, asset_type: str) -> dict[str, Any] | None:
    """Get real-time snapshot for A-share ticker."""
    rq_ticker = normalize_to_rq(symbol)
    if not rq_ticker:
        return None

    try:
        _ensure_rq()
        import rqdatac

        # Price + volume via get_price
        df = rqdatac.get_price(
            rq_ticker,
            start_date=_to_date(datetime.now() - timedelta(days=60)),
            end_date=_to_date(),
            frequency="1d",
            fields=["close", "open", "high", "low", "volume", "total_turnover"],
        )
        if df is None or df.empty:
            return _fallback_snapshot(symbol)

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        prices = df["close"].values
        last_price = float(prices[-1])
        prev_close = float(prices[-2]) if len(prices) >= 2 else last_price
        change = last_price - prev_close
        change_pct = round(change / prev_close * 100, 2) if prev_close else 0

        vol = float(df["volume"].values[-1]) if "volume" in df.columns else 0

        # PE/PB/EPS via factor
        pe, pb, market_cap, eps = None, None, None, None
        try:
            all_f = rqdatac.get_all_factor_names()
            fields = [f for f in ["pe_ratio", "pb_ratio_lf", "market_cap", "earnings_per_share"] if f in all_f]
            if fields:
                fdf = rqdatac.get_factor(rq_ticker, factor=fields, start_date=_to_date(datetime.now() - timedelta(days=10)), end_date=_to_date())
                if fdf is not None and not fdf.empty:
                    if isinstance(fdf.index, pd.MultiIndex):
                        fdf = fdf.reset_index()
                    # Walk backwards from latest row to find one with non-NaN data
                    row_idx = -1
                    for i in range(len(fdf) - 1, -1, -1):
                        candidate = fdf.iloc[i]
                        if any(pd.notna(candidate.get(col)) for col in fields):
                            row_idx = i
                            break
                    row = fdf.iloc[row_idx]
                    pe = float(row.get("pe_ratio")) if "pe_ratio" in fdf.columns and pd.notna(row.get("pe_ratio")) else None
                    pb = float(row.get("pb_ratio_lf")) if "pb_ratio_lf" in fdf.columns and pd.notna(row.get("pb_ratio_lf")) else None
                    mc = row.get("market_cap")
                    if pd.notna(mc):
                        market_cap = float(mc)
                    eps_val = row.get("earnings_per_share")
                    if pd.notna(eps_val):
                        eps = float(eps_val)
        except Exception:
            pass

        result = {
            "symbol": rq_ticker,
            "name": symbol,
            "price": round(last_price, 2),
            "currency": "CNY",
            "change": round(change, 2),
            "change_percent": change_pct,
            "volume": vol,
            "open": float(df["open"].values[-1]),
            "high": float(df["high"].max()),
            "low": float(df["low"].min()),
            "prev_close": prev_close,
            "market_cap": market_cap,
            "pe_ttm": pe,
            "pb": pb,
            "eps": eps,
            "source": "rqdatac",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "market": detect_market(rq_ticker),
        }
        return result
    except Exception as exc:
        logger.warning("fetch_snapshot rqdatac failed: %s", exc)
    return _fallback_snapshot(symbol)


def _fallback_snapshot(symbol: str) -> dict | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_quote_metrics
        result = fetch_cn_hk_quote_metrics(symbol)
        if result:
            result["currency"] = "CNY"
            result["source"] = "eastmoney"
            result["as_of"] = datetime.now(timezone.utc).isoformat()
            return result
    except Exception:
        pass
    return None


def fetch_market_chart(symbol: str, period: str = "1y", interval: str = "1d") -> list[dict[str, Any]] | None:
    df = _load_ohlcv_frame(symbol, period, interval)
    if df is None:
        return None
    rows = []
    for idx, row in df.iterrows():
        rows.append({
            "time": str(idx)[:19] if hasattr(idx, "strftime") else str(idx)[:10],
            "open": float(row.get("open", 0)),
            "close": float(row.get("close", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "volume": float(row.get("volume", 0)),
        })
    return rows


# ── Valuation ────────────────────────────────────────────
def fetch_valuation(symbol: str) -> dict[str, Any] | None:
    rq_ticker = normalize_to_rq(symbol)
    if not rq_ticker:
        return None

    try:
        _ensure_rq()
        import rqdatac

        all_f = rqdatac.get_all_factor_names()
        rq_factors = [f for f in ["pe_ratio", "pe_ratio_2", "pb_ratio_lf", "ps_ratio", "market_cap", "dividend_yield", "ev_to_ebitda"] if f in all_f]
        if not rq_factors:
            return _fallback_valuation(symbol)

        fdf = rqdatac.get_factor(rq_ticker, factor=rq_factors, start_date=_to_date(datetime.now() - timedelta(days=10)), end_date=_to_date())
        if fdf is None or fdf.empty:
            return _fallback_valuation(symbol)

        if isinstance(fdf.index, pd.MultiIndex):
            fdf = fdf.reset_index()
        # Walk backwards to find the last row with a valid factor value
        row = fdf.iloc[-1]
        for i in range(len(fdf) - 1, -1, -1):
            candidate = fdf.iloc[i]
            if any(pd.notna(candidate.get(col)) for col in rq_factors):
                row = candidate
                break

        # 52-week high/low from 1 year of daily prices
        week52_high = week52_low = None
        try:
            yr_ago = datetime.now() - timedelta(days=365)
            pdf = rqdatac.get_price(rq_ticker, start_date=_to_date(yr_ago), end_date=_to_date(), frequency="1d", fields=["close", "high", "low"])
            if pdf is not None and not pdf.empty:
                week52_high = float(pdf["high"].max()) if "high" in pdf.columns else None
                week52_low = float(pdf["low"].min()) if "low" in pdf.columns else None
        except Exception:
            pass

        # Beta via CNE5 style factor exposure
        beta = None
        try:
            bdf = rqdatac.get_style_factor_exposure(rq_ticker, factors=["beta"], start_date=_to_date(datetime.now() - timedelta(days=10)), end_date=_to_date())
            if bdf is not None and not bdf.empty:
                if hasattr(bdf, "iloc"):
                    beta = float(bdf.iloc[-1].iloc[0])
        except Exception:
            pass

        # dividend_yield: rqdatac returns basis points (bps), convert to ratio
        raw_dy = row.get("dividend_yield")
        dividend_yield = None
        if "dividend_yield" in fdf.columns and pd.notna(raw_dy):
            dividend_yield = float(raw_dy) / 10000.0

        return {
            "symbol": rq_ticker,
            "currency": "CNY",
            "trailing_pe": float(row.get("pe_ratio")) if "pe_ratio" in fdf.columns and pd.notna(row.get("pe_ratio")) else None,
            "forward_pe": float(row.get("pe_ratio_2")) if "pe_ratio_2" in fdf.columns and pd.notna(row.get("pe_ratio_2")) else None,
            "price_to_book": float(row.get("pb_ratio_lf")) if "pb_ratio_lf" in fdf.columns and pd.notna(row.get("pb_ratio_lf")) else None,
            "price_to_sales": float(row.get("ps_ratio")) if "ps_ratio" in fdf.columns and pd.notna(row.get("ps_ratio")) else None,
            "ev_to_ebitda": float(row.get("ev_to_ebitda")) if "ev_to_ebitda" in fdf.columns and pd.notna(row.get("ev_to_ebitda")) else None,
            "market_cap": float(row.get("market_cap")) if "market_cap" in fdf.columns and pd.notna(row.get("market_cap")) else None,
            "dividend_yield": dividend_yield,
            "beta": beta,
            "week52_high": week52_high,
            "week52_low": week52_low,
            "source": "rqdatac",
        }
    except Exception as exc:
        logger.warning("fetch_valuation rqdatac failed: %s", exc)
    return _fallback_valuation(symbol)


def _fallback_valuation(symbol: str) -> dict | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_quote_metrics
        q = fetch_cn_hk_quote_metrics(symbol)
        if q:
            return {"symbol": symbol, "currency": "CNY", "trailing_pe": q.get("trailing_pe"), "price_to_book": q.get("price_to_book"), "market_cap": q.get("market_cap"), "source": "eastmoney"}
    except Exception:
        pass
    return None


# ── Financial Statements ─────────────────────────────────
def fetch_financial_statements(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    rq_ticker = normalize_to_rq(symbol)
    if not rq_ticker:
        return None

    try:
        _ensure_rq()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=365 * 3 + 90)

        # Convert dates to quarter format (e.g. '2024q1')
        def _to_quarter(dt: datetime) -> str:
            return f"{dt.year}q{(dt.month - 1) // 3 + 1}"

        fields = [
            "operating_revenue", "profit_from_operation", "net_profit_parent_company",
            "basic_earnings_per_share", "net_profit_deduct_non_recurring_pnl", "gross_profit",
            "total_assets", "total_liabilities", "equity_parent_company",
            "cash_flow_from_operating_activities", "cash_flow_from_investing_activities",
            "cash_flow_from_financing_activities",
        ]
        df = rqdatac.get_pit_financials_ex(rq_ticker, fields=fields, start_quarter=_to_quarter(start), end_quarter=_to_quarter(end))
        if df is None or df.empty:
            return _fallback_financials(symbol, periods)

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        # Find announcement date column (for picking latest revision) and
        # reporting-period column (for period labeling).  These are
        # usually different — e.g. quarter=2025q1 (the reporting period)
        # but info_date=2026-04-30 (when it was announced).
        announcement_col = next((c for c in ["info_date", "announcement_date", "date"] if c in df.columns), None)
        period_col = next((c for c in ["quarter", "end_date", "report_date"] if c in df.columns), announcement_col)

        if not period_col:
            return _fallback_financials(symbol, periods)

        # Deduplicate: for each reporting period, keep only the latest revision
        if period_col and announcement_col and period_col != announcement_col:
            df = df.sort_values(announcement_col, ascending=False)
            df = df.groupby(period_col, as_index=False).first()

        # Sort by reporting period descending (newest first)
        df = df.sort_values(period_col, ascending=False)

        def _period_label(v: object) -> str:
            """Convert a period value to display label like '2025Q1'."""
            s = str(v)
            # Already in quarter format like '2024q1' -> '2024Q1'
            if re.match(r'^\d{4}q[1-4]$', s):
                return s.upper()
            # Date string — parse via _to_period
            return _to_period(s[:10])

        result = {
            "periods": [_period_label(row[period_col]) for _, row in df.head(periods).iterrows()],
            "revenue": [float(row.get("operating_revenue", 0) or 0) for _, row in df.head(periods).iterrows()],
            "gross_profit": [float(row.get("gross_profit", 0) or 0) for _, row in df.head(periods).iterrows()],
            "operating_income": [float(row.get("profit_from_operation", 0) or 0) for _, row in df.head(periods).iterrows()],
            "net_income": [float(row.get("net_profit_parent_company", 0) or 0) for _, row in df.head(periods).iterrows()],
            "eps": [float(row.get("basic_earnings_per_share", 0) or 0) for _, row in df.head(periods).iterrows()],
            "total_assets": [float(row.get("total_assets", 0) or 0) for _, row in df.head(periods).iterrows()],
            "total_liabilities": [float(row.get("total_liabilities", 0) or 0) for _, row in df.head(periods).iterrows()],
            "operating_cash_flow": [float(row.get("cash_flow_from_operating_activities", 0) or 0) for _, row in df.head(periods).iterrows()],
            "source": "rqdatac",
            "market": "CN",
        }
        return result
    except Exception as exc:
        logger.warning("fetch_financial_statements rqdatac failed: %s", exc)
    return _fallback_financials(symbol, periods)


def _fallback_financials(symbol: str, periods: int) -> dict | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_financial_statements
        return fetch_cn_hk_financial_statements(symbol, periods)
    except Exception:
        pass
    return None


def _to_period(dt: str) -> str:
    try:
        d = datetime.strptime(dt[:10], "%Y-%m-%d")
        if d.month == 12 and d.day == 31:
            return f"{d.year}FY"
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    except Exception:
        return dt[:7]


# ── Financial Trends ─────────────────────────────────────
def fetch_revenue_trend(symbol: str) -> list[dict[str, Any]]:
    fs = fetch_financial_statements(symbol, periods=12)
    if not fs:
        return []
    result = []
    for i, period in enumerate(fs.get("periods", [])):
        result.append({
            "period": period,
            "revenue": fs["revenue"][i] if i < len(fs.get("revenue", [])) else None,
            "net_income": fs["net_income"][i] if i < len(fs.get("net_income", [])) else None,
            "eps": fs["eps"][i] if i < len(fs.get("eps", [])) else None,
        })
    return result


def fetch_segment_mix(symbol: str) -> list[dict[str, Any]]:
    # A-share segment mix via Eastmoney
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_financial_statements
        fs = fetch_cn_hk_financial_statements(symbol, periods=1)
        if fs and fs.get("revenue"):
            return [{"segment": "主营业务", "revenue": fs["revenue"][0], "source": "eastmoney"}]
    except Exception:
        pass
    return []


# ── Technical Indicators ─────────────────────────────────
def fetch_technical_indicators(symbol: str) -> dict[str, Any] | None:
    df = _load_ohlcv_frame(symbol, period="1y", interval="1d")
    if df is None or len(df) < 20:
        return None

    close = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)

    # SMA
    sma5 = float(close[-5:].mean())
    sma10 = float(close[-10:].mean())
    sma20 = float(close[-20:].mean())
    sma60 = float(close[-60:].mean()) if len(close) >= 60 else sma20
    latest = float(close[-1])

    # RSI (14)
    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = float(100 - 100 / (1 + gain / loss)) if loss > 0 else 100.0 if gain > 0 else 50.0

    # MACD
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
    macd_line = float(ema12.iloc[-1] - ema26.iloc[-1])
    signal = float(pd.Series(ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1])
    macd_hist = macd_line - signal

    # Vol avg
    vol_avg_20 = float(volume[-20:].mean())
    vol_ratio = float(volume[-1] / vol_avg_20) if vol_avg_20 > 0 else 1.0

    return {
        "symbol": symbol,
        "latest_price": round(latest, 2),
        "sma_5": round(sma5, 2),
        "sma_10": round(sma10, 2),
        "sma_20": round(sma20, 2),
        "sma_60": round(sma60, 2),
        "rsi_14": round(rsi, 1),
        "macd": round(macd_line, 4),
        "macd_signal": round(signal, 4),
        "macd_hist": round(macd_hist, 4),
        "vol_avg_20d": round(vol_avg_20, 0),
        "vol_ratio": round(vol_ratio, 2),
        "source": "rqdatac",
    }


def fetch_indicator_series(symbol: str, n_days: int = 120) -> dict[str, Any] | None:
    df = _load_ohlcv_frame(symbol, period="6mo", interval="1d")
    if df is None or len(df) < 5:
        return None
    close = df["close"].values.astype(float)[-n_days:]
    dates = [str(x)[:10] for x in (df.index[-n_days:] if hasattr(df, "index") else range(len(close)))]
    return {"dates": dates, "close": [float(c) for c in close], "symbol": symbol}


# ── Earnings & Analyst ───────────────────────────────────
def fetch_earnings_history(symbol: str) -> list[dict[str, Any]] | None:
    """Fetch quarterly EPS history from RQData financial statements.

    Returns data compatible with ``EarningsHistoryEntry``
    (quarter, eps_actual), sorted chronologically for the chart.
    """
    fs = fetch_financial_statements(symbol, periods=8)
    if not fs or not fs.get("periods"):
        return None

    result = []
    for i, period in enumerate(fs.get("periods", [])):
        eps_val = fs["eps"][i] if i < len(fs.get("eps", [])) else None
        result.append({
            "quarter": period,
            "eps_estimate": None,
            "eps_actual": eps_val,
            "surprise_pct": None,
        })

    # Financial statements returns newest-first; reverse for chronological
    result.reverse()
    return result


def fetch_analyst_targets(symbol: str) -> dict[str, Any] | None:
    try:
        _ensure_rq()
        import rqdatac
        all_f = rqdatac.get_all_factor_names()
        fields = [f for f in ["forecast_eps", "forecast_net_profit", "rating_score"] if f in all_f]
        if not fields:
            return None
        fdf = rqdatac.get_factor(normalize_to_rq(symbol), factor=fields, start_date=_to_date(datetime.now() - timedelta(days=60)), end_date=_to_date())
        if fdf is None or fdf.empty:
            return None
        if isinstance(fdf.index, pd.MultiIndex):
            fdf = fdf.reset_index()
        row = fdf.iloc[-1]
        return {
            "symbol": symbol,
            "forecast_eps": float(row.get("forecast_eps")) if "forecast_eps" in fdf.columns else None,
            "forecast_net_profit": float(row.get("forecast_net_profit")) if "forecast_net_profit" in fdf.columns else None,
            "rating_score": float(row.get("rating_score")) if "rating_score" in fdf.columns else None,
            "source": "rqdatac",
        }
    except Exception:
        return None


def fetch_recommendations(symbol: str) -> dict[str, Any] | None:
    return fetch_analyst_targets(symbol)


# ── Macro Snapshot ───────────────────────────────────────
def fetch_macro_snapshot() -> dict[str, Any]:
    try:
        _ensure_rq()
        import rqdatac

        end = _to_date()
        start = _to_date(datetime.now() - timedelta(days=120))

        econ_data = {}
        try:
            df = rqdatac.econ.get_money_supply(start_date=start, end_date=end)
            if df is not None and not df.empty:
                if isinstance(df.index, pd.MultiIndex):
                    df = df.reset_index()
                econ_data["money_supply"] = df.head(4).to_dict(orient="records")
        except Exception:
            pass

        # CSI 300 PE
        pe_data = None
        try:
            pdf = rqdatac.index_indicator("000300.XSHG", start_date=start, end_date=end, fields=["pe_ttm", "pb"])
            if pdf is not None and not pdf.empty:
                if isinstance(pdf.index, pd.MultiIndex):
                    pdf = pdf.reset_index()
                latest = pdf.iloc[-1]
                pe_data = {"pe_ttm": float(latest["pe_ttm"]), "pb": float(latest["pb"])}
        except Exception:
            pass

        return {
            "indicator": "沪深300",
            "index_code": "000300.XSHG",
            "valuation": pe_data,
            "macro_data": econ_data,
            "source": "rqdatac",
        }
    except Exception:
        return {"source": "unavailable", "indicator": "N/A"}


def _label_fear_greed(value: float) -> str:
    if value <= 25: return "极度恐惧"
    if value <= 45: return "恐惧"
    if value <= 55: return "中性"
    if value <= 75: return "乐观"
    return "极度乐观"


# ── News ──────────────────────────────────────────────────
def fetch_news(symbol: str, limit: int = 20) -> dict[str, Any]:
    try:
        from backend.tools.news import get_stock_news, score_news_article
        articles = get_stock_news(symbol, days=7, max_results=limit)
        items = []
        for a in (articles or []):
            scoring = score_news_article(a)
            items.append({
                "title": a.get("title", ""),
                "source": a.get("source", ""),
                "url": a.get("url", ""),
                "time": a.get("time", ""),
                "sentiment": a.get("sentiment", 0),
                "impact_score": scoring.get("impact_score", 0.3),
                "source_reliability": scoring.get("source_reliability", 0.5),
            })
        return {"items": items, "count": len(items), "source": "rqdatac"}
    except Exception:
        return {"items": [], "count": 0, "source": "unavailable"}


# ── Sector / Holdings (stubs — A-share equivalents via rqdatac) ─
def fetch_sector_weights(symbol: str, asset_type: str) -> list[dict[str, Any]]:
    try:
        _ensure_rq()
        import rqdatac
        ind = rqdatac.get_instrument_industry(normalize_to_rq(symbol), date=_to_date())
        if ind is not None and not ind.empty:
            name = str(ind.iloc[0].get("industry_name", "")) if len(ind) > 0 else ""
            return [{"sector": name, "weight": 1.0, "source": "rqdatac"}]
    except Exception:
        pass
    return []


def fetch_top_constituents(symbol: str, asset_type: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        _ensure_rq()
        import rqdatac
        if symbol.endswith(".XSHG") and symbol[:6] in ("000300", "000905", "000016", "000688"):
            idx = symbol
        else:
            return []
        comps = rqdatac.index_components(idx, date=_to_date())
        if comps is not None:
            if isinstance(comps, pd.DataFrame):
                return [{"symbol": c, "name": c} for c in comps.iloc[:, 0].tolist()[:limit]]
            return [{"symbol": c, "name": c} for c in comps[:limit] if isinstance(comps, list)]
    except Exception:
        pass
    return []


def fetch_holdings(symbol: str, asset_type: str, limit: int = 50) -> list[dict[str, Any]]:
    return fetch_top_constituents(symbol, asset_type, limit)


