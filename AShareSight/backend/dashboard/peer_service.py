"""A-share peer comparison via rqdatac + Eastmoney fallback."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Optional

from backend.utils.quote import safe_float
from backend.utils.ticker_rq import from_rqdatac_id, to_rqdatac_id

logger = logging.getLogger(__name__)

_PEER_BATCH_TIMEOUT_SECONDS = 15.0

# 申万一级行业示例同行（静态 fallback）
_SECTOR_PEER_MAP: dict[str, list[str]] = {
    "食品饮料": ["600519.XSHG", "000858.XSHE", "000568.XSHE", "603369.XSHG"],
    "银行": ["600036.XSHG", "601318.XSHG", "601166.XSHG", "600000.XSHG"],
    "医药生物": ["600276.XSHG", "000661.XSHE", "300760.XSHE", "603259.XSHG"],
    "电子": ["002475.XSHE", "603501.XSHG", "688981.XSHG", "000725.XSHE"],
    "电力设备": ["300750.XSHE", "601012.XSHG", "002594.XSHE", "688599.XSHG"],
}

_DEFAULT_PEERS: list[str] = [
    "600519.XSHG",
    "300750.XSHE",
    "600036.XSHG",
    "000858.XSHE",
    "601318.XSHG",
    "000300.XSHG",
]


def _infer_market(symbol: str) -> str:
    if to_rqdatac_id(symbol):
        return "CN"
    ticker = str(symbol or "").strip().upper()
    if ticker.endswith((".SS", ".SZ", ".BJ", ".HK")):
        return "CN" if not ticker.endswith(".HK") else "HK"
    return "US"


def _has_peer_metrics(row: dict[str, Any]) -> bool:
    return any(row.get(k) is not None for k in ("trailing_pe", "price_to_book", "market_cap", "last_price"))


def _fetch_single_peer_metrics(sym: str) -> dict[str, Any]:
    obid = to_rqdatac_id(sym) or sym
    short = from_rqdatac_id(obid)
    result: dict[str, Any] = {"symbol": obid, "name": obid, "currency": "CNY"}

    try:
        from backend.tools.rqdata_price import get_stock_price
        from backend.tools.rqdata_financial import get_company_info

        q = get_stock_price(obid)
        if isinstance(q, dict):
            result["name"] = q.get("name") or obid
            result["last_price"] = q.get("price")
        info = get_company_info(obid)
        if isinstance(info, dict):
            result["name"] = info.get("name") or result["name"]
            result["trailing_pe"] = safe_float(info.get("pe_ttm"))
            result["price_to_book"] = safe_float(info.get("pb"))
            result["market_cap"] = safe_float(info.get("market_cap"))
    except Exception as exc:
        logger.info("[PeerService] rqdatac metrics failed %s: %s", obid, exc)

    if not _has_peer_metrics(result):
        try:
            from backend.tools.cn_hk_market import fetch_cn_hk_quote_metrics

            em = fetch_cn_hk_quote_metrics(short)
            if isinstance(em, dict):
                result.update(
                    {
                        "name": em.get("name") or result["name"],
                        "trailing_pe": safe_float(em.get("trailing_pe")),
                        "price_to_book": safe_float(em.get("price_to_book")),
                        "market_cap": safe_float(em.get("market_cap")),
                        "last_price": safe_float(em.get("last_price")),
                    }
                )
        except Exception as exc:
            logger.info("[PeerService] eastmoney peer failed %s: %s", short, exc)
    return result


def resolve_peers(symbol: str, limit: int = 6) -> list[str]:
    """申万同行业 + 沪深300成分 fallback。"""
    obid = to_rqdatac_id(symbol)
    if not obid:
        return [s for s in _DEFAULT_PEERS if s.upper() != str(symbol).upper()][:limit]

    peers: list[str] = []
    try:
        from backend.tools.rqdata_client import rqdatac_module

        rq = rqdatac_module()
        if rq is not None:
            ind = rq.get_instrument_industry(obid)
            if ind is not None and not ind.empty:
                industry_name = str(ind.iloc[-1].get("first_industry_name") or ind.iloc[-1].get("industry_name") or "")
                if industry_name in _SECTOR_PEER_MAP:
                    peers = list(_SECTOR_PEER_MAP[industry_name])
            if not peers:
                comps = rq.index_components("000300.XSHG")
                if comps:
                    peers = [str(c) for c in list(comps)[:20]]
    except Exception as exc:
        logger.info("[PeerService] rqdatac resolve_peers failed: %s", exc)

    if not peers:
        peers = list(_DEFAULT_PEERS)
    out = []
    for p in peers:
        norm = to_rqdatac_id(p) or p
        if norm.upper() != obid.upper() and norm not in out:
            out.append(norm)
        if len(out) >= limit:
            break
    return out


def fetch_peer_comparison(symbol: str, limit: int = 6, peers: list[str] | None = None) -> dict[str, Any]:
    target = to_rqdatac_id(symbol) or symbol
    if peers:
        peer_symbols = [to_rqdatac_id(p) or p for p in peers if (to_rqdatac_id(p) or p).upper() != target.upper()][:limit]
    else:
        peer_symbols = resolve_peers(target, limit=limit)
    rows: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(peer_symbols) + 1))) as pool:
        futures = {pool.submit(_fetch_single_peer_metrics, target): target}
        for peer in peer_symbols:
            futures[pool.submit(_fetch_single_peer_metrics, peer)] = peer
        try:
            for fut in as_completed(futures, timeout=_PEER_BATCH_TIMEOUT_SECONDS):
                sym = futures[fut]
                try:
                    row = fut.result()
                    if isinstance(row, dict):
                        row["symbol"] = to_rqdatac_id(sym) or sym
                        rows.append(row)
                except Exception as exc:
                    logger.info("[PeerService] peer fetch error %s: %s", sym, exc)
        except FuturesTimeout:
            logger.warning("[PeerService] peer batch timeout for %s", target)

    target_row = next((r for r in rows if (r.get("symbol") or "").upper() == target.upper()), None)
    return {
        "symbol": target,
        "currency": "CNY",
        "target": target_row,
        "peers": [r for r in rows if (r.get("symbol") or "").upper() != target.upper()],
        "industry_source": "shenwan_rqdatac",
    }
