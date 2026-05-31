"""多股票解析与会话绑定。"""

from __future__ import annotations

import re
from typing import Any

from ..cninfo import normalize_stock_code

_MAX_STOCKS = 8
_SPLIT_RE = re.compile(r"[,，、;/\s]+")


def normalize_stock_codes_list(
    codes: list[str] | None = None,
    *,
    single: str | None = None,
    text: str | None = None,
) -> list[str]:
    """合并代码列表、单代码与自由文本，去重保序。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        if not raw:
            return
        code = str(raw).strip()
        if not re.fullmatch(r"\d{6}", code):
            return
        code = normalize_stock_code(code)
        if code in seen:
            return
        seen.add(code)
        ordered.append(code)

    for item in codes or []:
        _add(item)
    _add(single)
    if text:
        for code in parse_stock_codes_text(text):
            _add(code)
    return ordered[:_MAX_STOCKS]


def parse_stock_codes_text(text: str) -> list[str]:
    """从「600519,比亚迪 宁德时代」等文本解析多个 6 位代码。"""
    from .data_tools import _code_from_aliases, _code_from_cninfo_name, _code_from_sec_name, extract_stock_code

    blob = str(text or "").strip()
    if not blob:
        return []

    found: list[str] = []
    seen: set[str] = set()

    def _push(code: str | None) -> None:
        if not code:
            return
        c = normalize_stock_code(code)
        if c in seen:
            return
        seen.add(c)
        found.append(c)

    for part in _SPLIT_RE.split(blob):
        piece = part.strip()
        if not piece:
            continue
        _push(extract_stock_code(piece))
        _push(_code_from_aliases(piece))
        if not re.fullmatch(r"\d{6}", piece):
            _push(_code_from_cninfo_name(piece))
            _push(_code_from_sec_name(piece))

    for match in re.finditer(r"\b([036]\d{5})\b", blob):
        _push(match.group(1))

    if len(found) <= 1:
        _push(_code_from_aliases(blob))
        if len(found) <= 1:
            _push(_code_from_cninfo_name(blob))

    return found[:_MAX_STOCKS]


def merge_session_stock_codes(session: Any, codes: list[str]) -> list[str]:
    """写入 session.stock_codes，并同步 stock_code 主代码。"""
    merged = normalize_stock_codes_list(
        getattr(session, "stock_codes", None) or [],
        single=getattr(session, "stock_code", None),
    )
    for code in codes:
        merged = normalize_stock_codes_list(merged, single=code)
    session.stock_codes = merged
    session.stock_code = merged[0] if merged else None
    return merged


def stocks_display_label(codes: list[str], *, max_show: int = 4) -> str:
    if not codes:
        return ""
    if len(codes) <= max_show:
        return "、".join(codes)
    head = "、".join(codes[:max_show])
    return f"{head} 等{len(codes)}只"
