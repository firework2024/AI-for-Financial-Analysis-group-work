"""Normalize OHLCV payloads from rqdatac / Eastmoney / legacy tools."""

from __future__ import annotations

from typing import Any


def normalize_kline_payload(data: Any) -> dict[str, Any]:
    """Ensure dict has ``kline_data`` list for TechnicalAgent / charts."""
    if not isinstance(data, dict):
        return {"kline_data": [], "error": "invalid_payload"}
    if data.get("kline_data"):
        return data
    rows = data.get("rows")
    if isinstance(rows, list) and rows:
        kline: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            kline.append(
                {
                    "time": row.get("date") or row.get("time"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                }
            )
        out = dict(data)
        out["kline_data"] = kline
        return out
    return data
