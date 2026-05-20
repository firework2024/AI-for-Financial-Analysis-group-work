"""A-share ticker format conversion (rqdatac native <-> short suffix)."""

from __future__ import annotations

import re
from typing import Literal

MarketCode = Literal["SH", "SZ", "BJ", "UNKNOWN"]

_SUFFIX_TO_RQ = {
    ".SZ": ".XSHE",
    ".SS": ".XSHG",
    ".BJ": ".XBEX",
}
_RQ_TO_SUFFIX = {v: k for k, v in _SUFFIX_TO_RQ.items()}

_SH_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SZ_PREFIXES = ("000", "001", "002", "003", "300", "301")
_BJ_PREFIX = "8"


def normalize_input_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def to_rqdatac_id(ticker: str) -> str | None:
    """Convert short (.SZ/.SS/.BJ) or bare 6-digit code to rqdatac order_book_id."""
    symbol = normalize_input_ticker(ticker)
    if not symbol:
        return None
    for short, rq in _SUFFIX_TO_RQ.items():
        if symbol.endswith(rq):
            return symbol
        if symbol.endswith(short):
            return symbol[: -len(short)] + rq
    core = re.sub(r"\D", "", symbol)
    if len(core) == 6 and core.isdigit():
        market = detect_market_from_code(core)
        if market == "SH":
            return f"{core}.XSHG"
        if market == "SZ":
            return f"{core}.XSHE"
        if market == "BJ":
            return f"{core}.XBEX"
    return None


def from_rqdatac_id(ticker: str) -> str:
    """Convert rqdatac id to short Yahoo-style suffix (.SZ/.SS/.BJ)."""
    symbol = normalize_input_ticker(ticker)
    for rq, short in _RQ_TO_SUFFIX.items():
        if symbol.endswith(rq):
            return symbol[: -len(rq)] + short
    return symbol


def detect_market_from_code(code: str) -> MarketCode:
    core = re.sub(r"\D", "", str(code or ""))
    if len(core) != 6 or not core.isdigit():
        return "UNKNOWN"
    if core.startswith(_SH_PREFIXES):
        return "SH"
    if core.startswith(_SZ_PREFIXES):
        return "SZ"
    if core.startswith(_BJ_PREFIX):
        return "BJ"
    return "UNKNOWN"


def detect_market(ticker: str) -> MarketCode:
    symbol = normalize_input_ticker(ticker)
    if symbol.endswith((".SS", ".XSHG")):
        return "SH"
    if symbol.endswith((".SZ", ".XSHE")):
        return "SZ"
    if symbol.endswith((".BJ", ".XBEX")):
        return "BJ"
    core = re.sub(r"\D", "", symbol)
    if len(core) == 6:
        return detect_market_from_code(core)
    return "UNKNOWN"


def is_valid_astock_ticker(ticker: str) -> bool:
    return to_rqdatac_id(ticker) is not None


def board_type(ticker: str) -> str:
    """主板 / 创业板 / 科创板 / 北交所（用于涨跌停幅度推断）。"""
    rq = to_rqdatac_id(ticker) or ""
    core = rq.split(".")[0] if rq else ""
    if core.startswith("688") or core.startswith("689"):
        return "STAR"
    if core.startswith(("300", "301")):
        return "ChiNext"
    if core.startswith("8"):
        return "BJ"
    if core.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "Main"
    return "Unknown"


def limit_pct(ticker: str) -> float:
    bt = board_type(ticker)
    if bt in {"STAR", "ChiNext"}:
        return 0.20
    if bt == "BJ":
        return 0.30
    return 0.10


__all__ = [
    "MarketCode",
    "normalize_input_ticker",
    "to_rqdatac_id",
    "from_rqdatac_id",
    "detect_market",
    "detect_market_from_code",
    "is_valid_astock_ticker",
    "board_type",
    "limit_pct",
]
