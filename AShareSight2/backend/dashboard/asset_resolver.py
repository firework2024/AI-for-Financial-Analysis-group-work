"""Asset type resolver — classify A-share symbols into equity/index."""

import re
from backend.dashboard.schemas import ActiveAsset
from backend.utils.ticker_rq import normalize_to_rq, detect_market

_INDEX_SYMBOLS = {
    "000001.XSHG", "000300.XSHG", "000016.XSHG", "000688.XSHG",
    "000905.XSHG", "000852.XSHG", "000688.XSHG",
    "399001.XSHE", "399006.XSHE", "399005.XSHE",
    "899050.XBEX", "000985.XSHG",
    # Alias formats
    "000001.SS", "000300.SS", "399001.SZ", "399006.SZ",
}


def _looks_like_index(symbol: str) -> bool:
    """Check if a symbol looks like an A-share index."""
    code = re.search(r"(\d{6})", symbol)
    if not code:
        return False
    c = code.group(1)
    # Indices start with 000, 399, 899 etc. in A-share context
    return c.startswith(("000", "399", "899", "9")) or symbol.strip().upper() in _INDEX_SYMBOLS


def resolve_asset(symbol: str, display_name: str | None = None) -> ActiveAsset:
    """Resolve an A-share symbol to an ActiveAsset."""
    sym = symbol.strip().upper()
    rq = normalize_to_rq(sym) or sym
    market = detect_market(rq)

    if _looks_like_index(sym) or rq in _INDEX_SYMBOLS:
        return ActiveAsset(symbol=rq, display_name=display_name or rq, type="index")

    return ActiveAsset(symbol=rq, display_name=display_name or rq, type="equity")


def is_valid_symbol(symbol: str) -> bool:
    """Check if a symbol looks like a valid A-share ticker or index."""
    if not symbol or not symbol.strip():
        return False
    sym = symbol.strip().upper()
    if re.match(r"^\d{6}\.(XSHE|XSHG|XBEX|SS|SZ|BJ)$", sym):
        return True
    if sym in _INDEX_SYMBOLS:
        return True
    return False
