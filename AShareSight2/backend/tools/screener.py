"""A-share stock screener — uses Eastmoney for A-share screening.

yfinance and FMP screener removed (US market data not relevant for AShareSight).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.tools.http import _http_get
from backend.tools.env import CN_DATA_PRIMARY

logger = logging.getLogger(__name__)

_FMP_SCREENER_URL = "https://financialmodelingprep.com/api/v3/stock-screener"


def screen_stocks(
    market: str = "CN",
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    sort_by: str = "marketCap",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """Screen A-share stocks.

    Currently returns a placeholder. Full implementation using
    rqdatac or Eastmoney screen API can be added later.
    """
    market_norm = str(market or "CN").strip().upper()

    if market_norm not in {"CN"}:
        return {
            "success": False,
            "market": market_norm,
            "items": [],
            "count": 0,
            "error": f"Unsupported market: {market_norm}",
            "source": "not_implemented",
        }

    # TODO: Implement A-share screening via rqdatac or Eastmoney
    logger.info("A-share screener not yet implemented for market=%s", market_norm)
    return {
        "success": False,
        "market": market_norm,
        "items": [],
        "count": 0,
        "error": "A-share screener not implemented",
        "source": "placeholder",
    }
