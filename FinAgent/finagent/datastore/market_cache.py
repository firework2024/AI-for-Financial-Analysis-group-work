"""从 SQLite 已入库序列复现 data_executor 载荷。"""

from __future__ import annotations

from datetime import date
from typing import Any

from .db import META_KEYS, SERIES_KEYS, get_annual_report, get_latest_snapshot, load_series
from .snapshot_merge import market_snapshot_is_stale


class MarketCacheError(RuntimeError):
    """本地数据不可用且禁止外网拉取时抛出。"""


def snapshot_usable_for_executor(
    snapshot: dict[str, Any] | None,
    *,
    as_of: date,
    lookback_days: int,
) -> bool:
    """在线模式的快速路径：快照较新且回看天数覆盖请求。"""
    if snapshot is None:
        return False
    if market_snapshot_is_stale(snapshot, as_of=as_of):
        return False
    stored_lb = snapshot.get("lookback_days")
    if stored_lb is not None and int(stored_lb) < int(lookback_days):
        return False
    return _snapshot_has_price_rows(snapshot)


def _snapshot_has_price_rows(snapshot: dict[str, Any]) -> bool:
    sid = snapshot.get("id")
    if sid is None:
        return False
    series = load_series(int(sid), ["price"], tail=5)
    price = series.get("price") if isinstance(series.get("price"), dict) else {}
    return bool(price.get("rows"))


def local_price_volume_available(stock_code: str) -> bool:
    """本地是否存在非空量价序列（不校验是否最新交易日）。"""
    snapshot = get_latest_snapshot(stock_code)
    return snapshot is not None and _snapshot_has_price_rows(snapshot)


def market_end_date(stock_code: str) -> date | None:
    snapshot = get_latest_snapshot(stock_code)
    if not snapshot:
        return None
    text = str(snapshot.get("end_date") or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def market_is_current(stock_code: str, *, as_of: date | None = None) -> bool:
    """本地量价最新 end_date 是否覆盖最近交易日（用于对话是否需先增量刷新）。"""
    snapshot = get_latest_snapshot(stock_code)
    if not snapshot or not _snapshot_has_price_rows(snapshot):
        return False
    from ..stock_utils import calendar_trading_as_of

    ref = calendar_trading_as_of(as_of) if as_of is not None else calendar_trading_as_of(date.today())
    return not market_snapshot_is_stale(snapshot, as_of=ref)


def _local_cache_warnings(
    snapshot: dict[str, Any],
    *,
    as_of: date | None,
    lookback_days: int,
) -> list[str]:
    notes: list[str] = []
    if as_of is not None and market_snapshot_is_stale(snapshot, as_of=as_of):
        notes.append("本地量价可能不是最新交易日，离线模式仍继续使用。")
    stored_lb = snapshot.get("lookback_days")
    if stored_lb is not None and int(stored_lb) < int(lookback_days):
        notes.append(
            f"本地入库回看为 {int(stored_lb)} 天，少于请求的 {int(lookback_days)} 天，将使用现有全部 K 线。"
        )
    price_rows = 0
    sid = snapshot.get("id")
    if sid is not None:
        block = load_series(int(sid), ["price"], tail=None).get("price")
        if isinstance(block, dict):
            price_rows = len(block.get("rows") or [])
    if price_rows and price_rows < 30:
        notes.append(f"本地量价仅 {price_rows} 条，图表与技术指标可能较简略。")
    return notes


def load_executor_payload_from_snapshot(
    stock_code: str,
    *,
    lookback_days: int = 260,
    relaxed: bool = False,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """
    从 data_snapshots / data_series 组装 executor 载荷。

    relaxed=True（「仅用本地数据」）：
    - 不校验快照是否过期、入库回看是否覆盖请求；
    - 只要有非空 price 序列即返回，并附带 local_cache_warnings。
    """
    snapshot = get_latest_snapshot(stock_code)
    if not snapshot or snapshot.get("id") is None:
        return None
    if not _snapshot_has_price_rows(snapshot):
        return None
    if not relaxed:
        if as_of is not None and market_snapshot_is_stale(snapshot, as_of=as_of):
            return None
        stored_lb = snapshot.get("lookback_days")
        if stored_lb is not None and int(stored_lb) < int(lookback_days):
            return None

    tail_cap = max(260, int(lookback_days))
    series = load_series(int(snapshot["id"]), list(SERIES_KEYS))
    price_block = series.get("price") if isinstance(series.get("price"), dict) else {}
    if not price_block.get("rows"):
        return None

    code = str(stock_code).strip()
    order_book_id = str(snapshot.get("order_book_id") or "").strip() or f"{code}.XSHG"
    meta = dict(snapshot.get("meta") or {}) if isinstance(snapshot.get("meta"), dict) else {}

    payload: dict[str, Any] = {
        "order_book_id": order_book_id,
        "stock_code": code,
        "sec_name": str(meta.get("sec_name") or ""),
        "start_date": str(snapshot.get("start_date") or ""),
        "end_date": str(snapshot.get("end_date") or ""),
        "source": "local_db_relaxed" if relaxed else "local_db_cache",
        "data_snapshot_id": snapshot.get("id"),
        "from_cache": True,
    }

    tail_rules: dict[str, int] = {
        "dividend": 20,
        "suspended": 30,
        "st_stock": 30,
        "interbank_rate": 120,
        "yield_curve": 120,
    }
    for key in SERIES_KEYS:
        block = series.get(key)
        if not isinstance(block, dict):
            continue
        rows = list(block.get("rows") or [])
        cap = tail_rules.get(key, tail_cap)
        if len(rows) > cap:
            rows = rows[-cap:]
        out: dict[str, Any] = {
            "rows": rows,
            "row_count": len(rows),
        }
        if block.get("columns") is not None:
            out["columns"] = block.get("columns")
        if key == "capital_flow" and block.get("net_buy_value_sum") is not None:
            out["net_buy_value_sum"] = block["net_buy_value_sum"]
        payload[key] = out

    for key in META_KEYS:
        value = meta.get(key)
        if value is not None:
            payload[key] = value

    if relaxed and as_of is not None:
        warnings = _local_cache_warnings(snapshot, as_of=as_of, lookback_days=lookback_days)
        if warnings:
            payload["local_cache_warnings"] = warnings
            meta_notes = meta.get("local_cache_warnings")
            if isinstance(meta_notes, list):
                payload["local_cache_warnings"] = list(meta_notes) + warnings
            payload["meta"] = {**meta, "local_cache_warnings": payload["local_cache_warnings"]}

    if not payload["sec_name"]:
        annual = get_annual_report(code)
        if annual and annual.get("sec_name"):
            payload["sec_name"] = str(annual["sec_name"])

    return payload
