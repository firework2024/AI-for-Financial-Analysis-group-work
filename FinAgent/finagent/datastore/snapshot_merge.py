"""行情快照增量合并：在最新快照上追加新交易日，避免重复 INSERT。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from .db import META_KEYS, SERIES_KEYS, _json_default, _locked_connect, get_latest_snapshot, load_series

_DATE_KEYS = ("date", "datetime", "trading_date", "tradedate")


def row_date_key(row: dict[str, Any]) -> str | None:
    for key in _DATE_KEYS:
        value = row.get(key)
        if value is None or value == "":
            continue
        text = str(value)
        if "T" in text:
            text = text.split("T", 1)[0]
        return text[:10]
    return None


def merge_series_payload(
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    *,
    tail: int | None = None,
) -> dict[str, Any]:
    old_rows = list((old or {}).get("rows") or [])
    new_rows = list((new or {}).get("rows") or [])
    if not old_rows:
        base = new or {"rows": [], "row_count": 0}
        rows = list(base.get("rows") or [])
    elif not new_rows:
        rows = old_rows
        base = old
    else:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for row in old_rows + new_rows:
            if not isinstance(row, dict):
                continue
            key = row_date_key(row)
            if key is None:
                key = f"__{len(merged)}"
            if key not in merged:
                order.append(key)
            merged[key] = row
        dated = [k for k in order if not k.startswith("__")]
        undated = [k for k in order if k.startswith("__")]
        dated.sort()
        rows = [merged[k] for k in dated + undated]
        base = new if new_rows else old
    if tail is not None and tail > 0 and len(rows) > tail:
        rows = rows[-tail:]
    columns = (new or {}).get("columns") if new and new.get("columns") is not None else (old or {}).get("columns")
    out: dict[str, Any] = {"rows": rows, "row_count": len(rows)}
    if columns is not None:
        out["columns"] = columns
    for extra in ("net_buy_value_sum",):
        if (new or {}).get(extra) is not None:
            out[extra] = new[extra]
        elif (old or {}).get(extra) is not None:
            out[extra] = old[extra]
    return out


def merge_meta(old_meta: dict[str, Any], new_data: dict[str, Any]) -> dict[str, Any]:
    meta = dict(old_meta or {})
    for key in META_KEYS:
        value = new_data.get(key)
        if value is not None:
            meta[key] = value
    return meta


def incremental_fetch_start(
    end_date: date,
    *,
    lookback_days: int,
    last_end_date: str | None,
    overlap_days: int = 3,
) -> date:
    """在已有快照时，从最近 end_date 起做短窗口拉取（含重叠修正）。"""
    full_start = end_date - timedelta(days=max(30, lookback_days))
    if not last_end_date:
        return full_start
    try:
        last = date.fromisoformat(str(last_end_date)[:10])
    except ValueError:
        return full_start
    if last >= end_date:
        return end_date - timedelta(days=max(overlap_days, min(10, lookback_days)))
    overlap_start = last - timedelta(days=max(0, overlap_days))
    return min(full_start, overlap_start)


def market_snapshot_is_stale(snapshot: dict[str, Any] | None, *, as_of: date | None = None) -> bool:
    if not snapshot:
        return True
    end = str(snapshot.get("end_date") or "")[:10]
    if not end:
        return True
    today = as_of or date.today()
    try:
        last = date.fromisoformat(end)
    except ValueError:
        return True
    if today.weekday() >= 5:
        return (today - last).days > 3
    return last < today - timedelta(days=1)


def upsert_market_snapshot(
    data: dict[str, Any],
    *,
    lookback_days: int | None = None,
    source: str = "data_executor",
) -> int | None:
    """写入行情：有最新快照则原地合并，否则新建。"""
    stock_code = str(data.get("stock_code") or "").strip()
    if not stock_code:
        order_book_id = str(data.get("order_book_id") or "").strip()
        if order_book_id:
            stock_code = order_book_id.split(".")[0]
    if not stock_code:
        return None

    latest = get_latest_snapshot(stock_code)
    tail_cap = max(260, int(lookback_days or 260))
    if latest is None:
        from .db import save_data_snapshot

        return save_data_snapshot(data, stock_code=stock_code, lookback_days=lookback_days, source=source)

    snapshot_id = int(latest["id"])
    existing_series = load_series(snapshot_id)
    merged_series: dict[str, Any] = {}
    for key in SERIES_KEYS:
        old_payload = existing_series.get(key)
        new_payload = data.get(key) if isinstance(data.get(key), dict) else None
        if old_payload is None and new_payload is None:
            continue
        cap = 20 if key in {"dividend", "suspended", "st_stock"} else 120 if key in {"interbank_rate", "yield_curve"} else tail_cap
        merged_series[key] = merge_series_payload(old_payload, new_payload, tail=cap)

    old_meta = latest.get("meta") or {}
    meta = merge_meta(old_meta, data)

    new_start = str(data.get("start_date") or "")[:10]
    new_end = str(data.get("end_date") or "")[:10]
    old_start = str(latest.get("start_date") or "")[:10]
    old_end = str(latest.get("end_date") or "")[:10]
    start_date = new_start
    if old_start and new_start:
        start_date = min(old_start, new_start)
    elif old_start:
        start_date = old_start
    end_date = new_end or old_end

    created_at = datetime.now().isoformat(timespec="seconds")
    order_book_id = str(data.get("order_book_id") or latest.get("order_book_id") or "")
    as_of = end_date or datetime.now().date().isoformat()

    with _locked_connect() as conn:
        conn.execute(
            """
            UPDATE data_snapshots
            SET order_book_id = ?, as_of = ?, lookback_days = ?, start_date = ?, end_date = ?,
                source = ?, meta_json = ?, created_at = ?
            WHERE id = ?
            """,
            (
                order_book_id,
                as_of,
                lookback_days,
                start_date,
                end_date,
                source,
                json.dumps(meta, ensure_ascii=False, default=_json_default),
                created_at,
                snapshot_id,
            ),
        )
        for key, payload in merged_series.items():
            rows_json = json.dumps(payload.get("rows") or [], ensure_ascii=False, default=_json_default)
            columns_json = (
                json.dumps(payload.get("columns"), ensure_ascii=False)
                if payload.get("columns") is not None
                else None
            )
            row_count = int(payload.get("row_count") or len(payload.get("rows") or []))
            updated = conn.execute(
                """
                UPDATE data_series
                SET columns_json = ?, rows_json = ?, row_count = ?
                WHERE snapshot_id = ? AND data_key = ?
                """,
                (columns_json, rows_json, row_count, snapshot_id, key),
            )
            if updated.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO data_series (snapshot_id, data_key, columns_json, rows_json, row_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, key, columns_json, rows_json, row_count),
                )

        conn.execute(
            "DELETE FROM data_snapshots WHERE stock_code = ? AND id != ?",
            (stock_code, snapshot_id),
        )
        conn.execute(
            """
            DELETE FROM data_series
            WHERE snapshot_id NOT IN (SELECT id FROM data_snapshots)
            """
        )

    return snapshot_id
