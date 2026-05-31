"""行情派生技术指标：供 chart_plots 出图与 multiagent technical 摘要共用。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .chart_style import compute_rsi

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MA_FAST = 20
MA_SLOW = 60
VOL_WINDOW = 20


def trim_plot_frame(frame: pd.DataFrame, skip: int) -> pd.DataFrame:
    if frame.empty or skip <= 0:
        return frame
    if len(frame) <= skip:
        return frame.iloc[0:0].copy()
    return frame.iloc[skip:].reset_index(drop=True)


def technical_indicator_warmup_bars() -> int:
    """RSI/MACD 出图前需剔除的无效热身交易日数（慢线+信号线滞后）。"""
    return max(RSI_PERIOD, MACD_SLOW + MACD_SIGNAL - 1)


def technical_indicator_plot_frame(price: pd.DataFrame) -> pd.DataFrame:
    """截取 RSI/MACD 均已进入有效区间的子序列，避免图左侧误导性波动。"""
    return trim_plot_frame(price, technical_indicator_warmup_bars())


def moving_average_plot_frame(price: pd.DataFrame) -> pd.DataFrame:
    """MA60 满窗后均线才稳定，三条线从此处起绘。"""
    return trim_plot_frame(price, MA_SLOW - 1)


def rolling_volatility_plot_frame(price: pd.DataFrame) -> pd.DataFrame:
    """20 日滚动年化波动率满窗前无统计意义（含首日收益率空值）。"""
    return trim_plot_frame(price, VOL_WINDOW)


def safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def numeric_value_column(
    df: pd.DataFrame,
    stock: str,
    exclude: tuple[str, ...] = ("date", "order_book_id"),
) -> str | None:
    if stock in df.columns:
        return stock
    for col in df.columns:
        if col in exclude:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().any():
            return col
    return None


def resolve_close_column(df: pd.DataFrame) -> str | None:
    if "close" in df.columns:
        return "close"
    return numeric_value_column(df)


def enrich_price_frame(price: pd.DataFrame) -> pd.DataFrame:
    """在行情 DataFrame 上追加均线、MACD、RSI、回撤、波动率等列。"""
    frame = price.copy()
    if frame.empty or "close" not in frame.columns:
        return frame
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
    for col in ("open", "high", "low", "close", "volume", "total_turnover"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["ma20"] = frame["close"].rolling(MA_FAST).mean()
    frame["ma60"] = frame["close"].rolling(MA_SLOW).mean()
    frame["return"] = frame["close"].pct_change()
    base = frame["close"].iloc[0]
    if base and pd.notna(base) and base != 0:
        frame["cum_return"] = frame["close"] / base - 1
    else:
        frame["cum_return"] = pd.NA
    frame["drawdown"] = frame["close"] / frame["close"].cummax() - 1
    frame["rsi14"] = compute_rsi(frame["close"], period=RSI_PERIOD)
    ema12 = frame["close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema26 = frame["close"].ewm(span=MACD_SLOW, adjust=False).mean()
    frame["macd"] = ema12 - ema26
    frame["macd_signal"] = frame["macd"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    frame["macd_hist"] = frame["macd"] - frame["macd_signal"]
    frame["vol20"] = frame["return"].rolling(VOL_WINDOW).std() * (252**0.5) * 100
    return frame


def technical_summary(
    price_df: pd.DataFrame,
    price_change_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if price_df.empty or "close" not in price_df.columns:
        return {}
    close = pd.to_numeric(price_df["close"], errors="coerce")
    volume = pd.to_numeric(price_df["volume"], errors="coerce") if "volume" in price_df.columns else pd.Series(dtype=float)
    enriched = enrich_price_frame(price_df)
    returns = close.pct_change()
    vol20 = returns.rolling(20).std() * (252**0.5)
    latest_change = None
    if price_change_df is not None and not price_change_df.empty:
        value_cols = [c for c in price_change_df.columns if c not in {"date", "order_book_id"}]
        if value_cols:
            latest_change = safe_float(pd.to_numeric(price_change_df[value_cols[0]], errors="coerce").iloc[-1])
    return {
        "latest_close": safe_float(close.iloc[-1]),
        "latest_change_rate": latest_change,
        "return_20d": safe_float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 else None,
        "return_60d": safe_float(close.iloc[-1] / close.iloc[-61] - 1) if len(close) >= 61 else None,
        "ma20": safe_float(enriched["ma20"].iloc[-1]),
        "ma60": safe_float(enriched["ma60"].iloc[-1]),
        "rsi14": safe_float(enriched["rsi14"].iloc[-1]),
        "macd": safe_float(enriched["macd"].iloc[-1]),
        "macd_signal": safe_float(enriched["macd_signal"].iloc[-1]),
        "latest_drawdown": safe_float(enriched["drawdown"].iloc[-1]),
        "max_drawdown": safe_float(enriched["drawdown"].min()) if enriched["drawdown"].notna().any() else None,
        "volatility_20d": safe_float(vol20.iloc[-1]) if vol20.notna().any() else None,
        "avg_volume_20d": safe_float(volume.tail(20).mean()) if not volume.empty else None,
    }
