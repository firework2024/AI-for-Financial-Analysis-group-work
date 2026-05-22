"""A-share financial data via RQData.

Primary: rqdatac.get_pit_financials_ex()
Fallback: eastmoney (via cn_hk_market.py)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from backend.utils.ticker_rq import normalize_to_rq
from .rqdata_config import init_rqdata

logger = logging.getLogger(__name__)

# Common financial field mappings (RQData -> our normalized names)
_FINANCIAL_FIELDS = {
    # Income statement
    "total_operating_revenue": "revenue",
    "operating_revenue": "revenue",
    "operating_profit": "operating_income",
    "net_profit_parent_company": "net_income",
    "net_profit": "net_income",
    "basic_eps": "eps",
    "diluted_eps": "diluted_eps",
    "deducted_profit": "deducted_profit",  # 扣非净利润 (CAS specific)
    "gross_profit": "gross_profit",
    "selling_expense": "selling_expense",
    "admin_expense": "admin_expense",
    "research_expense": "research_expense",
    # Balance sheet
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "accounts_receivable": "accounts_receivable",
    "goodwill": "goodwill",
    "intangible_assets": "intangible_assets",
    "inventories": "inventories",
    "equity_parent_company": "equity",
    # Cash flow
    "operating_cash_flow": "operating_cash_flow",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
    "free_cash_flow": "free_cash_flow",
    "capex": "capex",
}


def _ensure_init():
    if not init_rqdata():
        raise RuntimeError("RQData not initialized")


def _to_date_str(dt) -> str:
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def get_financial_statements(
    ticker: str, periods: int = 8, statement_type: str = "all"
) -> Optional[dict[str, Any]]:
    """Get financial statements for A-share ticker via RQData.

    Args:
        ticker: A-share ticker
        periods: Number of quarters to return
        statement_type: 'income', 'balance', 'cashflow', or 'all'

    Returns:
        Dict with structure like:
        { "periods": [...], "revenue": [...], "net_income": [...], "source": "rqdatac" }
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac
    except (ImportError, RuntimeError):
        return _fallback_financials(ticker, periods)

    end = datetime.now()
    # Get ~3 years of data + buffer
    start = end - timedelta(days=365 * 3 + 180)

    try:
        # Map our field names to RQData pit financials field names
        rq_fields = list(_FINANCIAL_FIELDS.keys())

        df = rqdatac.get_pit_financials_ex(
            rq_ticker,
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
            fields=rq_fields,
        )

        if df is None or df.empty:
            return _fallback_financials(ticker, periods)

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        # Build normalized output
        result = _build_normalized_result(df, rq_ticker)
        if result:
            return result

        return _fallback_financials(ticker, periods)
    except Exception as exc:
        logger.warning("rqdatac financials failed for %s: %s", rq_ticker, exc)
        return _fallback_financials(ticker, periods)


def _build_normalized_result(df: pd.DataFrame, ticker: str) -> Optional[dict]:
    """Build normalized financial statement output from rqdatac DataFrame."""
    # Expect columns: date | field1 | field2 | ...
    # or order_book_id | date | field1 | field2 | ...
    date_col = None
    for col in ["date", "day", "report_date", "end_date", "announcement_date"]:
        if col in df.columns:
            date_col = col
            break
    if not date_col:
        return None

    # Sort by date descending
    df = df.sort_values(date_col, ascending=False)

    # Build period -> metrics mapping
    rows = {}
    for _, row in df.iterrows():
        dt = str(row[date_col])[:10]
        period = _date_to_period_label(dt)
        if period not in rows:
            entry = {}
            for rq_field, our_field in _FINANCIAL_FIELDS.items():
                val = row.get(rq_field)
                if pd.notna(val):
                    try:
                        entry[our_field] = round(float(val), 2)
                    except (ValueError, TypeError):
                        entry[our_field] = None
            rows[period] = entry

    periods = sorted(rows.keys(), reverse=True)

    result = {
        "periods": periods,
        "source": "rqdatac",
        "market": "CN",
    }

    # Build arrays for each metric
    for our_field in set(_FINANCIAL_FIELDS.values()):
        result[our_field] = [rows.get(p, {}).get(our_field) for p in periods]

    # Only return if we have meaningful data
    has_data = any(
        result.get(key)
        for key in ["revenue", "net_income", "total_assets", "operating_cash_flow"]
    )
    if has_data and result["periods"]:
        return result
    return None


