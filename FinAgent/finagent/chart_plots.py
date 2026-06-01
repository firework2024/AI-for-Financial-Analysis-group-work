"""多智能体报告固定模板图表（研报级样式）。

本模块是 ``dynamic_chart_pipeline`` 的 ``chart_agent_fn`` 实现：
- 已知 chart_key → 走固定模板（本文件）
- 未知 chart_key → ``chart_codegen_agent`` 生成参数化规格 → ``execute_parametric_chart``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .chart_style import (
    PALETTE,
    SERIES_COLORS,
    add_ref_line,
    add_zero_line,
    bar_on_dates,
    chart_title,
    close_figure,
    factor_to_chart_scale,
    label,
    new_figure,
    plot_category_bars,
    plot_line,
    prepare_date_index,
    save_chart,
    setup_matplotlib,
    snapshot_bar_value,
    style_axes,
    style_legend,
    style_twin_axes,
    to_percent_points,
)
from .peer_analysis import FACTOR_LABELS
from .technical import (
    enrich_price_frame,
    moving_average_plot_frame,
    numeric_value_column,
    resolve_close_column,
    rolling_volatility_plot_frame,
    safe_float,
    technical_indicator_plot_frame,
)


def chart_agent(*, data: dict[str, Any], output_dir: Path, only_keys: set[str] | None = None) -> dict[str, str]:
    from .progress import step, info

    setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    stock = str(data.get("order_book_id") or "")
    step("读取数据帧", f"股票: {stock}")
    price = pd.DataFrame(data["price"]["rows"])
    price_change = pd.DataFrame(data.get("price_change_rate", {}).get("rows", []))
    index_benchmark = pd.DataFrame(data.get("index_benchmark", {}).get("rows", []))
    block_trade = pd.DataFrame(data.get("block_trade", {}).get("rows", []))
    turnover = pd.DataFrame(data["turnover"]["rows"])
    capital = pd.DataFrame(data["capital_flow"]["rows"])
    margin = pd.DataFrame(data.get("securities_margin", {}).get("rows", []))
    info(f"量价数据: {len(price)} 行, 换手率: {len(turnover)} 行, 资金流: {len(capital)} 行, 两融: {len(margin)} 行")
    dividend = pd.DataFrame(data.get("dividend", {}).get("rows", []))
    shares = pd.DataFrame(data.get("shares", {}).get("rows", []))
    interbank_rate = pd.DataFrame(data.get("interbank_rate", {}).get("rows", []))
    yield_curve = pd.DataFrame(data.get("yield_curve", {}).get("rows", []))
    factor_history = pd.DataFrame(data.get("factor_history", {}).get("rows", []))
    factor_latest = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    charts: dict[str, str] = {}
    charts.update(_plot_industry_comparison_charts(data.get("industry_comparison"), output_dir, stock))

    if not price.empty:
        price = enrich_price_frame(price)

        fig, ax1 = new_figure()
        plot_line(ax1, price["date"], price["close"], color=PALETTE["primary"], linewidth=2)
        ax2 = ax1.twinx()
        bar_on_dates(ax2, price["date"], price["volume"], color=PALETTE["muted"], alpha=0.22, width=0.85)
        style_axes(ax1, title=chart_title(stock, "price_volume"), ylabel=label("close"), date_index=price["date"])
        ax2.set_ylabel(label("volume"), color="#94A3B8", fontsize=9)
        style_twin_axes(ax2)
        path = output_dir / "price_volume.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["price_volume"] = str(path)

        ma = moving_average_plot_frame(price)
        if not ma.empty:
            fig, ax = new_figure()
            plot_line(ax, ma["date"], ma["close"], color=PALETTE["text"], linewidth=1.6, label=label("close"))
            plot_line(ax, ma["date"], ma["ma20"], color=PALETTE["secondary"], linewidth=1.6, label=label("MA20"))
            plot_line(ax, ma["date"], ma["ma60"], color=PALETTE["accent"], linewidth=1.6, label=label("MA60"))
            style_axes(ax, title=chart_title(stock, "moving_averages"), ylabel=label("close"), date_index=ma["date"])
            style_legend(ax)
            path = output_dir / "moving_averages.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["moving_averages"] = str(path)

        base_close = price["close"].iloc[0]
        if base_close and pd.notna(base_close) and base_close != 0:
            price["nav"] = price["close"] / base_close
            fig, ax = new_figure()
            plot_line(ax, price["date"], price["nav"], color=PALETTE["secondary"], linewidth=2)
            add_ref_line(ax, 1.0)
            style_axes(ax, title=chart_title(stock, "nav_curve"), ylabel=label("nav"), date_index=price["date"])
            path = output_dir / "nav_curve.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["nav_curve"] = str(path)

        fig, ax = new_figure()
        plot_line(ax, price["date"], price["cum_return"], color=PALETTE["purple"], linewidth=2)
        add_zero_line(ax)
        style_axes(ax, title=chart_title(stock, "cumulative_return"), ylabel=label("cum_return"), date_index=price["date"])
        path = output_dir / "cumulative_return.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["cumulative_return"] = str(path)

        fig, ax = new_figure()
        x_idx, _ = prepare_date_index(price["date"])
        ax.fill_between(x_idx, price["drawdown"], 0, color=PALETTE["negative"], alpha=0.28, zorder=2)
        plot_line(ax, price["date"], price["drawdown"], color=PALETTE["negative"], linewidth=1.2, alpha=0.85)
        style_axes(ax, title=chart_title(stock, "drawdown"), ylabel=label("drawdown"), date_index=price["date"])
        path = output_dir / "drawdown.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["drawdown"] = str(path)

        tech = technical_indicator_plot_frame(price)
        if not tech.empty:
            fig, (ax1, ax2) = new_figure(nrows=2, sharex=True)
            _, dt_idx = prepare_date_index(tech["date"])
            plot_line(ax1, dt_idx, tech["rsi14"], color=PALETTE["positive"], linewidth=1.6)
            add_ref_line(ax1, 70, color="#FCA5A5")
            add_ref_line(ax1, 30, color="#86EFAC")
            style_axes(ax1, title=chart_title(stock, "technical_indicators"), ylabel=label("rsi14"))
            bar_on_dates(ax2, dt_idx, tech["macd_hist"], color=PALETTE["neutral"], alpha=0.45, width=0.85)
            plot_line(ax2, dt_idx, tech["macd"], color=PALETTE["secondary"], linewidth=1.4, label=label("macd"))
            plot_line(ax2, dt_idx, tech["macd_signal"], color=PALETTE["negative"], linewidth=1.4, label=label("macd_signal"))
            style_axes(ax2, ylabel="MACD", date_index=dt_idx)
            style_legend(ax2, loc="upper left", ncol=2)
            path = output_dir / "technical_indicators.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["technical_indicators"] = str(path)

        if "total_turnover" in price.columns and price["total_turnover"].notna().any():
            fig, ax = new_figure()
            plot_line(ax, price["date"], price["total_turnover"], color=PALETTE["accent"], linewidth=1.8)
            style_axes(ax, title=chart_title(stock, "turnover_amount"), ylabel="成交额", date_index=price["date"])
            path = output_dir / "turnover_amount.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["turnover_amount"] = str(path)

        vol = rolling_volatility_plot_frame(price)
        if not vol.empty and vol["vol20"].notna().any():
            fig, ax = new_figure()
            plot_line(ax, vol["date"], vol["vol20"], color=PALETTE["purple"], linewidth=1.8)
            style_axes(ax, title=chart_title(stock, "rolling_volatility"), ylabel="年化波动率 (%)", date_index=vol["date"])
            path = output_dir / "rolling_volatility.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["rolling_volatility"] = str(path)

    if not price_change.empty and "date" in price_change.columns:
        price_change["date"] = pd.to_datetime(price_change["date"])
        value_col = numeric_value_column(price_change, stock)
        if value_col:
            price_change[value_col] = pd.to_numeric(price_change[value_col], errors="coerce")
            plot_change = price_change.dropna(subset=[value_col]).tail(120)
            if not plot_change.empty:
                fig, ax = new_figure()
                pct_values = plot_change[value_col] * 100
                colors = [PALETTE["up"] if v >= 0 else PALETTE["down"] for v in pct_values]
                bar_on_dates(ax, plot_change["date"], pct_values, color=colors, alpha=0.82, width=0.82)
                add_zero_line(ax)
                style_axes(ax, title=chart_title(stock, "daily_return"), ylabel="日涨跌幅 (%)", date_index=plot_change["date"])
                path = output_dir / "daily_return.png"
                save_chart(fig, path)
                close_figure(fig)
                charts["daily_return"] = str(path)

    if not price.empty and not index_benchmark.empty and "date" in index_benchmark.columns:
        index_benchmark["date"] = pd.to_datetime(index_benchmark["date"])
        index_close_col = resolve_close_column(index_benchmark)
        if index_close_col:
            index_benchmark[index_close_col] = pd.to_numeric(index_benchmark[index_close_col], errors="coerce")
            merged = price[["date", "close"]].merge(
                index_benchmark[["date", index_close_col]].rename(columns={index_close_col: "index_close"}),
                on="date",
                how="inner",
            )
            if len(merged) >= 2:
                stock_nav = merged["close"] / merged["close"].iloc[0]
                index_nav = merged["index_close"] / merged["index_close"].iloc[0]
                benchmark = data.get("benchmark_index") if isinstance(data.get("benchmark_index"), dict) else {}
                bench_label = str(benchmark.get("label") or "基准指数")
                fig, ax = new_figure()
                plot_line(ax, merged["date"], stock_nav, color=PALETTE["primary"], linewidth=1.8, label="标的")
                plot_line(ax, merged["date"], index_nav, color=PALETTE["muted"], linewidth=1.6, label=bench_label)
                add_ref_line(ax, 1.0)
                style_axes(ax, title=chart_title(stock, "relative_return"), ylabel="归一化净值", date_index=merged["date"])
                style_legend(ax)
                path = output_dir / "relative_return.png"
                save_chart(fig, path)
                close_figure(fig)
                charts["relative_return"] = str(path)

    if not turnover.empty:
        turnover["date"] = pd.to_datetime(turnover["date"])
        for col in ("today", "week", "month", "year", "current_year"):
            if col in turnover.columns:
                turnover[col] = pd.to_numeric(turnover[col], errors="coerce")
        fig, ax = new_figure()
        plot_line(ax, turnover["date"], turnover["today"], color=PALETTE["secondary"], linewidth=1.8, label=label("today"))
        if "month" in turnover.columns:
            plot_line(ax, turnover["date"], turnover["month"], color=PALETTE["accent"], linewidth=1.5, alpha=0.9, label=label("month"))
        style_axes(ax, title=chart_title(stock, "turnover_rate"), ylabel="换手率", date_index=turnover["date"])
        style_legend(ax)
        path = output_dir / "turnover_rate.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["turnover_rate"] = str(path)

    if not capital.empty:
        capital["date"] = pd.to_datetime(capital["date"])
        for col in ("buy_volume", "buy_value", "sell_volume", "sell_value"):
            if col in capital.columns:
                capital[col] = pd.to_numeric(capital[col], errors="coerce")
        capital["net_value"] = capital["buy_value"] - capital["sell_value"]
        capital["cum_net_value"] = capital["net_value"].cumsum()

        fig, ax = new_figure()
        colors = [PALETTE["up"] if v >= 0 else PALETTE["down"] for v in capital["net_value"]]
        bar_on_dates(ax, capital["date"], capital["net_value"], color=colors, alpha=0.82, width=0.82)
        add_zero_line(ax)
        style_axes(ax, title=chart_title(stock, "capital_flow"), ylabel=label("net_value"), date_index=capital["date"])
        path = output_dir / "capital_flow.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["capital_flow"] = str(path)

        fig, ax = new_figure()
        plot_line(ax, capital["date"], capital["cum_net_value"], color=PALETTE["purple"], linewidth=2)
        add_zero_line(ax)
        style_axes(ax, title=chart_title(stock, "cumulative_capital_flow"), ylabel=label("cum_net_value"), date_index=capital["date"])
        path = output_dir / "cumulative_capital_flow.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["cumulative_capital_flow"] = str(path)

        fig, ax = new_figure()
        plot_line(ax, capital["date"], capital["buy_value"], color=PALETTE["up"], linewidth=1.6, label=label("buy_value"))
        plot_line(ax, capital["date"], capital["sell_value"], color=PALETTE["down"], linewidth=1.6, label=label("sell_value"))
        style_axes(ax, title=chart_title(stock, "buy_sell_value"), ylabel="金额", date_index=capital["date"])
        style_legend(ax)
        path = output_dir / "buy_sell_value.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["buy_sell_value"] = str(path)

    if not factor_history.empty:
        factor_history["date"] = pd.to_datetime(factor_history["date"])
        for col in factor_history.columns:
            if col not in ("date", "order_book_id"):
                factor_history[col] = pd.to_numeric(factor_history[col], errors="coerce")
        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm")):
            if col in factor_history.columns and factor_history[col].notna().any():
                plot_line(
                    ax,
                    factor_history["date"],
                    factor_history[col],
                    color=SERIES_COLORS[idx % len(SERIES_COLORS)],
                    linewidth=1.7,
                    label=label(col),
                )
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "valuation_factors"), ylabel="倍数", date_index=factor_history["date"])
            style_legend(ax, ncol=3)
            path = output_dir / "valuation_factors.png"
            save_chart(fig, path)
            charts["valuation_factors"] = str(path)
        close_figure(fig)

        window = min(252, len(factor_history))
        for col in ("pe_ratio_ttm", "pb_ratio_ttm"):
            if col in factor_history.columns:
                factor_history[f"{col}_pct"] = factor_history[col].rolling(window).apply(
                    lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() != x.min() else 0.5,
                    raw=False,
                )
        if "pe_ratio_ttm" in factor_history.columns and factor_history["pe_ratio_ttm"].notna().any():
            fig, ax1 = new_figure()
            plot_line(
                ax1,
                factor_history["date"],
                factor_history["pe_ratio_ttm"],
                color=PALETTE["secondary"],
                linewidth=1.8,
                label=label("pe_ratio_ttm"),
            )
            if "pb_ratio_ttm" in factor_history.columns and factor_history["pb_ratio_ttm"].notna().any():
                ax2 = ax1.twinx()
                plot_line(
                    ax2,
                    factor_history["date"],
                    factor_history["pb_ratio_ttm"],
                    color=PALETTE["accent"],
                    linewidth=1.8,
                    label=label("pb_ratio_ttm"),
                )
                style_twin_axes(ax2)
                ax2.set_ylabel(label("pb_ratio_ttm"), color="#475569", fontsize=9)
                style_legend(ax2, loc="upper right")
            if "pe_ratio_ttm_pct" in factor_history.columns and not factor_history["pe_ratio_ttm_pct"].isna().all():
                last_pct = float(factor_history["pe_ratio_ttm_pct"].iloc[-1])
                ax1.annotate(
                    f"PE 分位 {last_pct:.0%}",
                    xy=(len(factor_history) - 1, factor_history["pe_ratio_ttm"].iloc[-1]),
                    xytext=(8, 8),
                    textcoords="offset points",
                    fontsize=8,
                    color=PALETTE["secondary"],
                )
            style_axes(
                ax1,
                title=chart_title(stock, "valuation_percentile", extra=f"rolling {window}d"),
                ylabel=label("pe_ratio_ttm"),
                date_index=factor_history["date"],
            )
            style_legend(ax1, loc="upper left")
            path = output_dir / "valuation_percentile.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["valuation_percentile"] = str(path)

        growth_cols = (
            "net_profit_growth_ratio_ttm",
            "operating_profit_growth_ratio_ttm",
            "gross_profit_growth_ratio_ttm",
            "operating_revenue_growth_ratio_ttm",
        )
        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(growth_cols):
            if col in factor_history.columns and factor_history[col].notna().any():
                plot_line(
                    ax,
                    factor_history["date"],
                    factor_to_chart_scale(col, factor_history[col]),
                    color=SERIES_COLORS[idx % len(SERIES_COLORS)],
                    linewidth=1.7,
                    label=label(col),
                )
                plotted = True
        if plotted:
            add_zero_line(ax)
            style_axes(ax, title=chart_title(stock, "growth_factors"), ylabel="增长率 (%)", date_index=factor_history["date"])
            style_legend(ax, ncol=2)
            path = output_dir / "growth_factors.png"
            save_chart(fig, path)
            charts["growth_factors"] = str(path)
        close_figure(fig)

        profit_cols = ("gross_profit_margin_ttm", "net_profit_margin_ttm", "roe_ttm")
        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(profit_cols):
            if col in factor_history.columns and factor_history[col].notna().any():
                plot_line(
                    ax,
                    factor_history["date"],
                    factor_to_chart_scale(col, factor_history[col]),
                    color=SERIES_COLORS[idx % len(SERIES_COLORS)],
                    linewidth=1.7,
                    label=label(col),
                )
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "profitability_factors"), ylabel="比率 (%)", date_index=factor_history["date"])
            style_legend(ax, ncol=3)
            path = output_dir / "profitability_factors.png"
            save_chart(fig, path)
            charts["profitability_factors"] = str(path)
        close_figure(fig)

        liquidity_cols = ("current_ratio", "quick_ratio")
        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(liquidity_cols):
            if col in factor_history.columns and factor_history[col].notna().any():
                plot_line(
                    ax,
                    factor_history["date"],
                    factor_history[col],
                    color=SERIES_COLORS[idx % len(SERIES_COLORS)],
                    linewidth=1.7,
                    label=label(col),
                )
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "liquidity_factors"), ylabel="倍数", date_index=factor_history["date"])
            style_legend(ax, ncol=2)
            path = output_dir / "liquidity_factors.png"
            save_chart(fig, path)
            charts["liquidity_factors"] = str(path)
        close_figure(fig)

        if "debt_to_asset_ratio" in factor_history.columns and factor_history["debt_to_asset_ratio"].notna().any():
            fig, ax = new_figure()
            plot_line(
                ax,
                factor_history["date"],
                factor_history["debt_to_asset_ratio"],
                color=PALETTE["negative"],
                linewidth=1.8,
            )
            style_axes(
                ax,
                title=chart_title(stock, "debt_ratio_trend"),
                ylabel="资产负债率 (%)",
                date_index=factor_history["date"],
            )
            path = output_dir / "debt_ratio_trend.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["debt_ratio_trend"] = str(path)

        if "market_cap" in factor_history.columns and factor_history["market_cap"].notna().any():
            fig, ax = new_figure()
            plot_line(ax, factor_history["date"], factor_history["market_cap"], color=PALETTE["secondary"], linewidth=1.8)
            style_axes(ax, title=chart_title(stock, "market_cap_trend"), ylabel=label("market_cap"), date_index=factor_history["date"])
            path = output_dir / "market_cap_trend.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["market_cap_trend"] = str(path)

    if not block_trade.empty and "date" in block_trade.columns:
        block_trade["date"] = pd.to_datetime(block_trade["date"])
        amount_col = next(
            (col for col in ("total_turnover", "turnover", "value", "amount") if col in block_trade.columns),
            None,
        )
        if amount_col:
            block_trade[amount_col] = pd.to_numeric(block_trade[amount_col], errors="coerce")
            plot_block = block_trade.dropna(subset=[amount_col])
            if not plot_block.empty:
                fig, ax = new_figure()
                bar_on_dates(ax, plot_block["date"], plot_block[amount_col], color=PALETTE["accent"], alpha=0.82, width=0.75)
                style_axes(ax, title=chart_title(stock, "block_trade_activity"), ylabel="成交额", date_index=plot_block["date"])
                path = output_dir / "block_trade_activity.png"
                save_chart(fig, path)
                close_figure(fig)
                charts["block_trade_activity"] = str(path)

    if not margin.empty and "date" in margin.columns:
        margin["date"] = pd.to_datetime(margin["date"])
        for col in ("margin_balance", "buy_on_margin_value", "short_balance", "total_balance", "margin_repayment"):
            if col in margin.columns:
                margin[col] = pd.to_numeric(margin[col], errors="coerce")

        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(("margin_balance", "short_balance", "total_balance")):
            if col in margin.columns and margin[col].notna().any():
                plot_line(ax, margin["date"], margin[col], color=SERIES_COLORS[idx], linewidth=1.7, label=label(col))
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "margin_balances"), ylabel="余额", date_index=margin["date"])
            style_legend(ax, ncol=3)
            path = output_dir / "margin_balances.png"
            save_chart(fig, path)
            charts["margin_balances"] = str(path)
        close_figure(fig)

        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(("buy_on_margin_value", "margin_repayment")):
            if col in margin.columns and margin[col].notna().any():
                plot_line(ax, margin["date"], margin[col], color=SERIES_COLORS[idx + 1], linewidth=1.7, label=label(col))
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "margin_activity"), ylabel="金额", date_index=margin["date"])
            style_legend(ax, ncol=2)
            path = output_dir / "margin_activity.png"
            save_chart(fig, path)
            charts["margin_activity"] = str(path)
        close_figure(fig)

        if "margin_balance" in margin.columns and margin["margin_balance"].notna().any():
            fig, ax1 = new_figure()
            plot_line(
                ax1,
                margin["date"],
                margin["margin_balance"],
                color=PALETTE["secondary"],
                linewidth=1.8,
                label=label("margin_balance"),
            )
            ax2 = ax1.twinx()
            x_idx, dt_idx = prepare_date_index(margin["date"])
            if "buy_on_margin_value" in margin.columns and margin["buy_on_margin_value"].notna().any():
                ax2.bar(
                    x_idx,
                    margin["buy_on_margin_value"],
                    alpha=0.45,
                    width=0.75,
                    color=PALETTE["positive"],
                    label=label("buy_on_margin_value"),
                    zorder=2,
                )
            if "margin_repayment" in margin.columns and margin["margin_repayment"].notna().any():
                ax2.bar(
                    x_idx,
                    -margin["margin_repayment"],
                    alpha=0.45,
                    width=0.75,
                    color=PALETTE["negative"],
                    label=label("margin_repayment"),
                    zorder=2,
                )
            style_axes(ax1, title=chart_title(stock, "margin_enhanced"), ylabel=label("margin_balance"), date_index=margin["date"])
            ax2.set_ylabel("日度流向", color="#94A3B8", fontsize=9)
            style_twin_axes(ax2)
            style_legend(ax1, loc="upper left")
            style_legend(ax2, loc="upper right", ncol=2)
            path = output_dir / "margin_enhanced.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["margin_enhanced"] = str(path)

    if not shares.empty and "date" in shares.columns:
        shares["date"] = pd.to_datetime(shares["date"])
        for col in ("total", "circulation_a", "free_circulation"):
            if col in shares.columns:
                shares[col] = pd.to_numeric(shares[col], errors="coerce")
        fig, ax = new_figure()
        plotted = False
        for idx, col in enumerate(("total", "circulation_a", "free_circulation")):
            if col in shares.columns and shares[col].notna().any():
                plot_line(ax, shares["date"], shares[col], color=SERIES_COLORS[idx], linewidth=1.7, label=label(col))
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "share_structure"), ylabel="股本", date_index=shares["date"])
            style_legend(ax, ncol=3)
            path = output_dir / "share_structure.png"
            save_chart(fig, path)
            charts["share_structure"] = str(path)
        close_figure(fig)

        latest = shares.iloc[-1]
        total = safe_float(latest.get("total")) or 0
        circ_a = safe_float(latest.get("circulation_a")) or 0
        free_circ = safe_float(latest.get("free_circulation")) or 0
        non_free = max(circ_a - free_circ, 0) if circ_a and free_circ else 0
        other = max(total - circ_a, 0) if total else 0
        pie_labels = ["自由流通股本", "限售流通股", "其他"]
        pie_sizes = [free_circ, non_free, other]
        if total and any(size > 0 for size in pie_sizes):
            fig, ax = new_figure(figsize=(10.2, 4.8))
            ax.pie(
                pie_sizes,
                labels=pie_labels,
                autopct="%1.1f%%",
                startangle=90,
                colors=SERIES_COLORS[:3],
                wedgeprops={"linewidth": 0.6, "edgecolor": "#FFFFFF"},
                textprops={"color": PALETTE["text"], "fontsize": 9},
            )
            ax.set_title(chart_title(stock, "share_structure_pie"), loc="left", color=PALETTE["text"], fontsize=12.5, fontweight=600, pad=12)
            path = output_dir / "share_structure_pie.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["share_structure_pie"] = str(path)

    if not dividend.empty:
        cash_col = "dividend_cash_before_tax"
        date_col = "declaration_announcement_date" if "declaration_announcement_date" in dividend.columns else "date"
        if cash_col in dividend.columns and date_col in dividend.columns:
            dividend[date_col] = pd.to_datetime(dividend[date_col])
            dividend[cash_col] = pd.to_numeric(dividend[cash_col], errors="coerce")
            plot_dividend = dividend.dropna(subset=[cash_col]).tail(12)
            if not plot_dividend.empty:
                labels = plot_dividend.get("quarter", plot_dividend[date_col].dt.date.astype(str)).astype(str)
                fig, ax = new_figure()
                ax.bar(labels, plot_dividend[cash_col], color=PALETTE["accent"], alpha=0.88, width=0.68, zorder=2)
                style_axes(ax, title=chart_title(stock, "dividend_history"), ylabel="每股税前分红（10派）")
                ax.tick_params(axis="x", rotation=20, labelsize=8)
                path = output_dir / "dividend_history.png"
                save_chart(fig, path)
                close_figure(fig)
                charts["dividend_history"] = str(path)

    if factor_latest and not yield_curve.empty and "dividend_yield_ttm" in factor_latest:
        dividend_raw = safe_float(factor_latest.get("dividend_yield_ttm"))
        if dividend_raw is not None:
            yield_curve["date"] = pd.to_datetime(yield_curve["date"])
            for col in yield_curve.columns:
                if col != "date":
                    yield_curve[col] = pd.to_numeric(yield_curve[col], errors="coerce")
            yc_1y = yield_curve.dropna(subset=["1Y"]).tail(1) if "1Y" in yield_curve.columns else pd.DataFrame()
            if not yc_1y.empty:
                dividend_pct = to_percent_points(dividend_raw)
                risk_free_pct = to_percent_points(float(yc_1y["1Y"].iloc[0]))
                if dividend_pct is not None and risk_free_pct is not None:
                    spread_pct = dividend_pct - risk_free_pct
                    fig, ax = new_figure(figsize=(10.2, 4.6))
                    categories = ["股息率(TTM)", "1Y国债收益率", "利差"]
                    values = [dividend_pct, risk_free_pct, spread_pct]
                    colors = [PALETTE["positive"], PALETTE["accent"], PALETTE["secondary"]]
                    if spread_pct < 0:
                        colors[2] = PALETTE["negative"]
                    plot_category_bars(ax, categories, values, colors=colors)
                    add_zero_line(ax)
                    style_axes(ax, title=chart_title(stock, "dividend_spread"), ylabel="收益率 (%)")
                    path = output_dir / "dividend_spread.png"
                    save_chart(fig, path)
                    close_figure(fig)
                    charts["dividend_spread"] = str(path)

    if not interbank_rate.empty and "date" in interbank_rate.columns:
        interbank_rate["date"] = pd.to_datetime(interbank_rate["date"])
        for col in ("ON", "1W", "1M", "3M", "1Y"):
            if col in interbank_rate.columns:
                interbank_rate[col] = pd.to_numeric(interbank_rate[col], errors="coerce")
        fig, ax = new_figure()
        plotted = False
        shibor_labels = {"ON": "隔夜", "1W": "1周", "1M": "1月", "3M": "3月", "1Y": "1年"}
        for idx, col in enumerate(("ON", "1M", "3M", "1Y")):
            if col in interbank_rate.columns and interbank_rate[col].notna().any():
                plot_line(
                    ax,
                    interbank_rate["date"],
                    interbank_rate[col],
                    color=SERIES_COLORS[idx],
                    linewidth=1.7,
                    label=f"Shibor {shibor_labels.get(col, col)}",
                )
                plotted = True
        if plotted:
            style_axes(ax, title=chart_title(stock, "shibor_rates"), ylabel="利率 (%)", date_index=interbank_rate["date"])
            style_legend(ax, ncol=4)
            path = output_dir / "shibor_rates.png"
            save_chart(fig, path)
            charts["shibor_rates"] = str(path)
        close_figure(fig)

    if not yield_curve.empty and "date" in yield_curve.columns:
        yield_curve["date"] = pd.to_datetime(yield_curve["date"])
        tenor_cols = [col for col in ("1Y", "3Y", "5Y", "10Y", "30Y") if col in yield_curve.columns]
        for col in tenor_cols:
            yield_curve[col] = pd.to_numeric(yield_curve[col], errors="coerce")

        trend_cols = [col for col in ("1Y", "10Y", "30Y") if col in yield_curve.columns]
        plot_trend = yield_curve.dropna(subset=trend_cols, how="all")
        if len(plot_trend) >= 2:
            fig, ax = new_figure()
            plotted = False
            for idx, col in enumerate(trend_cols):
                series = plot_trend[col].map(lambda v: to_percent_points(v) if pd.notna(v) else None)
                if series.notna().sum() >= 2:
                    plot_line(
                        ax,
                        plot_trend["date"],
                        series,
                        color=SERIES_COLORS[idx % len(SERIES_COLORS)],
                        linewidth=1.8,
                        label=f"{col} 国债",
                    )
                    plotted = True
            if plotted:
                style_axes(
                    ax,
                    title=chart_title(stock, "gov_yield_trend"),
                    ylabel="收益率 (%)",
                    date_index=plot_trend["date"],
                )
                style_legend(ax, ncol=3)
                path = output_dir / "gov_yield_trend.png"
                save_chart(fig, path)
                close_figure(fig)
                charts["gov_yield_trend"] = str(path)

        latest_curve = yield_curve.dropna(subset=tenor_cols, how="all").tail(1)
        if tenor_cols and not latest_curve.empty:
            snap_date = latest_curve["date"].dt.date.iloc[0]
            fig, ax = new_figure()
            values = [latest_curve[col].iloc[0] for col in tenor_cols]
            ax.plot(tenor_cols, values, color=PALETTE["secondary"], linewidth=2.2, marker="o", markersize=6, zorder=3)
            style_axes(
                ax,
                title=chart_title(stock, "yield_curve_snapshot", extra=str(snap_date)),
                xlabel="期限",
                ylabel="收益率 (%)",
            )
            path = output_dir / "yield_curve_snapshot.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["yield_curve_snapshot"] = str(path)

    if factor_latest:
        snapshot_specs = (
            ("latest_valuation_snapshot", ["market_cap", "pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "dividend_yield_ttm"]),
            ("latest_liquidity_snapshot", ["current_ratio", "quick_ratio", "debt_to_asset_ratio"]),
            (
                "latest_growth_snapshot",
                [
                    "net_profit_growth_ratio_ttm",
                    "operating_profit_growth_ratio_ttm",
                    "gross_profit_growth_ratio_ttm",
                    "operating_revenue_growth_ratio_ttm",
                ],
            ),
        )
        for name, keys in snapshot_specs:
            rows = [(key, snapshot_bar_value(key, safe_float(factor_latest.get(key)))) for key in keys]
            rows = [(key, value) for key, value in rows if value is not None]
            if not rows:
                continue
            labels_list = [label(key) for key, _ in rows]
            values = [value for _, value in rows]
            xlabel = "数值 (%)"
            if name == "latest_liquidity_snapshot":
                xlabel = "数值（比率/负债率 %）"
            elif name == "latest_valuation_snapshot":
                xlabel = "数值（量纲不一，仅作快照）"
            fig, ax = new_figure(figsize=(10.2, max(4.2, 0.45 * len(rows) + 2.2)))
            y_pos = range(len(rows))
            ax.barh(y_pos, values, color=PALETTE["secondary"], alpha=0.88, height=0.58, zorder=2)
            ax.set_yticks(list(y_pos))
            ax.set_yticklabels(labels_list)
            style_axes(ax, title=chart_title(stock, name), xlabel=xlabel)
            ax.invert_yaxis()
            path = output_dir / f"{name}.png"
            save_chart(fig, path)
            close_figure(fig)
            charts[name] = str(path)

    # ── 年报财务图表（来自 annual_analysis / workflow 格式财务数据） ──
    annual_analysis = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
    pit_fin = annual_analysis.get("financial_data") if isinstance(annual_analysis.get("financial_data"), list) else []
    if pit_fin:
        info(f"年报财务数据: {len(pit_fin)} 年, 生成年报财务图表")
        charts.update(_plot_annual_financial_charts(pit_fin, output_dir, stock))

    # ── 图表元数据（供 placement 智能体使用） ──
    data["_chart_metadata"] = _build_chart_metadata(data, charts)

    if only_keys:
        charts = {name: path for name, path in charts.items() if name in only_keys}
    info(f"图表生成完成: {len(charts)} 张 ({', '.join(charts.keys())})")
    return charts


def _plot_industry_comparison_charts(industry_comparison: Any, output_dir: Path, stock: str) -> dict[str, str]:
    if not isinstance(industry_comparison, dict):
        return {}
    metrics = industry_comparison.get("metrics") if isinstance(industry_comparison.get("metrics"), dict) else {}
    if not metrics:
        return {}
    charts: dict[str, str] = {}
    groups = {
        "industry_valuation_compare": ["pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"],
        "industry_profitability_compare": ["gross_profit_margin_ttm", "net_profit_margin_ttm", "roe_ttm"],
        "industry_growth_leverage_compare": [
            "operating_revenue_growth_ratio_ttm",
            "net_profit_parent_company_growth_ratio_ttm",
            "debt_to_asset_ratio",
            "current_ratio",
        ],
    }
    for name, keys in groups.items():
        rows = _industry_compare_rows(metrics, keys)
        if not rows:
            continue
        fig, ax = new_figure()
        labels_list = [row["label"] for row in rows]
        y = list(range(len(rows)))
        height = 0.24
        ax.barh([item - height for item in y], [row["target"] for row in rows], height=height, color=PALETTE["negative"], alpha=0.78, label="目标公司")
        ax.barh(y, [row["median"] for row in rows], height=height, color=PALETTE["secondary"], alpha=0.72, label="行业中位数")
        ax.barh([item + height for item in y], [row["mean"] for row in rows], height=height, color=PALETTE["accent"], alpha=0.72, label="行业均值")
        ax.set_yticks(y)
        ax.set_yticklabels(labels_list)
        ax.invert_yaxis()
        style_axes(ax, title=chart_title(stock, name), xlabel="指标值（百分比指标已换算为 %）")
        style_legend(ax, loc="lower right")
        path = output_dir / f"{name}.png"
        save_chart(fig, path)
        close_figure(fig)
        charts[name] = str(path)

    cluster = industry_comparison.get("cluster_anomalies")
    if isinstance(cluster, dict) and cluster.get("status") == "ok":
        points = cluster.get("points") if isinstance(cluster.get("points"), list) else []
        plot_features = cluster.get("plot_features") if isinstance(cluster.get("plot_features"), list) else []
        if points and len(plot_features) >= 2:
            fig, ax = new_figure()
            peer_points = [point for point in points if not point.get("is_target")]
            normal = [point for point in peer_points if not point.get("is_noise")]
            noise = [point for point in peer_points if point.get("is_noise")]
            target_points = [point for point in points if point.get("is_target")]
            if normal:
                ax.scatter([p["x"] for p in normal], [p["y"] for p in normal], s=26, color=PALETTE["secondary"], alpha=0.52, label="同行样本")
            if noise:
                ax.scatter([p["x"] for p in noise], [p["y"] for p in noise], s=34, color=PALETTE["muted"], alpha=0.72, marker="x", label="噪声点")
            if target_points:
                ax.scatter([p["x"] for p in target_points], [p["y"] for p in target_points], s=86, color=PALETTE["negative"], edgecolors=PALETTE["text"], linewidths=0.8, label="目标公司")
            ax.axhline(0, color=PALETTE["grid"], linewidth=0.9, zorder=1)
            ax.axvline(0, color=PALETTE["grid"], linewidth=0.9, zorder=1)
            x_label = FACTOR_LABELS.get(str(plot_features[0]), str(plot_features[0]))
            y_label = FACTOR_LABELS.get(str(plot_features[1]), str(plot_features[1]))
            style_axes(ax, title=chart_title(stock, "industry_dbscan_anomaly"), xlabel=f"{x_label} robust z", ylabel=f"{y_label} robust z")
            style_legend(ax, loc="best")
            path = output_dir / "industry_dbscan_anomaly.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["industry_dbscan_anomaly"] = str(path)
    return charts


def _industry_compare_rows(metrics: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        target = _scaled_metric_value(key, item.get("target"))
        median = _scaled_metric_value(key, item.get("median"))
        mean = _scaled_metric_value(key, item.get("mean"))
        if target is None or median is None or mean is None:
            continue
        rows.append(
            {
                "label": str(item.get("label") or FACTOR_LABELS.get(key, key)),
                "target": target,
                "median": median,
                "mean": mean,
            }
        )
    return rows


def _scaled_metric_value(key: str, value: Any) -> float | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    scaled = snapshot_bar_value(key, parsed)
    return None if scaled is None else float(scaled)


# ── 图表元数据生成（供 placement 智能体使用） ──


def _build_chart_metadata(data: dict[str, Any], charts: dict[str, str]) -> dict[str, Any]:
    """为生成的每张图构建结构化元数据：标题、关键词、数据摘要。

    Returns:
        chart_name → {"caption": str, "hints": tuple[str,...], "data_summary": str}
    """
    from .chart_catalog import CHART_CAPTIONS, CHART_SUBHEADING_HINTS
    from .technical import safe_float

    metadata: dict[str, Any] = {}
    if not charts:
        return metadata

    # 预读公共数据源
    fh = pd.DataFrame(data.get("factor_history", {}).get("rows", []))
    if not fh.empty:
        fh["date"] = pd.to_datetime(fh["date"], errors="coerce")
        for col in fh.columns:
            if col not in ("date", "order_book_id"):
                fh[col] = pd.to_numeric(fh[col], errors="coerce")

    price = pd.DataFrame(data.get("price", {}).get("rows", []))
    if not price.empty:
        price = __enrich_price(price)

    # 年报财务数据（workflow 格式）
    annual = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
    pit_fin: list[dict[str, Any]] = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []

    ic = data.get("industry_comparison") if isinstance(data.get("industry_comparison"), dict) else {}
    ic_metrics = ic.get("metrics") if isinstance(ic.get("metrics"), dict) else {}

    for chart_name in charts:
        caption = CHART_CAPTIONS.get(chart_name, chart_name)
        hints = CHART_SUBHEADING_HINTS.get(chart_name, ())
        summary = _chart_metadata_summary(chart_name, fh, price, pit_fin, ic_metrics)
        metadata[chart_name] = {
            "name": chart_name,
            "caption": caption,
            "hints": hints,
            "data_summary": summary,
        }
    return metadata


def _chart_metadata_summary(
    chart_name: str,
    fh: pd.DataFrame,
    price: pd.DataFrame,
    pit_fin: list[dict[str, Any]],
    ic_metrics: dict[str, Any],
) -> str:
    """为单张图生成文本数据摘要，供placement agent写桥接句时引用。"""
    from .technical import safe_float

    # ── 因子历史图 ──
    factor_cols = {
        "profitability_factors": ("gross_profit_margin_ttm", "net_profit_margin_ttm", "roe_ttm"),
        "growth_factors": (
            "net_profit_growth_ratio_ttm", "operating_revenue_growth_ratio_ttm",
            "gross_profit_growth_ratio_ttm", "operating_profit_growth_ratio_ttm",
        ),
        "liquidity_factors": ("current_ratio", "quick_ratio"),
        "debt_ratio_trend": ("debt_to_asset_ratio",),
        "valuation_factors": ("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"),
        "market_cap_trend": ("market_cap",),
    }
    if chart_name in factor_cols and not fh.empty:
        cols = factor_cols[chart_name]
        parts: list[str] = []
        for col in cols:
            if col in fh.columns and fh[col].notna().any():
                vals = fh[col].dropna()
                first = float(vals.iloc[0])
                last = float(vals.iloc[-1])
                delta = (last - first) / abs(first) if first != 0 else 0.0
                trend = "上升" if delta > 0.05 else ("下降" if delta < -0.05 else "平稳")
                parts.append(f"{col}: 期末{last:.2f}, 趋势{trend}")
        if parts:
            return "; ".join(parts)

    # ── 行业对比图 ──
    ic_charts = {
        "industry_profitability_compare": ("gross_profit_margin_ttm", "net_profit_margin_ttm", "roe_ttm"),
        "industry_growth_leverage_compare": (
            "operating_revenue_growth_ratio_ttm", "net_profit_parent_company_growth_ratio_ttm",
            "debt_to_asset_ratio", "current_ratio",
        ),
        "industry_valuation_compare": ("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"),
        "industry_dbscan_anomaly": None,
    }
    if chart_name in ic_charts and ic_metrics:
        if chart_name == "industry_dbscan_anomaly":
            return "DBSCAN 聚类散点图: 目标公司相对同行在横截面因子上的异常位置识别"
        keys = ic_charts[chart_name]
        parts = []
        for key in keys:
            item = ic_metrics.get(key)
            if isinstance(item, dict):
                t = safe_float(item.get("target"))
                m = safe_float(item.get("median"))
                label = item.get("label", key)
                if t is not None and m is not None:
                    parts.append(f"{label}: 目标{t:.2f}, 行业中位数{m:.2f}")
        if parts:
            return "; ".join(parts)

    # ── 年报财务图 ──
    annual_charts = {
        "revenue_profit_trend": ["revenue", "net_profit_parent_company"],
        "profit_vs_cashflow": ["net_profit_parent_company", "cash_flow_from_operating_activities"],
        "free_cashflow_trend": ["free_cash_flow"],
        "margin_roe_trend": ["gross_margin", "roe"],
    }
    if chart_name in annual_charts and pit_fin:
        fields = annual_charts[chart_name]
        parts = []
        for fld in fields:
            vals: list[tuple[int, float]] = []
            for row in pit_fin:
                fi = row.get("fields") if isinstance(row.get("fields"), dict) else {}
                info = fi.get(fld)
                if isinstance(info, dict):
                    v = safe_float(info.get("value"))
                    if v is not None:
                        vals.append((row.get("year"), v))
            if vals:
                years_str = "→".join(str(y) for y, _ in vals)
                # 金额用亿元，比率用百分比
                if fld in ("gross_margin", "roe"):
                    vals_str = "→".join(f"{v*100:.1f}%" for _, v in vals)
                else:
                    vals_str = "→".join(_format_amount(v) for _, v in vals)
                parts.append(f"{fld}({vals_str}, {years_str})")
        if parts:
            return "; ".join(parts)

    # ── 量价图 ──
    if not price.empty:
        price_charts = {
            "price_volume": ("close", "volume"),
            "moving_averages": ("close", "ma20", "ma60"),
            "nav_curve": ("close",),
            "cumulative_return": ("cum_return",),
            "drawdown": ("drawdown",),
            "technical_indicators": ("rsi14", "macd", "macd_signal"),
        }
        if chart_name in price_charts:
            cols = price_charts[chart_name]
            parts = []
            for col in cols:
                if col in price.columns and price[col].notna().any():
                    vals = price[col].dropna()
                    last = float(vals.iloc[-1])
                    first = float(vals.iloc[0]) if vals.iloc[0] != 0 else None
                    label = col
                    if first:
                        delta = (last - first) / abs(first)
                        trend = "上升" if delta > 0.03 else ("下降" if delta < -0.03 else "平稳")
                        parts.append(f"{label}: 末值{last:.2f}, 趋势{trend}")
                    else:
                        parts.append(f"{label}: 末值{last:.2f}")
            if parts:
                return "; ".join(parts)

    return ""


def __enrich_price(price: pd.DataFrame) -> pd.DataFrame:
    """轻量 enrich：加 ma20/ma60/drawdown 等（避免全量 technical 计算）。"""
    from .technical import enrich_price_frame
    try:
        return enrich_price_frame(price)
    except Exception:
        return price


# ── 年报财务图表辅助函数 ──


def _extract_annual_metric(
    financial_data: list[dict[str, Any]], field_name: str
) -> tuple[list[int], list[float]]:
    """从 workflow 格式 financial_data 提取逐年 (years, values)。

    workflow 格式: ``[{"year": 2024, "fields": {"revenue": {"value": 1200, ...}}}]``
    """
    years: list[int] = []
    values: list[float] = []
    for row in financial_data:
        year = row.get("year")
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        info = fields.get(field_name)
        if isinstance(info, dict) and info.get("value") is not None:
            try:
                years.append(int(year))
                values.append(float(info["value"]))
            except (TypeError, ValueError):
                continue
    return years, values


def _format_amount(value: float) -> str:
    """将数值格式化为亿元或万元。"""
    abs_v = abs(value)
    if abs_v >= 1e8:
        return f"{value / 1e8:.2f} 亿"
    elif abs_v >= 1e4:
        return f"{value / 1e4:.2f} 万"
    else:
        return f"{value:.2f}"


def _plot_annual_financial_charts(
    financial_data: list[dict[str, Any]], output_dir: Path, stock: str
) -> dict[str, str]:
    """基于 workflow 格式年报财务数据生成 4 张图表。"""
    charts: dict[str, str] = {}

    # 1. 营收 / 净利润多年趋势对比（双轴）
    rev_years, rev_values = _extract_annual_metric(financial_data, "revenue")
    np_years, np_values = _extract_annual_metric(financial_data, "net_profit_parent_company")
    if rev_years and np_years:
        fig, ax1 = new_figure()
        bar_on_dates(ax1, rev_years, rev_values, color=PALETTE["secondary"], alpha=0.55, width=0.55)
        ax1.set_ylabel("营收（元）", color=PALETTE["secondary"], fontsize=9)
        ax1.tick_params(axis="y", labelcolor=PALETTE["secondary"])
        ax2 = ax1.twinx()
        plot_line(ax2, np_years, np_values, color=PALETTE["accent"], linewidth=2.2, marker="o", markersize=6)
        ax2.set_ylabel("归母净利润（元）", color=PALETTE["accent"], fontsize=9)
        ax2.tick_params(axis="y", labelcolor=PALETTE["accent"])
        style_axes(ax1, title=chart_title(stock, "revenue_profit_trend"), xlabel="年份")
        ax1.set_xticks(rev_years)
        ax1.set_xticklabels([str(y) for y in rev_years])
        path = output_dir / "revenue_profit_trend.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["revenue_profit_trend"] = str(path)

    # 2. 净利润 vs 经营现金流对比
    _, np_vals = _extract_annual_metric(financial_data, "net_profit_parent_company")
    ocf_years, ocf_vals = _extract_annual_metric(financial_data, "cash_flow_from_operating_activities")
    if np_vals and ocf_years:
        fig, ax = new_figure()
        years_shared = sorted(set(np_years) & set(ocf_years))
        np_plot = [np_vals[np_years.index(y)] for y in years_shared if y in np_years]
        ocf_plot = [ocf_vals[ocf_years.index(y)] for y in years_shared if y in ocf_years]
        if len(years_shared) == len(np_plot) == len(ocf_plot):
            bar_on_dates(ax, years_shared, np_plot, color=PALETTE["secondary"], alpha=0.55, width=0.45, label="归母净利润")
            bar_on_dates(ax, [y + 0.18 for y in years_shared], ocf_plot, color=PALETTE["accent"], alpha=0.55, width=0.45, label="经营现金流")
            style_axes(ax, title=chart_title(stock, "profit_vs_cashflow"), xlabel="年份", ylabel="金额（元）")
            ax.set_xticks(years_shared)
            ax.set_xticklabels([str(y) for y in years_shared])
            style_legend(ax, loc="upper left", ncol=2)
            path = output_dir / "profit_vs_cashflow.png"
            save_chart(fig, path)
            close_figure(fig)
            charts["profit_vs_cashflow"] = str(path)

    # 3. 自由现金流趋势
    fcf_years, fcf_vals = _extract_annual_metric(financial_data, "free_cash_flow")
    if fcf_years:
        fig, ax = new_figure()
        colors_fcf = [PALETTE["positive"] if v >= 0 else PALETTE["negative"] for v in fcf_vals]
        bar_on_dates(ax, fcf_years, fcf_vals, color=colors_fcf, alpha=0.78, width=0.58)
        add_zero_line(ax)
        style_axes(ax, title=chart_title(stock, "free_cashflow_trend"), xlabel="年份", ylabel="自由现金流（元）")
        ax.set_xticks(fcf_years)
        ax.set_xticklabels([str(y) for y in fcf_years])
        path = output_dir / "free_cashflow_trend.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["free_cashflow_trend"] = str(path)

    # 4. 毛利率 / ROE 多年趋势（双轴）
    gm_years, gm_vals = _extract_annual_metric(financial_data, "gross_margin")
    roe_years, roe_vals = _extract_annual_metric(financial_data, "roe")
    if gm_years or roe_years:
        fig, ax1 = new_figure()
        if gm_years:
            gm_pct = [v * 100 for v in gm_vals]  # 小数 → 百分比
            plot_line(ax1, gm_years, gm_pct, color=PALETTE["secondary"], linewidth=2.0, marker="s", markersize=5, label="毛利率 (%)")
        ax1.set_ylabel("毛利率 (%)", color=PALETTE["secondary"], fontsize=9)
        ax1.tick_params(axis="y", labelcolor=PALETTE["secondary"])
        if roe_years:
            ax2 = ax1.twinx()
            roe_pct = [v * 100 for v in roe_vals]
            plot_line(ax2, roe_years, roe_pct, color=PALETTE["accent"], linewidth=2.0, marker="o", markersize=5, label="ROE (%)")
            ax2.set_ylabel("ROE (%)", color=PALETTE["accent"], fontsize=9)
            ax2.tick_params(axis="y", labelcolor=PALETTE["accent"])
        all_years = sorted(set(gm_years + roe_years))
        style_axes(ax1, title=chart_title(stock, "margin_roe_trend"), xlabel="年份")
        ax1.set_xticks(all_years)
        ax1.set_xticklabels([str(y) for y in all_years])
        lines1, labels1 = ax1.get_legend_handles_labels()
        if roe_years:
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8, ncol=2)
        else:
            style_legend(ax1, loc="upper left")
        path = output_dir / "margin_roe_trend.png"
        save_chart(fig, path)
        close_figure(fig)
        charts["margin_roe_trend"] = str(path)

    return charts
