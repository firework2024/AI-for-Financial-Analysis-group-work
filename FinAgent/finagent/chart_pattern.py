"""从同源序列提取曲线形态，生成图注（只描述走势/形态，不写具体数值）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .data_registry import CHART_DATA_SOURCE
from .technical import enrich_price_frame, numeric_value_column, resolve_close_column, safe_float


def _rows(key: str, data: dict[str, Any]) -> pd.DataFrame:
    block = data.get(key)
    if not isinstance(block, dict):
        return pd.DataFrame()
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame


def _series(frame: pd.DataFrame, col: str | None = None, stock: str = "") -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    if col and col in frame.columns:
        return pd.to_numeric(frame[col], errors="coerce")
    if stock and stock in frame.columns:
        return pd.to_numeric(frame[stock], errors="coerce")
    picked = numeric_value_column(frame, stock)
    if picked:
        return pd.to_numeric(frame[picked], errors="coerce")
    return pd.Series(dtype=float)


def _trend_shape(values: pd.Series, *, flat_threshold: float = 0.03) -> str:
    clean = values.dropna()
    if len(clean) < 3:
        return "样本较短"
    start = float(clean.iloc[0])
    end = float(clean.iloc[-1])
    if start == 0:
        change = 0.0
    else:
        change = (end - start) / abs(start)
    idx_min = int(clean.values.argmin())
    idx_max = int(clean.values.argmax())
    n = len(clean)
    if 0.2 * n < idx_min < 0.8 * n and change > flat_threshold:
        return "先抑后扬"
    if 0.2 * n < idx_max < 0.8 * n and change < -flat_threshold:
        return "先扬后抑"
    if change > flat_threshold:
        return "整体上行"
    if change < -flat_threshold:
        return "整体下行"
    spread = (float(clean.max()) - float(clean.min())) / (abs(float(clean.mean())) or 1.0)
    if spread > 0.08:
        return "区间震荡"
    return "大体走平"


def _volatility_shape(values: pd.Series) -> str:
    clean = values.dropna()
    if len(clean) < 6:
        return ""
    mid = len(clean) // 2
    early = clean.iloc[:mid].std()
    late = clean.iloc[mid:].std()
    if pd.isna(early) or pd.isna(late):
        return ""
    if late > early * 1.25:
        return "波动逐步放大"
    if late < early * 0.75:
        return "波动趋于收敛"
    return "波动相对平稳"


def _price_volume_shape(price: pd.Series, volume: pd.Series) -> str:
    pt = _trend_shape(price)
    vt = _trend_shape(volume)
    if "上行" in pt and "上行" in vt:
        return "量价同步走强"
    if "下行" in pt and ("下行" in vt or "回落" in vt):
        return "量价同步走弱"
    if "先抑后扬" in pt and "上行" in vt:
        return "反弹阶段量能配合放大"
    if ("上行" in pt or "先抑后扬" in pt) and ("下行" in vt or "走平" in vt):
        return "价格回升但量能偏弱，呈量价背离"
    if "下行" in pt and ("上行" in vt or "放大" in _volatility_shape(volume)):
        return "价格下跌而成交活跃，抛压与承接并存"
    return f"价格{pt}，成交量{vt}"


def _ma_shape(price: pd.DataFrame) -> str:
    if price.empty or "close" not in price.columns:
        return "均线走势待数据补充"
    frame = enrich_price_frame(price)
    close = frame["close"].dropna()
    ma20 = frame["ma20"].dropna()
    ma60 = frame["ma60"].dropna()
    if close.empty or ma20.empty:
        return "均线信号待数据补充"
    last_close = float(close.iloc[-1])
    last_ma20 = float(ma20.iloc[-1])
    last_ma60 = float(ma60.iloc[-1]) if not ma60.empty else last_ma20
    if last_close > last_ma20 > last_ma60:
        return "价格运行在均线之上，短中期趋势偏强"
    if last_close < last_ma20 < last_ma60:
        return "价格运行在均线之下，短中期趋势偏弱"
    if last_close > last_ma60 and last_close < last_ma20:
        return "价格位于短均线下、长均线上，呈现震荡整理"
    if last_close < last_ma60 and last_close > last_ma20:
        return "价格位于短均线上、长均线下，均线多空交织"
    return "价格与均线缠绕，方向尚不明朗"


def _drawdown_shape(price: pd.DataFrame) -> str:
    if price.empty:
        return "回撤曲线待数据补充"
    frame = enrich_price_frame(price)
    dd = frame["drawdown"].dropna()
    if dd.empty:
        return "回撤曲线待数据补充"
    if float(dd.iloc[-1]) > float(dd.iloc[0]):
        return "回撤幅度近期收敛，下行压力缓解"
    if float(dd.min()) == float(dd.iloc[-1]):
        return "回撤仍在加深，风险暴露抬升"
    return "回撤经历加深后有所修复"


def _macd_rsi_shape(price: pd.DataFrame) -> str:
    if price.empty:
        return "动量指标待数据补充"
    frame = enrich_price_frame(price)
    rsi = safe_float(frame["rsi14"].dropna().iloc[-1]) if frame["rsi14"].notna().any() else None
    macd = safe_float(frame["macd"].dropna().iloc[-1]) if frame["macd"].notna().any() else None
    signal = safe_float(frame["macd_signal"].dropna().iloc[-1]) if frame["macd_signal"].notna().any() else None
    parts: list[str] = []
    if rsi is not None:
        if rsi >= 70:
            parts.append("RSI 处于超买区域")
        elif rsi <= 30:
            parts.append("RSI 处于超卖区域")
        elif rsi < 45:
            parts.append("RSI 位于弱势区间")
        elif rsi > 55:
            parts.append("RSI 位于强势区间")
        else:
            parts.append("RSI 位于中性区间")
    if macd is not None and signal is not None:
        if macd > signal and macd > 0:
            parts.append("MACD 位于信号线上方，动能偏强")
        elif macd < signal and macd < 0:
            parts.append("MACD 位于信号线下方，动能偏弱")
        elif macd > signal:
            parts.append("MACD 金叉向上，动能修复")
        else:
            parts.append("MACD 死叉向下，动能走弱")
    return "；".join(parts) if parts else "动量指标整体中性"


def _relative_shape(price: pd.DataFrame, index: pd.DataFrame, stock: str) -> str:
    pcol = resolve_close_column(price)
    icol = resolve_close_column(index)
    if not pcol or not icol or price.empty or index.empty:
        return "相对强弱待数据补充"
    p = pd.to_numeric(price[pcol], errors="coerce").dropna()
    i = pd.to_numeric(index[icol], errors="coerce").dropna()
    if len(p) < 2 or len(i) < 2:
        return "相对强弱待数据补充"
    stock_ret = float(p.iloc[-1] / p.iloc[0] - 1)
    index_ret = float(i.iloc[-1] / i.iloc[0] - 1)
    if stock_ret > index_ret + 0.02:
        return "归一化净值整体强于基准，呈现超额收益"
    if stock_ret < index_ret - 0.02:
        return "归一化净值整体弱于基准，相对表现落后"
    return "与基准走势大体同步，超额收益不明显"


def _bar_dominance(values: pd.Series, *, pos: str, neg: str) -> str:
    clean = values.dropna()
    if clean.empty:
        return "柱状分布待数据补充"
    pos_n = int((clean > 0).sum())
    neg_n = int((clean < 0).sum())
    if pos_n > neg_n * 1.5:
        return pos
    if neg_n > pos_n * 1.5:
        return neg
    return "正负交替，方向不够集中"


def _multi_line_shape(frame: pd.DataFrame, cols: tuple[str, ...]) -> str:
    trends: list[str] = []
    for col in cols:
        if col not in frame.columns:
            continue
        series = pd.to_numeric(frame[col], errors="coerce").dropna()
        if series.empty:
            continue
        trends.append(_trend_shape(series))
    if not trends:
        return "因子曲线待数据补充"
    up = sum("上行" in t or "先抑后扬" in t for t in trends)
    down = sum("下行" in t or "先扬后抑" in t for t in trends)
    if up >= max(2, len(trends) - 1):
        return "多条曲线整体向上，指标同步改善"
    if down >= max(2, len(trends) - 1):
        return "多条曲线整体向下，指标同步走弱"
    return "各曲线走势分化，需结合分项观察"


def _yield_curve_shape(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "收益率曲线待数据补充"
    tenor_cols = [c for c in frame.columns if c not in {"date", "order_book_id"}]
    if not tenor_cols:
        return "收益率曲线待数据补充"
    latest = frame.dropna(subset=tenor_cols, how="all").tail(1)
    if latest.empty:
        return "收益率曲线待数据补充"
    values = [safe_float(latest[col].iloc[0]) for col in tenor_cols]
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return "收益率曲线形态待数据补充"
    short = values[0]
    long = values[-1]
    if short > long:
        return "短端高于长端，曲线形态偏倒挂"
    if long - short > 0.5:
        return "曲线陡峭，长端明显高于短端"
    return "曲线整体平坦，期限利差不大"


def _shibor_shape(frame: pd.DataFrame) -> str:
    cols = [c for c in frame.columns if c not in {"date", "order_book_id"}]
    if not cols:
        return "利率曲线待数据补充"
    short = _series(frame, cols[0]).dropna()
    if short.empty:
        return "利率曲线待数据补充"
    trend = _trend_shape(short)
    vol = _volatility_shape(short)
    text = f"短端利率{trend}"
    return f"{text}，{vol}" if vol else text


def build_chart_pattern(chart_key: str, data: dict[str, Any]) -> dict[str, Any]:
    """返回结构化形态特征，供图注 agent 或测试使用。"""
    stock = str(data.get("order_book_id") or "")
    data_key = CHART_DATA_SOURCE.get(chart_key, "")
    frame = _rows(data_key, data) if data_key else pd.DataFrame()
    price = _rows("price", data)
    patterns: dict[str, Any] = {"chart_key": chart_key}

    if chart_key == "price_volume":
        patterns["shape"] = _price_volume_shape(
            _series(price, "close"),
            _series(price, "volume"),
        )
    elif chart_key == "moving_averages":
        patterns["shape"] = _ma_shape(price)
    elif chart_key in {"nav_curve", "cumulative_return"}:
        patterns["shape"] = _trend_shape(_series(enrich_price_frame(price), "cum_return"))
    elif chart_key == "drawdown":
        patterns["shape"] = _drawdown_shape(price)
    elif chart_key == "technical_indicators":
        patterns["shape"] = _macd_rsi_shape(price)
    elif chart_key == "daily_return":
        series = _series(_rows("price_change_rate", data), stock=stock)
        patterns["shape"] = f"日涨跌幅{_bar_dominance(series, pos='涨多跌少，整体偏强', neg='跌多涨少，整体偏弱')}"
    elif chart_key == "rolling_volatility":
        vol = enrich_price_frame(price).get("vol20")
        if vol is not None:
            patterns["shape"] = f"滚动波动率{_trend_shape(pd.Series(vol))}，{_volatility_shape(pd.Series(vol))}".strip("，")
        else:
            patterns["shape"] = "滚动波动率待数据补充"
    elif chart_key == "relative_return":
        patterns["shape"] = _relative_shape(price, _rows("index_benchmark", data), stock)
    elif chart_key in {"turnover_rate", "turnover_amount"}:
        col = "today" if chart_key == "turnover_rate" else "total_turnover"
        series = _series(frame if not frame.empty else price, col, stock=stock)
        patterns["shape"] = f"{'换手率' if chart_key == 'turnover_rate' else '成交额'}{_trend_shape(series)}"
    elif chart_key == "capital_flow":
        cap = _rows("capital_flow", data)
        net = pd.to_numeric(cap.get("buy_value"), errors="coerce") - pd.to_numeric(
            cap.get("sell_value"), errors="coerce"
        )
        patterns["shape"] = _bar_dominance(net, pos="净流入柱居多，资金方向偏正面", neg="净流出柱居多，资金方向偏负面")
    elif chart_key == "cumulative_capital_flow":
        cap = _rows("capital_flow", data)
        net = pd.to_numeric(cap.get("buy_value"), errors="coerce") - pd.to_numeric(
            cap.get("sell_value"), errors="coerce"
        )
        patterns["shape"] = f"累计净流入曲线{_trend_shape(net.cumsum())}"
    elif chart_key == "buy_sell_value":
        cap = _rows("capital_flow", data)
        buy = _series(cap, "buy_value")
        sell = _series(cap, "sell_value")
        if buy.empty or sell.empty:
            patterns["shape"] = "买卖金额对比待数据补充"
        elif float(buy.mean()) > float(sell.mean()) * 1.05:
            patterns["shape"] = "买入线整体高于卖出线，交易结构偏主动买入"
        elif float(sell.mean()) > float(buy.mean()) * 1.05:
            patterns["shape"] = "卖出线整体高于买入线，交易结构偏主动卖出"
        else:
            patterns["shape"] = "买卖两条曲线交织，多空力量接近"
    elif chart_key == "block_trade_activity":
        amount = _series(frame, "total_turnover") if "total_turnover" in frame.columns else _series(frame, "volume")
        if amount.dropna().empty:
            patterns["shape"] = "大宗成交额待数据补充"
        else:
            pulse = float(amount.max()) > float(amount.mean()) * 2 if amount.mean() else False
            patterns["shape"] = (
                f"大宗成交额{_trend_shape(amount)}，成交呈{'脉冲式' if pulse else '相对分散'}分布"
            )
    elif chart_key == "margin_balances":
        bal = _series(frame, "margin_balance")
        patterns["shape"] = f"融资余额曲线{_trend_shape(bal)}"
    elif chart_key == "margin_activity":
        buy = _series(frame, "buy_on_margin_value")
        patterns["shape"] = f"融资买入活动{_trend_shape(buy)}，杠杆交易{'活跃' if buy.max() > buy.mean() * 1.5 else '相对平稳'}"
    elif chart_key == "valuation_factors":
        patterns["shape"] = _multi_line_shape(frame, ("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"))
    elif chart_key == "market_cap_trend":
        patterns["shape"] = f"总市值曲线{_trend_shape(_series(frame, 'market_cap'))}"
    elif chart_key == "profitability_factors":
        patterns["shape"] = _multi_line_shape(
            frame, ("gross_profit_margin_ttm", "net_profit_margin_ttm", "roe_ttm")
        )
    elif chart_key == "growth_factors":
        patterns["shape"] = _multi_line_shape(
            frame,
            (
                "net_profit_growth_ratio_ttm",
                "operating_revenue_growth_ratio_ttm",
                "gross_profit_growth_ratio_ttm",
            ),
        )
    elif chart_key == "liquidity_factors":
        patterns["shape"] = _multi_line_shape(frame, ("current_ratio", "quick_ratio"))
    elif chart_key == "debt_ratio_trend":
        patterns["shape"] = f"资产负债率曲线{_trend_shape(_series(frame, 'debt_to_asset_ratio'))}"
    elif chart_key == "dividend_history":
        patterns["shape"] = "分红事件呈离散分布，体现派息节奏而非连续曲线"
    elif chart_key == "share_structure":
        patterns["shape"] = "股本结构以阶梯/分段变化为主，反映增发或流通盘调整"
    elif chart_key == "shibor_rates":
        patterns["shape"] = _shibor_shape(frame)
    elif chart_key == "gov_yield_trend":
        patterns["shape"] = _multi_line_shape(frame, ("1Y", "10Y", "30Y"))
    elif chart_key == "yield_curve_snapshot":
        patterns["shape"] = _yield_curve_shape(frame)
    else:
        patterns["shape"] = "曲线形态待数据补充"
    return patterns


def chart_pattern_note(chart_key: str, data: dict[str, Any]) -> str:
    """生成只描述形态的图注正文；无实质形态描述时返回空字符串。"""
    from .chart_catalog import TABLE_SNAPSHOT_KEYS

    if chart_key in TABLE_SNAPSHOT_KEYS:
        return ""
    pattern = build_chart_pattern(chart_key, data)
    shape = str(pattern.get("shape") or "").strip()
    if shape and not shape.endswith("待数据补充"):
        return f"{shape}。"
    return ""
