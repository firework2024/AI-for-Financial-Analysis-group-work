"""从量价序列计算技术指标（供 data_executor 与 SQLite 快照复现共用）。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def technical_summary_from_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "close" not in df.columns:
        return {}
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(dtype=float)
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    return {
        "latest_close": _float(close.iloc[-1]),
        "return_20d": _float(close.iloc[-1] / close.iloc[-20] - 1) if len(close) >= 20 else None,
        "return_60d": _float(close.iloc[-1] / close.iloc[-60] - 1) if len(close) >= 60 else None,
        "ma20": _float(ma20.iloc[-1]),
        "ma60": _float(ma60.iloc[-1]),
        "rsi14": _float(rsi.iloc[-1]),
        "avg_volume_20d": _float(volume.tail(20).mean()) if not volume.empty else None,
    }


def ensure_technical_from_price_rows(payload: dict[str, Any]) -> None:
    """technical 缺项时基于 price.rows 重算并写回 payload（原地修改）。"""
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    rows = price.get("rows") if isinstance(price.get("rows"), list) else []
    if not rows:
        return
    technical = payload.get("technical") if isinstance(payload.get("technical"), dict) else {}
    required = ("latest_close", "return_20d", "return_60d", "ma20", "ma60", "rsi14")
    if all(technical.get(key) is not None for key in required):
        return

    df = pd.DataFrame(rows)
    if df.empty or "close" not in df.columns:
        return
    if "date" in df.columns:
        try:
            df = df.sort_values("date")
        except Exception:
            pass
    computed = technical_summary_from_dataframe(df)
    if not computed:
        return
    merged = dict(technical)
    for key, value in computed.items():
        if merged.get(key) is None and value is not None:
            merged[key] = value
    if merged:
        payload["technical"] = merged
