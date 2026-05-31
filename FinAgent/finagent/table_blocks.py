"""章节内嵌 Markdown 表格：固定样式 + 数据驱动渲染。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .chart_catalog import TABLE_CAPTIONS, TABLE_SNAPSHOT_SPECS
from .chart_style import format_factor_display, label, to_percent_points
from .report_format import fmt_money, fmt_num, fmt_pct


def table_caption(table_key: str) -> str:
    return TABLE_CAPTIONS.get(table_key, table_key.replace("_", " "))


def format_table_block(table_key: str, data: dict[str, Any]) -> str | None:
    """渲染单个表格块；无数据时返回 None。"""
    if table_key in TABLE_SNAPSHOT_SPECS:
        return _format_factor_snapshot_table(table_key, data)
    builders = {
        "technical_snapshot_table": _format_technical_snapshot_table,
        "margin_snapshot_table": _format_margin_snapshot_table,
        "margin_period_table": _format_margin_period_table,
        "share_structure_table": _format_share_structure_table,
        "trading_activity_table": _format_trading_activity_table,
        "funding_cost_table": _format_funding_cost_table,
        "dividend_recent_table": _format_dividend_recent_table,
    }
    builder = builders.get(table_key)
    if not builder:
        return None
    rows = builder(data)
    if not rows:
        return None
    caption = table_caption(table_key)
    lines = [f"#### 表 · {caption}", ""]
    lines.extend(rows)
    return "\n".join(lines).strip()


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[str, str]]) -> list[str]:
    if not rows:
        return []
    col_count = len(headers)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * col_count) + " |"]
    lines.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return lines


def _fmt_rate(value: Any) -> str:
    pct = to_percent_points(_safe_float(value))
    if pct is None:
        return "—"
    return f"{pct:.2f}%"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_factor_snapshot_table(table_key: str, data: dict[str, Any]) -> str | None:
    keys = TABLE_SNAPSHOT_SPECS.get(table_key)
    if not keys:
        return None
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    headers = ("维度",) + tuple(label(key) for key in keys)
    cells: list[str] = []
    has_value = False
    for key in keys:
        display = format_factor_display(key, factor.get(key))
        if display is not None:
            has_value = True
        cells.append(display if display is not None else "—")
    if not has_value:
        return None
    caption = table_caption(table_key)
    lines = [f"#### 表 · {caption}", ""]
    lines.extend(_markdown_table(headers, [("最新", *cells)]))
    return "\n".join(lines).strip()


def _format_technical_snapshot_table(data: dict[str, Any]) -> list[str]:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    if not technical:
        return []
    columns = [
        ("最新收盘价", fmt_num(technical.get("latest_close"))),
        ("MA20", fmt_num(technical.get("ma20"))),
        ("MA60", fmt_num(technical.get("ma60"))),
        ("20 日收益率", fmt_pct(technical.get("return_20d"))),
        ("60 日收益率", fmt_pct(technical.get("return_60d"))),
        ("RSI14", fmt_num(technical.get("rsi14"))),
        ("MACD", fmt_num(technical.get("macd"))),
        ("MACD 信号线", fmt_num(technical.get("macd_signal"))),
        ("20 日波动率", fmt_pct(technical.get("volatility_20d"))),
        ("最新回撤", fmt_pct(technical.get("latest_drawdown"))),
        ("最大回撤", fmt_pct(technical.get("max_drawdown"))),
        ("20 日均量", fmt_num(technical.get("avg_volume_20d"))),
    ]
    columns = [(name, value) for name, value in columns if value not in ("—", "-", "N/A", "数据缺失", "")]
    if len(columns) < 3:
        return []
    headers = ("维度",) + tuple(name for name, _ in columns)
    row = ("最新",) + tuple(value for _, value in columns)
    return _markdown_table(headers, [row])


def _format_margin_snapshot_table(data: dict[str, Any]) -> list[str]:
    margin = _latest_margin_row(data)
    if not margin:
        return []
    date_label = str(margin.get("date") or "最新")
    headers = (
        "统计日期",
        "融资余额",
        "融券余额",
        "两融余额",
        "融资买入额",
        "融资偿还额",
        "融券余量",
    )
    row = (
        date_label,
        fmt_money(margin.get("margin_balance")),
        fmt_money(margin.get("short_balance")),
        fmt_money(margin.get("total_balance")),
        fmt_money(margin.get("buy_on_margin_value")),
        fmt_money(margin.get("margin_repayment")),
        fmt_num(margin.get("short_balance_quantity")),
    )
    if sum(1 for value in row[1:] if value not in ("—", "-", "N/A", "数据缺失", "")) < 2:
        return []
    return _markdown_table(headers, [row])


def _format_margin_period_table(data: dict[str, Any]) -> list[str]:
    block = data.get("securities_margin")
    if not isinstance(block, dict):
        return []
    rows_raw = block.get("rows")
    if not isinstance(rows_raw, list) or len(rows_raw) < 2:
        return []
    first = rows_raw[0] if isinstance(rows_raw[0], dict) else {}
    last = rows_raw[-1] if isinstance(rows_raw[-1], dict) else {}
    mb0 = _safe_float(first.get("margin_balance"))
    mb1 = _safe_float(last.get("margin_balance"))
    if mb0 is None or mb1 is None:
        return []
    change = mb1 - mb0
    pct = (change / mb0 * 100) if mb0 else None
    table_rows: list[tuple[str, str]] = [
        ("区间起始", str(first.get("date") or "—")),
        ("区间结束", str(last.get("date") or "—")),
        ("融资余额（期初）", fmt_money(mb0)),
        ("融资余额（期末）", fmt_money(mb1)),
        ("融资余额变动", fmt_money(change)),
        ("变动幅度", f"{pct:.2f}%" if pct is not None else "—"),
    ]
    sb0 = _safe_float(first.get("short_balance"))
    sb1 = _safe_float(last.get("short_balance"))
    if sb0 is not None and sb1 is not None:
        sb_change = sb1 - sb0
        sb_pct = (sb_change / sb0 * 100) if sb0 else None
        table_rows.extend(
            [
                ("融券余额（期初）", fmt_money(sb0)),
                ("融券余额（期末）", fmt_money(sb1)),
                ("融券余额变动", fmt_money(sb_change)),
                ("融券变动幅度", f"{sb_pct:.2f}%" if sb_pct is not None else "—"),
            ]
        )
    peak_date = None
    peak_buy = None
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        buy = _safe_float(item.get("buy_on_margin_value"))
        if buy is None:
            continue
        if peak_buy is None or buy > peak_buy:
            peak_buy = buy
            peak_date = item.get("date")
    if peak_buy is not None:
        table_rows.append(("融资买入峰值", f"{fmt_money(peak_buy)}（{peak_date}）"))
    return _markdown_table(("指标", "数值"), table_rows)


def _format_share_structure_table(data: dict[str, Any]) -> list[str]:
    block = data.get("shares")
    if not isinstance(block, dict):
        return []
    rows_raw = block.get("rows")
    if not isinstance(rows_raw, list) or not rows_raw:
        return []
    latest = rows_raw[-1] if isinstance(rows_raw[-1], dict) else {}
    total = _safe_float(latest.get("total"))
    circ = _safe_float(latest.get("circulation_a"))
    free = _safe_float(latest.get("free_circulation"))
    if not total or total <= 0:
        return []
    non_free_circ = max((circ or 0) - (free or 0), 0)
    other = max(total - (circ or 0), 0)
    locked = non_free_circ + other
    table_rows = [
        ("统计日期", str(latest.get("date") or "最新")),
        ("总股本", fmt_num(total)),
        ("流通 A 股", fmt_num(circ)),
        ("自由流通股本", fmt_num(free)),
        ("自由流通占比", fmt_pct((free or 0) / total, style="ratio")),
        ("非自由流通占比", fmt_pct(locked / total, style="ratio")),
    ]
    if len(rows_raw) >= 2 and isinstance(rows_raw[-2], dict):
        prev = rows_raw[-2]
        prev_total = _safe_float(prev.get("total"))
        if prev_total and prev_total != total:
            delta = total - prev_total
            table_rows.append(("较上期股本变动", fmt_num(delta)))
    return _markdown_table(("项目", "数值"), table_rows)


def _format_trading_activity_table(data: dict[str, Any]) -> list[str]:
    price_block = data.get("price")
    if not isinstance(price_block, dict):
        return []
    price_rows = price_block.get("rows")
    if not isinstance(price_rows, list) or not price_rows:
        return []
    price = pd.DataFrame(price_rows)
    if "date" not in price.columns:
        return []
    price["date"] = pd.to_datetime(price["date"], errors="coerce")
    recent = price.tail(12)
    table_rows: list[tuple[str, str]] = []

    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    if technical.get("avg_volume_20d") is not None:
        table_rows.append(("20 日均量", fmt_num(technical.get("avg_volume_20d"))))

    if "total_turnover" in recent.columns:
        turnover = pd.to_numeric(recent["total_turnover"], errors="coerce").dropna()
        if not turnover.empty:
            table_rows.append(("近12日日均成交额", fmt_money(float(turnover.mean()))))
            max_idx = turnover.idxmax()
            min_idx = turnover.idxmin()
            max_date = recent.loc[max_idx, "date"]
            min_date = recent.loc[min_idx, "date"]
            table_rows.append(
                ("近12日最高成交额", f"{fmt_money(float(turnover.max()))}（{max_date.date()}）")
            )
            table_rows.append(
                ("近12日最低成交额", f"{fmt_money(float(turnover.min()))}（{min_date.date()}）")
            )

    turn_block = data.get("turnover")
    if isinstance(turn_block, dict) and isinstance(turn_block.get("rows"), list):
        turn = pd.DataFrame(turn_block["rows"])
        if "date" in turn.columns and "today" in turn.columns:
            turn["date"] = pd.to_datetime(turn["date"], errors="coerce")
            merged = recent.merge(turn[["date", "today"]], on="date", how="inner")
            rates = pd.to_numeric(merged["today"], errors="coerce").dropna()
            if not rates.empty:
                table_rows.append(
                    ("近12日换手率区间", f"{fmt_pct(float(rates.min()))} ~ {fmt_pct(float(rates.max()))}")
                )

    cf = data.get("capital_flow")
    if isinstance(cf, dict) and int(cf.get("row_count") or 0) == 0:
        table_rows.append(("主力资金流向", "数据缺失"))

    if not table_rows:
        return []
    return _markdown_table(("指标", "数值"), table_rows)


def _format_funding_cost_table(data: dict[str, Any]) -> list[str]:
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    dividend = _safe_float(factor.get("dividend_yield_ttm"))
    if dividend is None:
        return []
    dividend_pct = to_percent_points(dividend)
    table_rows: list[tuple[str, str]] = [("股息率(TTM)", f"{dividend_pct:.2f}%")]

    ir_block = data.get("interbank_rate")
    if isinstance(ir_block, dict) and isinstance(ir_block.get("rows"), list) and ir_block["rows"]:
        latest = ir_block["rows"][-1]
        if isinstance(latest, dict):
            for key, name in (("ON", "Shibor 隔夜"), ("1Y", "Shibor 1年")):
                if latest.get(key) is not None:
                    table_rows.append((name, _fmt_rate(latest.get(key))))

    yc_block = data.get("yield_curve")
    y1_pct = None
    y10_pct = None
    if isinstance(yc_block, dict) and isinstance(yc_block.get("rows"), list) and yc_block["rows"]:
        latest = yc_block["rows"][-1]
        if isinstance(latest, dict):
            if latest.get("1Y") is not None:
                y1_pct = to_percent_points(_safe_float(latest.get("1Y")))
                table_rows.append(("1Y 国债收益率", f"{y1_pct:.2f}%"))
            if latest.get("10Y") is not None:
                y10_pct = to_percent_points(_safe_float(latest.get("10Y")))
                table_rows.append(("10Y 国债收益率", f"{y10_pct:.2f}%"))

    if y1_pct is not None and dividend_pct is not None:
        table_rows.append(("股息率 − 1Y国债", f"{dividend_pct - y1_pct:.2f} pct"))
    if y10_pct is not None and dividend_pct is not None:
        table_rows.append(("股息率 − 10Y国债", f"{dividend_pct - y10_pct:.2f} pct"))

    if len(table_rows) < 2:
        return []
    return _markdown_table(("指标", "数值"), table_rows)


def _format_dividend_recent_table(data: dict[str, Any]) -> list[str]:
    block = data.get("dividend") if isinstance(data.get("dividend"), dict) else {}
    rows_raw = block.get("rows") if isinstance(block.get("rows"), list) else []
    if not rows_raw:
        return []
    rows: list[tuple[str, str]] = []
    for item in rows_raw[-5:]:
        if not isinstance(item, dict):
            continue
        ex_date = str(item.get("ex_dividend_date") or item.get("book_closure_date") or item.get("date") or "")
        amount = item.get("dividend_cash_before_tax") or item.get("cash_amount") or item.get("amount")
        if ex_date and amount is not None:
            rows.append((ex_date, fmt_num(amount)))
    if not rows:
        return []
    return _markdown_table(("除权除息日", "每股税前分红(元)"), rows)


def _latest_margin_row(data: dict[str, Any]) -> dict[str, Any]:
    block = data.get("securities_margin")
    if not isinstance(block, dict):
        return {}
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        return {}
    latest = rows[-1]
    return latest if isinstance(latest, dict) else {}


def table_data_available(table_key: str, data: dict[str, Any]) -> bool:
    return format_table_block(table_key, data) is not None
