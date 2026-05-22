"""A-share ticker format conversion utilities.

RQData native format (internal):
  - 000001.XSHE (Shenzhen)
  - 600000.XSHG (Shanghai)
  - 830000.XBEX (Beijing)

Alias format (API input only):
  - 000001.SZ, 600000.SS, 830000.BJ
"""

import re
from typing import Optional

# Market detection patterns
_XSHE_PATTERNS = (".XSHE", ".SZ", "XSHE", "SZ")
_XSHG_PATTERNS = (".XSHG", ".SS", "XSHG", "SS")
_XBEX_PATTERNS = (".XBEX", ".BJ", "XBEX", "BJ")

# Suffix conversion maps
_SUFFIX_TO_RQ = {
    "XSHE": ".XSHE", "SZ": ".XSHE",
    "XSHG": ".XSHG", "SS": ".XSHG",
    "XBEX": ".XBEX", "BJ": ".XBEX",
}

_RQ_MARKET = {
    ".XSHE": "SZ",
    ".XSHG": "SH",
    ".XBEX": "BJ",
}

# Board detection thresholds (stock code ranges)
_BOARD_RANGES = [
    ("主板", "SH", lambda c: c.startswith("60")),
    ("科创板", "SH", lambda c: c.startswith("688")),
    ("主板", "SZ", lambda c: c.startswith("000") or c.startswith("001") or c.startswith("200")),
    ("创业板", "SZ", lambda c: c.startswith("300")),
    ("主板", "BJ", lambda c: True),
]


def normalize_to_rq(ticker: str) -> Optional[str]:
    """Convert any A-share ticker format to RQData native format."""
    if not ticker:
        return None
    t = ticker.strip().upper()
    # Extract the numeric part (6 digits for A-shares)
    match = re.search(r"(\d{6})", t)
    if not match:
        return None
    code = match.group(1)

    # Detect suffix
    for suffix, rq_suffix in _SUFFIX_TO_RQ.items():
        if suffix in t:
            return f"{code}{rq_suffix}"

    # No explicit suffix — infer market from code
    if code.startswith("6"):
        return f"{code}.XSHG"
    elif code.startswith(("0", "3", "2")):
        return f"{code}.XSHE"
    elif code.startswith("8"):
        return f"{code}.XBEX"
    return None


def detect_market(ticker: str) -> str:
    """Detect A-share market: SH / SZ / BJ / UNKNOWN."""
    rq = normalize_to_rq(ticker)
    if not rq:
        return "UNKNOWN"
    for rq_suffix, market in _RQ_MARKET.items():
        if rq.endswith(rq_suffix):
            return market
    return "UNKNOWN"


def detect_board(ticker: str) -> Optional[str]:
    """Detect A-share board: 主板 / 科创板 / 创业板 / 北交所."""
    rq = normalize_to_rq(ticker)
    if not rq:
        return None
    code = rq[:6]
    market = detect_market(ticker)
    for board_name, m, checker in _BOARD_RANGES:
        if market == m and checker(code):
            return board_name
    return None


def is_valid_astock_ticker(ticker: str) -> bool:
    """Check if a ticker looks like a valid A-share stock code."""
    return normalize_to_rq(ticker) is not None


def extract_code(ticker: str) -> Optional[str]:
    """Extract the 6-digit stock code from any ticker format."""
    if not ticker:
        return None
    match = re.search(r"(\d{6})", ticker.strip())
    return match.group(1) if match else None
