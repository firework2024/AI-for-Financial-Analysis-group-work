"""A-share peer comparison data service.

Resolves peer symbols based on 申万 industry classification via rqdatac.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Optional

from backend.utils.quote import safe_float
from backend.utils.ticker_rq import normalize_to_rq

logger = logging.getLogger(__name__)

_PEER_BATCH_TIMEOUT_SECONDS = 15.0

# Shenwan (申万) industry peer map
_SECTOR_PEER_MAP: dict[str, list[str]] = {
    "食品饮料": ["600519.XSHG", "000858.XSHE", "600809.XSHG", "002304.XSHE", "000568.XSHE"],
    "银行": ["601398.XSHG", "601939.XSHG", "600036.XSHG", "000001.XSHE", "601288.XSHG"],
    "医药生物": ["600276.XSHG", "000538.XSHE", "300760.XSHE", "002001.XSHE", "300015.XSHE"],
    "电子": ["002475.XSHE", "000725.XSHE", "603986.XSHG", "300433.XSHE", "688981.XSHG"],
    "电力设备": ["300750.XSHE", "601012.XSHG", "002129.XSHE", "600438.XSHG", "300274.XSHE", "300014.XSHE"],
    "汽车": ["002594.XSHE", "601633.XSHG", "000625.XSHE", "600104.XSHG"],
    "非银金融": ["601318.XSHG", "600030.XSHG", "601688.XSHG", "601601.XSHG", "601628.XSHG"],
    "家用电器": ["000333.XSHE", "000651.XSHE", "002032.XSHE", "600690.XSHG"],
    "计算机": ["002415.XSHE", "002230.XSHE", "688111.XSHG", "300454.XSHE"],
    "房地产": ["000002.XSHE", "600048.XSHG", "001979.XSHE", "600383.XSHG"],
}

_DEFAULT_PEERS: list[str] = [
    "600519.XSHG", "300750.XSHE", "000858.XSHE", "600036.XSHG",
    "601318.XSHG", "002594.XSHE", "600276.XSHG", "000333.XSHE",
    "601012.XSHG", "600900.XSHG",
]


def _ensure_rq():
    from backend.tools.rqdata_config import init_rqdata
    if not init_rqdata():
        raise RuntimeError("RQData not initialized")


def resolve_peer_symbols(symbol: str, limit: int = 8) -> list[str]:
    """Resolve peer symbols for an A-share ticker via industry classification."""
    rq_sym = normalize_to_rq(symbol)
    if not rq_sym:
        return _DEFAULT_PEERS[:limit]

    try:
        _ensure_rq()
        import rqdatac
        from datetime import datetime

        ind = rqdatac.get_instrument_industry(rq_sym, date=datetime.now().strftime("%Y-%m-%d"))
        if ind is not None and not ind.empty:
            industry_name = str(ind.iloc[0].get("industry_name", "")) if len(ind) > 0 else ""
            ind_code = str(ind.iloc[0].get("industry_code", "")) if len(ind) > 0 else ""

            # Try to get peers from same industry
            if ind_code:
                stocks = rqdatac.industry(ind_code, date=datetime.now().strftime("%Y-%m-%d"))
                if stocks is not None and isinstance(stocks, list):
                    peers = [s for s in stocks if s != rq_sym]
                    return peers[:limit]

            # Fallback to sector-level
            if industry_name:
                for sector_name, tickers in _SECTOR_PEER_MAP.items():
                    if sector_name in industry_name:
                        return tickers[:limit]
    except Exception as exc:
        logger.info("Peer resolution failed for %s: %s", symbol, exc)

    return _DEFAULT_PEERS[:limit]


def fetch_peer_comparison(symbol: str, peers: Optional[list[str]] = None) -> dict[str, Any]:
    """Fetch valuation comparison between target and peers."""
    if peers is None:
        peers = resolve_peer_symbols(symbol)

    rq_sym = normalize_to_rq(symbol)
    if not rq_sym:
        return {"error": "invalid_symbol", "subject_symbol": symbol, "peers": [], "items": []}

    all_tickers = [rq_sym] + [normalize_to_rq(p) for p in peers if normalize_to_rq(p)]
    if not all_tickers:
        return {"error": "no_peers", "subject_symbol": symbol, "items": []}

    try:
        _ensure_rq()
        import rqdatac
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=10)
        fields = ["pe_ttm", "pb_lf", "market_cap", "close"]
        all_f = rqdatac.get_all_factor_names()
        factor_fields = [f for f in fields if f in all_f]
        factor_fields = [f for f in factor_fields if f != "close"]

        items = []
        for t in all_tickers:
            try:
                fdf = rqdatac.get_factor(
                    t, factor=factor_fields,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                )
                price_df = rqdatac.get_price(
                    t, start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                    frequency="1d", fields=["close"],
                )

                pe = pb = mc = price = None
                if fdf is not None and not fdf.empty:
                    if hasattr(fdf, "index") and isinstance(fdf.index, type(pd.DataFrame)):
                        pass
                    last_row = fdf.iloc[-1] if len(fdf) > 0 else {}
                    pe = float(last_row.get("pe_ttm")) if "pe_ttm" in fdf.columns else None
                    pb = float(last_row.get("pb_lf")) if "pb_lf" in fdf.columns else None
                    mc = float(last_row.get("market_cap")) if "market_cap" in fdf.columns else None

                if price_df is not None and not price_df.empty:
                    prices = price_df["close"].values
                    price = float(prices[-1]) if len(prices) > 0 else None

                items.append({
                    "symbol": t,
                    "pe_ttm": pe,
                    "pb": pb,
                    "market_cap": mc,
                    "price": price,
                    "is_target": t == rq_sym,
                })
            except Exception:
                items.append({"symbol": t, "is_target": t == rq_sym})

        return {
            "subject_symbol": rq_sym,
            "peers": [
                {"symbol": i["symbol"], "trailing_pe": i.get("pe_ttm"), "price_to_book": i.get("pb"), "market_cap": i.get("market_cap")}
                for i in items if not i.get("is_target")
            ],
            "items": items, "source": "rqdatac"
        }
    except Exception as exc:
        logger.warning("Peer comparison failed: %s", exc)
        return {"error": str(exc), "subject_symbol": symbol, "peers": [], "items": []}