def _date_to_period_label(dt: str) -> str:
    """Convert '2025-03-31' -> '2025Q1' or '2025FY'."""
    try:
        d = datetime.strptime(dt[:10], "%Y-%m-%d")
        if d.month == 12 and d.day == 31:
            return f"{d.year}FY"
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    except ValueError:
        return dt


def _fallback_financials(ticker: str, periods: int) -> Optional[dict]:
    """Fallback to eastmoney for financial statements."""
    try:
        from .cn_hk_market import fetch_cn_hk_financial_statements

        result = fetch_cn_hk_financial_statements(ticker, periods)
        if result:
            result["source"] = "eastmoney"
            return result
    except Exception as exc:
        logger.info("Eastmoney financials fallback failed: %s", exc)
    return None


def get_company_info(ticker: str) -> Optional[dict[str, Any]]:
    """Get company basic info and valuation metrics for A-share ticker."""
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac
    except (ImportError, RuntimeError):
        return None

    try:
        # Get instrument basic info
        instr = rqdatac.instruments(rq_ticker)
        if instr is None:
            return None

        info = {
            "symbol": rq_ticker,
            "company_name": getattr(instr, "display_name", getattr(instr, "symbol", "")),
            "listed_date": str(getattr(instr, "listed_date", "")),
            "de_listed_date": str(getattr(instr, "de_listed_date", "")),
            "board": str(getattr(instr, "board", "")),
            "sector": str(getattr(instr, "sector", "")),
            "industry": str(getattr(instr, "industry", "")),
            "market": "CN",
            "source": "rqdatac",
        }

        # Get latest factor-based valuation
        end = datetime.now()
        start = end - timedelta(days=30)

        factor_fields = ["pe_ttm", "pb_lf", "ps_ttm", "market_cap", "dividend_yield_ratio"]
        all_factors = rqdatac.get_all_factor_names()
        available = [f for f in factor_fields if f in all_factors]

        if available:
            factor_df = rqdatac.get_factor(
                rq_ticker,
                factor=available,
                start_date=_to_date_str(start),
                end_date=_to_date_str(end),
            )
            if factor_df is not None and not factor_df.empty:
                if isinstance(factor_df.index, pd.MultiIndex):
                    factor_df = factor_df.reset_index()
                latest = factor_df.iloc[-1].to_dict()
                for f in available:
                    val = latest.get(f)
                    if pd.notna(val):
                        info[f] = round(float(val), 2) if isinstance(val, (int, float)) else val

        return info
    except Exception as exc:
        logger.warning("Company info failed for %s: %s", rq_ticker, exc)
        return None


def get_earnings_estimates(ticker: str) -> Optional[dict[str, Any]]:
    """Get consensus earnings estimates (一致预期) for A-share ticker.

    Note: Requires rqdatac consensus expectations data module.
    Returns None if data is not available.
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return None

    try:
        _ensure_init()
        import rqdatac
    except (ImportError, RuntimeError):
        return None

    try:
        # Try to get consensus forecast via factor data
        end = datetime.now()
        start = end - timedelta(days=30)

        all_factors = rqdatac.get_all_factor_names()
        forecast_fields = [
            f for f in [
                "forecast_eps", "forecast_net_profit",
                "forecast_revenue", "rating_score",
            ] if f in all_factors
        ]

        if not forecast_fields:
            return None

        df = rqdatac.get_factor(
            rq_ticker,
            factor=forecast_fields,
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
        )
        if df is None or df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        latest = df.iloc[-1].to_dict()
        return {
            "symbol": rq_ticker,
            "source": "rqdatac",
            "estimates": {k: float(v) if pd.notna(v) else None for k, v in latest.items()},
        }
    except Exception as exc:
        logger.warning("Earnings estimates failed for %s: %s", ticker, exc)
        return None


def resolve_company_ticker(name: str) -> Optional[str]:
    """Resolve a Chinese company name or aliases to A-share ticker.

    Uses instruments and ticker_mapping for lookup.
    """
    # First try direct lookup via instruments
    try:
        _ensure_init()
        import rqdatac

        all_stocks = rqdatac.all_instruments(type="CS")
        if all_stocks is not None and not all_stocks.empty:
            if isinstance(all_stocks.index, pd.MultiIndex):
                all_stocks = all_stocks.reset_index()

            # Search by display_name or symbol
            name_lower = name.strip().lower()
            for _, row in all_stocks.iterrows():
                display = str(row.get("display_name", "")).lower()
                sym = str(row.get("symbol", "")).lower()
                if name_lower in display or name_lower in sym:
                    return str(row.get("order_book_id", row.get("symbol", "")))
    except Exception:
        pass

    return None
