"""Chinese macro-economic data via rqdatac.

Primary: rqdatac.econ module (M2, CPI, PPI, PMI, reserve ratio, etc.)
Secondary: rqdatac.get_yield_curve (bond yields)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from backend.utils.ticker_rq import normalize_to_rq
from .rqdata_config import init_rqdata

logger = logging.getLogger(__name__)


def _ensure_init():
    if not init_rqdata():
        raise RuntimeError("RQData not initialized")


def _to_date_str(dt) -> str:
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def get_china_money_supply(months: int = 24) -> Optional[dict[str, Any]]:
    """Get M0/M1/M2 money supply data."""
    try:
        _ensure_init()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=months * 31)

        df = rqdatac.econ.get_money_supply(
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
        )
        if df is None or df.empty:
            return None

        if hasattr(df, "index") and isinstance(df.index, type(df.index)):
            df = df.reset_index()

        records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
        return {
            "source": "rqdatac",
            "data": records,
            "latest": records[-1] if records else None,
        }
    except Exception as exc:
        logger.warning("Money supply fetch failed: %s", exc)
        return None


def get_china_macro_factor(factor_name: str, months: int = 60) -> Optional[dict[str, Any]]:
    """Get macro factor data (CPI, PPI, PMI, etc.) via rqdatac.econ.get_factors.

    Common factor names: 'cpi', 'ppi', 'pmi', 'gdp', 'fixed_asset_investment', etc.
    """
    try:
        _ensure_init()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=months * 31)

        df = rqdatac.econ.get_factors(
            factors=[factor_name],
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
        )
        if df is None or df.empty:
            return None

        if hasattr(df, "index") and isinstance(df.index, type(df.index)):
            df = df.reset_index()

        values = df[factor_name].tolist() if factor_name in df.columns else []
        dates = df.iloc[:, 0].tolist() if len(df.columns) > 0 else []

        return {
            "factor": factor_name,
            "source": "rqdatac",
            "dates": [str(d) for d in dates],
            "values": [float(v) if v is not None else None for v in values],
            "latest": float(values[-1]) if values and values[-1] is not None else None,
        }
    except Exception as exc:
        logger.warning("Macro factor '%s' fetch failed: %s", factor_name, exc)
        return None


def get_china_reserve_ratio(months: int = 60) -> Optional[dict[str, Any]]:
    """Get China RRR (reserve requirement ratio) data."""
    try:
        _ensure_init()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=months * 31)

        df = rqdatac.econ.get_reserve_ratio(
            reserve_type="major",
            start_date=_to_date_str(start),
            end_date=_to_date_str(end),
        )
        if df is None or df.empty:
            return None

        if hasattr(df, "index") and isinstance(df.index, type(df.index)):
            df = df.reset_index()

        records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
        return {
            "source": "rqdatac",
            "data": records,
            "latest": records[-1] if records else None,
        }
    except Exception as exc:
        logger.warning("Reserve ratio fetch failed: %s", exc)
        return None


def get_china_bond_yield(tenor: str = "10Y") -> Optional[dict[str, Any]]:
    """Get China government bond yield curve data.

    Args:
        tenor: Bond tenor (e.g., '10Y', '5Y', '2Y', '1Y')
    """
    try:
        _ensure_init()
        import rqdatac

        end = datetime.now()
        start = end - timedelta(days=365)

        df = rqdatac.get_yield_curve(
            date=end.strftime("%Y-%m-%d"),
            tenor=tenor,
            market="cn",
        )
        if df is None or df.empty:
            return None

        if hasattr(df, "index") and isinstance(df.index, type(df.index)):
            df = df.reset_index()

        records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
        return {
            "tenor": tenor,
            "source": "rqdatac",
            "data": records,
        }
    except Exception as exc:
        logger.warning("Bond yield fetch failed: %s", exc)
        return None


def get_market_sentiment() -> Optional[dict[str, Any]]:
    """Get A-share market sentiment indicators.

    Returns: index PE, volume, northbound flow snapshot, etc.
    """
    try:
        _ensure_init()
        import rqdatac

        # CSI 300 PE
        end = _to_date_str(datetime.now())
        start = _to_date_str(datetime.now() - timedelta(days=30))

        pe_df = rqdatac.index_indicator(
            "000300.XSHG",
            start_date=start,
            end_date=end,
            fields=["pe_ttm", "pb"],
        )
        pe_latest = None
        if pe_df is not None and not pe_df.empty:
            if hasattr(pe_df, "index") and isinstance(pe_df.index, type(pe_df.index)):
                pe_df = pe_df.reset_index()
            pe_latest = {
                "pe_ttm": float(pe_df["pe_ttm"].iloc[-1]) if "pe_ttm" in pe_df.columns else None,
                "pb": float(pe_df["pb"].iloc[-1]) if "pb" in pe_df.columns else None,
            }

        return {
            "index": "沪深300",
            "index_code": "000300.XSHG",
            "valuation": pe_latest,
            "source": "rqdatac",
        }
    except Exception as exc:
        logger.warning("Market sentiment fetch failed: %s", exc)
        return None


def get_economic_events() -> list[dict]:
    """Get recent China economic event calendar (placeholder).

    rqdatac does not provide a dedicated economic calendar API.
    This function returns a structured placeholder.
    """
    return [
        {
            "date": None,
            "event": "中国宏观经济数据发布",
            "source": "国家统计局 / 中国人民银行",
            "relevance": "high",
        }
    ]


# Aliases for backward compatibility with agent code
get_fred_data = get_china_macro_factor  # Replaces FRED data with China macro
