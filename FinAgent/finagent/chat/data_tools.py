"""对话中按需拉取米筐数据快照。"""

from __future__ import annotations

import re
from typing import Any

from ..cninfo import default_as_of, normalize_stock_code, to_order_book_id
from ..env import load_dotenv


LIVE_DATA_HINTS = (
    "最新",
    "现在",
    "当前",
    "今天",
    "实时",
    "股价",
    "收盘",
    "开盘",
    "融资",
    "pe",
    "pb",
    "rsi",
    "macd",
    "均线",
    "市值",
    "换手率",
    "行情",
    "k线",
    "现价",
    "涨跌",
)

_LIVE_DATA_GENERIC = ("查一下", "帮我看", "拉一下", "更新一下")


def needs_live_data(query: str) -> bool:
    q = str(query or "").lower()
    if any(hint in q for hint in LIVE_DATA_HINTS):
        return True
    if any(h in q for h in _LIVE_DATA_GENERIC):
        return any(h in q for h in ("股价", "行情", "收盘", "pe", "pb", "融资", "市值", "换手", "最新"))
    return False


def fetch_market_snapshot(stock_code: str, *, as_of: str | None = None, lookback_days: int = 60) -> dict[str, Any]:
    load_dotenv()
    from pathlib import Path

    code = normalize_stock_code(stock_code)
    order_book_id = to_order_book_id(code)
    as_of_date = default_as_of(as_of)
    try:
        from ..multiagent import data_executor_agent

        data = data_executor_agent(
            order_book_id=order_book_id,
            stock_code=code,
            as_of=as_of_date,
            lookback_days=lookback_days,
            output_dir=Path("outputs"),
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "stock_code": code, "order_book_id": order_book_id}

    return {
        "stock_code": code,
        "order_book_id": order_book_id,
        "as_of": as_of_date.isoformat(),
        "technical": data.get("technical"),
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "price_tail": (data.get("price") or {}).get("rows", [])[-5:],
        "margin_tail": (data.get("securities_margin") or {}).get("rows", [])[-5:],
        "pit_financials_tail": (data.get("pit_financials") or {}).get("rows", [])[-3:],
    }


def extract_stock_code(text: str, fallback: str | None = None) -> str | None:
    match = re.search(r"\b([036]\d{5})\b", str(text or ""))
    if match:
        return match.group(1)
    return fallback
