"""China macro indicators via rqdatac.econ."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from .rqdata_client import rqdatac_module
from .search import search

logger = logging.getLogger(__name__)


def get_market_sentiment() -> dict[str, Any]:
    """A 股市场情绪摘要（宏观 + 搜索补充）。"""
    macro = get_china_macro_snapshot()
    return {
        "region": "CN",
        "macro": macro,
        "note": "A股情绪需结合北向资金、涨跌停家数、成交额等综合判断",
        "source": "rqdatac_econ",
    }


def get_economic_events() -> list[dict[str, Any]]:
    try:
        hits = search("中国 本月 经济数据 发布 日程 LPR PMI CPI", max_results=5)
        return [{"title": str(h), "source": "search"} for h in (hits or [])[:5]]
    except Exception:
        return []


def get_fred_data(series_id: str = "", start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """兼容旧工具名：改为中国宏观因子。"""
    del series_id, start_date, end_date
    return get_china_macro_snapshot()


def get_china_macro_snapshot() -> dict[str, Any]:
    rq = rqdatac_module()
    out: dict[str, Any] = {"region": "CN", "indicators": {}, "source": "rqdatac_econ"}
    if rq is None:
        out["error"] = "rqdatac_unavailable"
        return out
    end = str(date.today())
    start = (date.today() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    try:
        m2 = rq.econ.get_money_supply(start_date=start, end_date=end)
        if m2 is not None and not m2.empty:
            out["indicators"]["money_supply"] = m2.reset_index().tail(12).to_dict(orient="records")
    except Exception as exc:
        logger.info("[Macro] money_supply: %s", exc)
    try:
        factors = rq.econ.get_factors(
            factors=["CPI", "PPI", "PMI", "GDP"],
            start_date=start,
            end_date=end,
        )
        if factors is not None and not factors.empty:
            out["indicators"]["econ_factors"] = factors.reset_index().tail(24).to_dict(orient="records")
    except Exception as exc:
        logger.info("[Macro] econ factors: %s", exc)
    try:
        rr = rq.econ.get_reserve_ratio(reserve_type="major", start_date=start, end_date=end)
        if rr is not None and not rr.empty:
            out["indicators"]["reserve_ratio"] = rr.reset_index().tail(12).to_dict(orient="records")
    except Exception as exc:
        logger.info("[Macro] reserve_ratio: %s", exc)
    return out
