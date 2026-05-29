from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .cninfo import default_as_of, normalize_stock_code, to_order_book_id
from .env import get_env, load_dotenv
from .llm import llm_json, llm_text
from .multi_report import (
    CHART_CAPTIONS,
    CHART_INTERPRETATION_SECTION,
    apply_chart_placements,
    build_chart_interpretation_section,
    build_default_chart_placement,
    build_multi_json_payload,
    fallback_chart_note,
    fill_missing_section_placements,
    normalize_chart_placement,
    normalize_section_text,
    render_multi_html,
    render_multi_markdown,
)
from .report_format import write_report
from .report_html import write_html_report
from .rqdata_client import _init_rqdata, fetch_financials


def _get_max_workers() -> int:
    try:
        return max(1, int(get_env("FINAGENT_MAX_WORKERS", "4")))
    except (TypeError, ValueError):
        return 4


TOOL_REGISTRY = {
    "get_price": "量价行情：open/high/low/close/volume/total_turnover",
    "get_price_change_rate": "日涨跌幅序列，用于收益率和波动分析",
    "get_turnover_rate": "换手率：today/week/month/year/current_year",
    "get_capital_flow": "资金流向：buy_volume/buy_value/sell_volume/sell_value",
    "get_factor": "估值、盈利、偿债、成长和分红因子：market_cap/pe/pb/ps/dividend_yield/margin/debt/liquidity/growth",
    "get_securities_margin": "融资融券：margin_balance/buy_on_margin_value/short_balance/total_balance",
    "get_dividend": "分红方案：现金分红、除权除息日、支付日、报告期",
    "get_shares": "股本结构：total/circulation_a/free_circulation 等",
    "get_instrument_industry": "中信一级行业归属，用于限定可比口径和行业背景",
    "is_suspended": "停牌状态检查",
    "is_st_stock": "ST 状态检查",
    "get_interbank_offered_rate": "Shibor 同业拆借利率，用作宏观流动性背景",
    "get_yield_curve": "中国收益率曲线，用作无风险利率和期限结构背景",
    "get_pit_financials_ex": "年报口径三表财务字段，复用 FinAgent 原有财务数据模块",
}

DEFAULT_SECTIONS = [
    {"name": "量价与趋势", "agent": "price_volume_writer", "data": ["get_price", "get_price_change_rate", "get_turnover_rate"]},
    {"name": "基本面与估值", "agent": "fundamental_writer", "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares"]},
    {"name": "资金与交易结构", "agent": "capital_flow_writer", "data": ["get_capital_flow", "get_securities_margin"]},
    {"name": "技术因素", "agent": "technical_writer", "data": ["get_price", "get_price_change_rate"]},
    {"name": "宏观利率背景", "agent": "macro_rate_writer", "data": ["get_interbank_offered_rate", "get_yield_curve"]},
    {"name": "图表解读", "agent": "chart_writer", "data": ["generated_charts"]},
    {"name": "综合风险与数据局限", "agent": "risk_synthesis_writer", "data": ["all_collected_data", "is_suspended", "is_st_stock"]},
]


FACTOR_CANDIDATES = [
    "market_cap",
    "pe_ratio_ttm",
    "pb_ratio_ttm",
    "ps_ratio_ttm",
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
    "dividend_yield_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "account_receivable_turnover_rate_ttm",
    "current_asset_turnover_ttm",
]

CHART_QUALITY_REQUIREMENTS = [
    "每张图必须回答一个明确问题，不能为了凑数量画单一常数或重复口径。",
    "同一信息只保留最有解释力的一张图，避免价格/收益/均线图之间无差别堆叠。",
    "不同量纲不要直接放在同一柱状图里比较；市值、PE、PB、股息率等需拆分或只写入正文。",
    "宏观利率图必须服务于估值折现率或流动性背景，不得泛泛而谈。",
    "分红、股本、两融等事件型或结构型数据若变化很少，优先在正文表述，图表可删除。",
]


@dataclass
class MultiAgentOptions:
    stock: str
    as_of: str | None = None
    lookback_days: int = 260
    output: str | None = None
    workdir: str = "."


def run_multi_agent(options: MultiAgentOptions) -> dict[str, Any]:
    load_dotenv()
    root = Path(options.workdir)
    output_path = Path(options.output) if options.output else root / "outputs" / f"{normalize_stock_code(options.stock)}_multi_agent_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    as_of_date = default_as_of(options.as_of)
    stock_code = normalize_stock_code(options.stock)
    order_book_id = to_order_book_id(stock_code)

    plan = planner_agent(stock_code=stock_code, order_book_id=order_book_id, as_of=as_of_date, lookback_days=options.lookback_days)
    data = data_executor_agent(
        order_book_id=order_book_id,
        stock_code=stock_code,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        output_dir=output_path.parent,
    )
    chart_output_dir = output_path.parent / "charts" / output_path.stem
    chart_files = chart_agent(data=data, output_dir=chart_output_dir)
    charts = {name: _markdown_path(path, output_path.parent) for name, path in chart_files.items()}
    sections = section_writer_agents(plan=plan, data=data, charts=charts)
    draft_summary = _local_executive_summary(plan=plan, data=data, sections=sections)
    draft_markdown = render_multi_markdown(
        summary=draft_summary, plan=plan, data=data, charts=charts, sections=sections, inline_charts=False
    )
    validation = validation_agent(plan=plan, data=data, charts=charts, sections=sections, draft_markdown=draft_markdown)
    data, charts, validation = refinement_loop(
        plan=plan,
        data=data,
        charts=charts,
        validation=validation,
        order_book_id=order_book_id,
        stock_code=stock_code,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        output_dir=output_path.parent,
        chart_output_dir=chart_output_dir,
    )
    refinement = validation.get("refinement_performed") if isinstance(validation.get("refinement_performed"), dict) else {}
    if refinement.get("refresh_data") or refinement.get("refresh_charts"):
        sections = section_writer_agents(plan=plan, data=data, charts=charts)
    if _should_revise(validation):
        sections = revise_sections_with_validation(plan=plan, data=data, charts=charts, sections=sections, validation=validation)
    else:
        sections = {name: normalize_section_text(content, name) for name, content in sections.items()}
    chart_placement = chart_placement_agent(
        plan=plan, data=data, charts=charts, sections=sections, validation=validation
    )
    figure_note_charts = _charts_needing_figure_notes(chart_placement, charts)
    figure_notes = chart_figure_notes_agent(data=data, charts=charts, chart_names=figure_note_charts)
    sections, unused_charts = apply_chart_placements(
        sections, charts, chart_placement, figure_notes=figure_notes, data=data
    )
    sections[CHART_INTERPRETATION_SECTION] = build_chart_interpretation_section(
        unused_charts, charts, figure_notes=figure_notes, data=data
    )
    summary = _executive_summary_agent(plan=plan, data=data, sections=sections, validation=validation)
    final_markdown = render_multi_markdown(
        summary=summary,
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        inline_charts=True,
        unused_charts=[],
        validation=validation,
    )
    html_path = output_path.with_suffix(".html")
    final_html = render_multi_html(
        summary=summary,
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        inline_charts=True,
        unused_charts=[],
        validation=validation,
    )

    json_path = output_path.with_suffix(".json")
    payload = build_multi_json_payload(
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        validation=validation,
        summary=summary,
        output_markdown=str(output_path),
        output_json=str(json_path),
        output_html=str(html_path),
        chart_placement=chart_placement,
        unused_charts=unused_charts,
        figure_notes=figure_notes,
    )
    write_report(final_markdown, output_path)
    write_html_report(final_html, html_path)
    json_path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_markdown"] = str(output_path)
    payload["output_json"] = str(json_path)
    payload["output_html"] = str(html_path)
    return payload


def planner_agent(*, stock_code: str, order_book_id: str, as_of: date, lookback_days: int) -> dict[str, Any]:
    """规则化计划：章节与工具固定，避免额外 LLM 调用。"""
    _ = (stock_code, order_book_id, as_of, lookback_days)
    return {
        "objective": "生成覆盖量价、基本面、资金流、技术因素的 A 股多智能体研究报告",
        "tools": list(TOOL_REGISTRY),
        "sections": DEFAULT_SECTIONS,
        "risk_controls": [
            "仅基于可取得数据写结论",
            "不输出买卖建议",
            "说明缺失数据",
            "只能引用本系统实际采集的米筐数据与本地计算指标",
            "不得声称使用 Wind、行业调研、宏观数据、新闻或预测模型",
        ],
    }


def _sanitize_plan(plan: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(plan) if isinstance(plan, dict) else {}
    result["tools"] = [name for name in result.get("tools", []) if name in TOOL_REGISTRY] or list(TOOL_REGISTRY)
    # Keep the LLM objective, but pin section execution to data we actually collect.
    result["sections"] = DEFAULT_SECTIONS
    controls = result.get("risk_controls") if isinstance(result.get("risk_controls"), list) else []
    result["risk_controls"] = [
        *[str(item) for item in controls if str(item).strip()],
        "只能引用本系统实际采集的米筐数据与本地计算指标",
        "不得声称使用 Wind、行业调研、宏观数据、新闻或预测模型",
    ]
    result["objective"] = str(result.get("objective") or fallback["objective"])
    return result


def data_executor_agent(
    *,
    order_book_id: str,
    stock_code: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
) -> dict[str, Any]:
    import rqdatac

    _init_rqdata(rqdatac)
    end_date = _previous_trading_date(rqdatac, as_of)
    start_date = end_date - timedelta(days=max(30, lookback_days))
    fundamentals_start = end_date - timedelta(days=730)
    macro_start = end_date - timedelta(days=120)
    available_factors = set(rqdatac.get_all_factor_names())
    factors = [name for name in FACTOR_CANDIDATES if name in available_factors]

    # 所有 rqdatac 拉取互相独立，均为 IO 密集型网络请求，可并发执行。
    tasks: dict[str, Any] = {
        "price": lambda: rqdatac.get_price(
            order_book_id,
            start_date=start_date,
            end_date=end_date,
            frequency="1d",
            fields=["open", "high", "low", "close", "volume", "total_turnover"],
        ),
        "turnover": lambda: rqdatac.get_turnover_rate(order_book_id, start_date=start_date, end_date=end_date),
        "capital": lambda: rqdatac.get_capital_flow(order_book_id, start_date=start_date, end_date=end_date),
        "price_change": lambda: rqdatac.get_price_change_rate(order_book_id, start_date=start_date, end_date=end_date),
        "margin": lambda: rqdatac.get_securities_margin(order_book_id, start_date=start_date, end_date=end_date),
        "dividend": lambda: rqdatac.get_dividend(order_book_id, start_date=fundamentals_start, end_date=end_date),
        "shares": lambda: rqdatac.get_shares(order_book_id, start_date=fundamentals_start, end_date=end_date),
        "suspended": lambda: rqdatac.is_suspended(order_book_id, start_date=start_date, end_date=end_date),
        "st_stock": lambda: rqdatac.is_st_stock(order_book_id, start_date=start_date, end_date=end_date),
        "industry": lambda: rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=1, date=end_date),
        "interbank_rate": lambda: rqdatac.get_interbank_offered_rate(start_date=macro_start, end_date=end_date),
        "yield_curve": lambda: rqdatac.get_yield_curve(start_date=macro_start, end_date=end_date),
        "factor": (lambda: rqdatac.get_factor(order_book_id, factors, start_date=end_date, end_date=end_date)) if factors else (lambda: pd.DataFrame()),
        "factor_history": (lambda: rqdatac.get_factor(order_book_id, factors, start_date=start_date, end_date=end_date)) if factors else (lambda: pd.DataFrame()),
    }
    with ThreadPoolExecutor(max_workers=_get_max_workers()) as executor:
        future_map = {key: executor.submit(_safe_rq_call, key, fn) for key, fn in tasks.items()}
        fetched = {key: future.result() for key, future in future_map.items()}

    report_year = end_date.year - 1
    try:
        fin_result = fetch_financials(stock_code, report_year=report_year, years=3)
        pit_financials = {
            "rows": _slim_pit_financials(fin_result.rows),
            "row_count": len(fin_result.rows),
            "quarters": fin_result.quarters,
        }
    except Exception as exc:
        pit_financials = {"rows": [], "row_count": 0, "error": f"{type(exc).__name__}: {exc}"}

    price = fetched["price"]
    turnover = fetched["turnover"]
    capital = fetched["capital"]
    price_change = fetched["price_change"]
    margin = fetched["margin"]
    dividend = fetched["dividend"]
    shares = fetched["shares"]
    suspended = fetched["suspended"]
    st_stock = fetched["st_stock"]
    industry = fetched["industry"]
    interbank_rate = fetched["interbank_rate"]
    yield_curve = fetched["yield_curve"]
    factor = fetched["factor"]
    factor_history = fetched["factor_history"]

    frames = {
        "price": _flatten_frame(price),
        "price_change_rate": _flatten_frame(price_change),
        "turnover": _flatten_frame(turnover),
        "capital_flow": _flatten_frame(capital),
        "securities_margin": _flatten_frame(margin),
        "dividend": _flatten_frame(dividend),
        "shares": _flatten_frame(shares),
        "suspended": _flatten_frame(suspended),
        "st_stock": _flatten_frame(st_stock),
        "industry": _flatten_frame(industry),
        "interbank_rate": _flatten_frame(interbank_rate),
        "yield_curve": _flatten_frame(yield_curve),
        "factor": _flatten_frame(factor),
        "factor_history": _flatten_frame(factor_history),
    }
    log_path = _write_data_log(
        output_dir, order_book_id, start_date, end_date, factors, frames, pit_row_count=pit_financials.get("row_count", 0)
    )
    return {
        "order_book_id": order_book_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "tool_registry": TOOL_REGISTRY,
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
        "data_log": str(log_path),
        "price": _frame_summary(frames["price"], tail=max(260, lookback_days)),
        "price_change_rate": _frame_summary(frames["price_change_rate"], tail=max(260, lookback_days)),
        "turnover": _frame_summary(frames["turnover"], tail=max(260, lookback_days)),
        "capital_flow": _capital_flow_summary(frames["capital_flow"]),
        "securities_margin": _frame_summary(frames["securities_margin"], tail=max(260, lookback_days)),
        "dividend": _frame_summary(frames["dividend"], tail=20),
        "shares": _frame_summary(frames["shares"], tail=260),
        "suspended": _frame_summary(frames["suspended"], tail=30),
        "st_stock": _frame_summary(frames["st_stock"], tail=30),
        "industry": _latest_row(frames["industry"]),
        "interbank_rate": _frame_summary(frames["interbank_rate"], tail=120),
        "yield_curve": _frame_summary(frames["yield_curve"], tail=120),
        "factor": _latest_row(frames["factor"]),
        "factor_history": _frame_summary(frames["factor_history"], tail=max(260, lookback_days)),
        "pit_financials": pit_financials,
        "technical": _technical_summary(frames["price"]),
    }


def chart_agent(*, data: dict[str, Any], output_dir: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    price = pd.DataFrame(data["price"]["rows"])
    turnover = pd.DataFrame(data["turnover"]["rows"])
    capital = pd.DataFrame(data["capital_flow"]["rows"])
    margin = pd.DataFrame(data.get("securities_margin", {}).get("rows", []))
    dividend = pd.DataFrame(data.get("dividend", {}).get("rows", []))
    shares = pd.DataFrame(data.get("shares", {}).get("rows", []))
    interbank_rate = pd.DataFrame(data.get("interbank_rate", {}).get("rows", []))
    yield_curve = pd.DataFrame(data.get("yield_curve", {}).get("rows", []))
    factor_history = pd.DataFrame(data.get("factor_history", {}).get("rows", []))
    factor_latest = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    charts: dict[str, str] = {}
    if not price.empty:
        price["date"] = pd.to_datetime(price["date"])
        for col in ("open", "high", "low", "close", "volume", "total_turnover"):
            if col in price.columns:
                price[col] = pd.to_numeric(price[col], errors="coerce")
        price["ma20"] = price["close"].rolling(20).mean()
        price["ma60"] = price["close"].rolling(60).mean()
        price["return"] = price["close"].pct_change()
        price["cum_return"] = (1 + price["return"].fillna(0)).cumprod() - 1
        price["drawdown"] = price["close"] / price["close"].cummax() - 1
        delta = price["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        price["rsi14"] = 100 - 100 / (1 + gain / loss)
        ema12 = price["close"].ewm(span=12, adjust=False).mean()
        ema26 = price["close"].ewm(span=26, adjust=False).mean()
        price["macd"] = ema12 - ema26
        price["macd_signal"] = price["macd"].ewm(span=9, adjust=False).mean()
        price["macd_hist"] = price["macd"] - price["macd_signal"]

        fig, ax1 = plt.subplots(figsize=(10, 4.8))
        ax1.plot(price["date"], price["close"], label="close", color="#2563eb")
        ax1.set_ylabel("close")
        ax2 = ax1.twinx()
        ax2.bar(price["date"], price["volume"], alpha=0.18, label="volume", color="#64748b")
        ax2.set_ylabel("volume")
        ax1.set_title(f"{data['order_book_id']} price and volume")
        fig.tight_layout()
        path = output_dir / "price_volume.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["price_volume"] = str(path)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(price["date"], price["close"], label="close", color="#111827")
        ax.plot(price["date"], price["ma20"], label="MA20", color="#2563eb")
        ax.plot(price["date"], price["ma60"], label="MA60", color="#dc2626")
        ax.set_title(f"{data['order_book_id']} close with moving averages")
        ax.legend()
        fig.tight_layout()
        path = output_dir / "moving_averages.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["moving_averages"] = str(path)

        base_close = price["close"].iloc[0]
        if base_close and pd.notna(base_close) and base_close != 0:
            price["nav"] = price["close"] / base_close
            fig, ax = plt.subplots(figsize=(10, 4.8))
            ax.plot(price["date"], price["nav"], color="#2563eb", linewidth=1.8)
            ax.axhline(1.0, color="#94a3b8", linewidth=1, linestyle="--")
            ax.set_title(f"{data['order_book_id']} NAV curve")
            ax.set_ylabel("NAV (base=1)")
            fig.tight_layout()
            path = output_dir / "nav_curve.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            charts["nav_curve"] = str(path)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(price["date"], price["cum_return"], color="#7c3aed")
        ax.axhline(0, color="#94a3b8", linewidth=1)
        ax.set_title(f"{data['order_book_id']} cumulative return")
        ax.set_ylabel("return")
        fig.tight_layout()
        path = output_dir / "cumulative_return.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["cumulative_return"] = str(path)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.fill_between(price["date"], price["drawdown"], 0, color="#ef4444", alpha=0.35)
        ax.set_title(f"{data['order_book_id']} drawdown")
        ax.set_ylabel("drawdown")
        fig.tight_layout()
        path = output_dir / "drawdown.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["drawdown"] = str(path)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True)
        ax1.plot(price["date"], price["rsi14"], color="#0891b2")
        ax1.axhline(70, color="#ef4444", linestyle="--", linewidth=1)
        ax1.axhline(30, color="#16a34a", linestyle="--", linewidth=1)
        ax1.set_title("RSI14")
        ax2.bar(price["date"], price["macd_hist"], color="#64748b", alpha=0.55)
        ax2.plot(price["date"], price["macd"], color="#2563eb", label="MACD")
        ax2.plot(price["date"], price["macd_signal"], color="#dc2626", label="signal")
        ax2.set_title("MACD")
        ax2.legend()
        fig.tight_layout()
        path = output_dir / "technical_indicators.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["technical_indicators"] = str(path)

    if not turnover.empty:
        turnover["date"] = pd.to_datetime(turnover["date"])
        for col in ("today", "week", "month", "year", "current_year"):
            if col in turnover.columns:
                turnover[col] = pd.to_numeric(turnover[col], errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(turnover["date"], turnover["today"], label="today", color="#2563eb")
        if "month" in turnover.columns:
            ax.plot(turnover["date"], turnover["month"], label="month avg", color="#dc2626", alpha=0.8)
        ax.set_title(f"{data['order_book_id']} turnover rate")
        ax.set_ylabel("turnover rate")
        ax.legend()
        fig.tight_layout()
        path = output_dir / "turnover_rate.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["turnover_rate"] = str(path)

    if not capital.empty:
        capital["date"] = pd.to_datetime(capital["date"])
        for col in ("buy_volume", "buy_value", "sell_volume", "sell_value"):
            if col in capital.columns:
                capital[col] = pd.to_numeric(capital[col], errors="coerce")
        capital["net_value"] = capital["buy_value"] - capital["sell_value"]
        capital["cum_net_value"] = capital["net_value"].cumsum()
        fig, ax = plt.subplots(figsize=(10, 4.8))
        colors = ["#dc2626" if v >= 0 else "#16a34a" for v in capital["net_value"]]
        ax.bar(capital["date"], capital["net_value"], color=colors, alpha=0.78)
        ax.set_title(f"{data['order_book_id']} net capital flow")
        ax.set_ylabel("buy_value - sell_value")
        fig.tight_layout()
        path = output_dir / "capital_flow.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["capital_flow"] = str(path)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(capital["date"], capital["cum_net_value"], color="#7c3aed")
        ax.axhline(0, color="#94a3b8", linewidth=1)
        ax.set_title(f"{data['order_book_id']} cumulative net capital flow")
        ax.set_ylabel("cumulative net value")
        fig.tight_layout()
        path = output_dir / "cumulative_capital_flow.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["cumulative_capital_flow"] = str(path)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(capital["date"], capital["buy_value"], label="buy_value", color="#dc2626")
        ax.plot(capital["date"], capital["sell_value"], label="sell_value", color="#16a34a")
        ax.set_title(f"{data['order_book_id']} buy vs sell value")
        ax.legend()
        fig.tight_layout()
        path = output_dir / "buy_sell_value.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        charts["buy_sell_value"] = str(path)

    if not factor_history.empty:
        factor_history["date"] = pd.to_datetime(factor_history["date"])
        for col in ("pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"):
            if col in factor_history.columns:
                factor_history[col] = pd.to_numeric(factor_history[col], errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        plotted = False
        for col, color in (("pe_ratio_ttm", "#2563eb"), ("pb_ratio_ttm", "#dc2626"), ("ps_ratio_ttm", "#7c3aed")):
            if col in factor_history.columns and factor_history[col].notna().any():
                ax.plot(factor_history["date"], factor_history[col], label=col, color=color)
                plotted = True
        if plotted:
            ax.set_title(f"{data['order_book_id']} valuation factors")
            ax.legend()
            fig.tight_layout()
            path = output_dir / "valuation_factors.png"
            fig.savefig(path, dpi=160)
            charts["valuation_factors"] = str(path)
        plt.close(fig)

    if not margin.empty and "date" in margin.columns:
        margin["date"] = pd.to_datetime(margin["date"])
        for col in ("margin_balance", "buy_on_margin_value", "short_balance", "total_balance"):
            if col in margin.columns:
                margin[col] = pd.to_numeric(margin[col], errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        plotted = False
        for col, color in (("margin_balance", "#2563eb"), ("short_balance", "#dc2626"), ("total_balance", "#111827")):
            if col in margin.columns and margin[col].notna().any():
                ax.plot(margin["date"], margin[col], label=col, color=color)
                plotted = True
        if plotted:
            ax.set_title(f"{data['order_book_id']} margin trading balances")
            ax.legend()
            fig.tight_layout()
            path = output_dir / "margin_balances.png"
            fig.savefig(path, dpi=160)
            charts["margin_balances"] = str(path)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4.8))
        plotted = False
        for col, color in (("buy_on_margin_value", "#7c3aed"), ("margin_repayment", "#16a34a")):
            if col in margin.columns and margin[col].notna().any():
                ax.plot(margin["date"], margin[col], label=col, color=color)
                plotted = True
        if plotted:
            ax.set_title(f"{data['order_book_id']} margin buy and repayment")
            ax.legend()
            fig.tight_layout()
            path = output_dir / "margin_activity.png"
            fig.savefig(path, dpi=160)
            charts["margin_activity"] = str(path)
        plt.close(fig)

    if not shares.empty and "date" in shares.columns:
        shares["date"] = pd.to_datetime(shares["date"])
        for col in ("total", "circulation_a", "free_circulation"):
            if col in shares.columns:
                shares[col] = pd.to_numeric(shares[col], errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        plotted = False
        for col, color in (("total", "#111827"), ("circulation_a", "#2563eb"), ("free_circulation", "#16a34a")):
            if col in shares.columns and shares[col].notna().any():
                ax.plot(shares["date"], shares[col], label=col, color=color)
                plotted = True
        if plotted:
            ax.set_title(f"{data['order_book_id']} share structure")
            ax.legend()
            fig.tight_layout()
            path = output_dir / "share_structure.png"
            fig.savefig(path, dpi=160)
            charts["share_structure"] = str(path)
        plt.close(fig)

    if not dividend.empty:
        cash_col = "dividend_cash_before_tax"
        date_col = "declaration_announcement_date" if "declaration_announcement_date" in dividend.columns else "date"
        if cash_col in dividend.columns and date_col in dividend.columns:
            dividend[date_col] = pd.to_datetime(dividend[date_col])
            dividend[cash_col] = pd.to_numeric(dividend[cash_col], errors="coerce")
            plot_dividend = dividend.dropna(subset=[cash_col]).tail(12)
            if not plot_dividend.empty:
                labels = plot_dividend.get("quarter", plot_dividend[date_col].dt.date.astype(str)).astype(str)
                fig, ax = plt.subplots(figsize=(10, 4.8))
                ax.bar(labels, plot_dividend[cash_col], color="#dc2626", alpha=0.78)
                ax.set_title(f"{data['order_book_id']} cash dividend history")
                ax.set_ylabel("cash before tax per 10 shares")
                ax.tick_params(axis="x", rotation=25)
                fig.tight_layout()
                path = output_dir / "dividend_history.png"
                fig.savefig(path, dpi=160)
                plt.close(fig)
                charts["dividend_history"] = str(path)

    if not interbank_rate.empty and "date" in interbank_rate.columns:
        interbank_rate["date"] = pd.to_datetime(interbank_rate["date"])
        for col in ("ON", "1W", "1M", "3M", "1Y"):
            if col in interbank_rate.columns:
                interbank_rate[col] = pd.to_numeric(interbank_rate[col], errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        plotted = False
        for col, color in (("ON", "#64748b"), ("1M", "#2563eb"), ("3M", "#dc2626"), ("1Y", "#7c3aed")):
            if col in interbank_rate.columns and interbank_rate[col].notna().any():
                ax.plot(interbank_rate["date"], interbank_rate[col], label=f"Shibor {col}", color=color)
                plotted = True
        if plotted:
            ax.set_title("Shibor term rates")
            ax.legend()
            fig.tight_layout()
            path = output_dir / "shibor_rates.png"
            fig.savefig(path, dpi=160)
            charts["shibor_rates"] = str(path)
        plt.close(fig)

    if not yield_curve.empty and "date" in yield_curve.columns:
        yield_curve["date"] = pd.to_datetime(yield_curve["date"])
        tenor_cols = [col for col in ("1Y", "3Y", "5Y", "10Y", "30Y") if col in yield_curve.columns]
        for col in tenor_cols:
            yield_curve[col] = pd.to_numeric(yield_curve[col], errors="coerce")
        latest_curve = yield_curve.dropna(subset=tenor_cols, how="all").tail(1)
        if tenor_cols and not latest_curve.empty:
            fig, ax = plt.subplots(figsize=(10, 4.8))
            values = [latest_curve[col].iloc[0] for col in tenor_cols]
            ax.plot(tenor_cols, values, marker="o", color="#2563eb")
            ax.set_title(f"China yield curve snapshot {latest_curve['date'].dt.date.iloc[0]}")
            ax.set_ylabel("yield")
            fig.tight_layout()
            path = output_dir / "yield_curve_snapshot.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            charts["yield_curve_snapshot"] = str(path)

    if factor_latest:
        valuation_keys = ["market_cap", "pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "dividend_yield_ttm"]
        quality_keys = ["gross_profit_margin_ttm", "net_profit_margin_ttm", "debt_to_asset_ratio", "current_ratio", "quick_ratio"]
        for name, keys in (("latest_valuation_snapshot", valuation_keys), ("latest_quality_snapshot", quality_keys)):
            rows = [(key, _float(factor_latest.get(key))) for key in keys]
            rows = [(key, value) for key, value in rows if value is not None]
            if not rows:
                continue
            fig, ax = plt.subplots(figsize=(9, 4.8))
            labels = [key for key, _ in rows]
            values = [value for _, value in rows]
            ax.bar(labels, values, color="#2563eb", alpha=0.78)
            ax.set_title(name.replace("_", " "))
            ax.tick_params(axis="x", rotation=20)
            fig.tight_layout()
            path = output_dir / f"{name}.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            charts[name] = str(path)
    return charts


def section_writer_agents(*, plan: dict[str, Any], data: dict[str, Any], charts: dict[str, str]) -> dict[str, str]:
    specs = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    specs = [spec for spec in specs if str(spec.get("name") or "") != CHART_INTERPRETATION_SECTION]
    ordered_names = [str(spec.get("name") or "分析章节") for spec in specs]
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=_get_max_workers()) as executor:
        future_map = {}
        for spec in specs:
            name = str(spec.get("name") or "分析章节")
            agent = str(spec.get("agent") or "section_writer")
            prompt_data = _compact_data_for_prompt(data, charts, name)
            future = executor.submit(_write_section, agent=agent, section_name=name, data=prompt_data)
            future_map[future] = name
        for future in as_completed(future_map):
            results[future_map[future]] = future.result()
    # 按 plan.sections 原始顺序重组，保证报告章节顺序稳定。
    return {name: results[name] for name in ordered_names if name in results}


def validation_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    draft_markdown: str,
) -> dict[str, Any]:
    fallback = _local_validation(data=data, charts=charts, sections=sections, draft_markdown=draft_markdown)
    if not get_env("OPENAI_API_KEY"):
        return fallback
    try:
        validation = llm_json(
            "你是研报验证 Agent。只返回 JSON，不写 Markdown。"
            "你的任务是检查报告是否忠于已采集数据、是否遗漏重要图表解读、是否有应补充或应收敛的结论。"
            "你必须逐章节检查是否和目标股票直接相关；泛泛讲宏观、行业、市场或方法论但没有落到目标股票的数据、图表或结论的部分，必须要求改写。"
            "禁止要求补充 Wind、新闻、券商预测、管理层指引等本系统未采集数据。",
            json.dumps(
                {
                    "plan": plan,
                    "target_stock": {
                        "order_book_id": data.get("order_book_id"),
                        "industry": data.get("industry"),
                    },
                    "data_inventory": _data_inventory(data),
                    "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
                    "local_chart_review": _chart_quality_review(data=data, charts=charts),
                    "local_stock_relevance_review": _stock_relevance_review(data=data, sections=sections),
                    "charts": charts,
                    "sections": sections,
                    "draft_markdown": draft_markdown[:14000],
                    "local_checks": fallback,
                },
                ensure_ascii=False,
            )[:22000]
            + "\n你可以通过 refinement_requests 要求系统再次调用 data_agent 或 chart_agent。"
            "\n如果图表低信息量、重复、量纲混乱或无法支撑正文结论，请在 chart_quality_review.delete/redraw 中列出，并把 refresh_charts 设为 true。"
            "\n如果需要更长回看期或补充已支持的数据源，请把 refresh_data 设为 true，并给出 lookback_days。"
            + "\n必须返回 score/action_items/section_feedback/unsupported_claims/missing_data_notes/chart_quality_review/stock_relevance_review/refinement_requests/final_decision。"
            "\nscore 为 0-100；section_feedback 是对象，key 是章节名，value 是修改建议列表。",
        )
        return _sanitize_validation(validation, fallback)
    except Exception as exc:
        fallback["validator_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


def revise_sections_with_validation(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any],
) -> dict[str, str]:
    feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
    action_items = validation.get("action_items") if isinstance(validation.get("action_items"), list) else []
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    if not get_env("OPENAI_API_KEY") or not (feedback or action_items or has_relevance_rewrite):
        return sections
    revised = dict(sections)

    def _revise_one(name: str, content: str) -> str:
        section_notes = _string_list(feedback.get(name))
        section_relevance = relevance.get(name) if isinstance(relevance.get(name), dict) else {}
        if section_relevance.get("decision") == "rewrite":
            section_notes.append(str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。"))
        if not section_notes and not action_items:
            return content
        prompt_data = _compact_data_for_prompt(data, charts, name)
        try:
            text = llm_text(
                f"你是 revise_agent。请根据验证 Agent 的意见，重写《{name}》章节。"
                "只能使用 JSON 中已有数据；不要新增未采集来源；不要给买卖建议。"
                "需要补充数据局限和更可追溯的数字表述；不要在正文写图表解读或 charts/ 路径，图表与图注由系统统一编排。"
                "每一段都必须回到目标股票本身：引用目标股票代码、目标股票的米筐数据字段或目标股票对应行业归属。"
                "如果原文有泛泛讲宏观、行业、市场或方法论但没有连接目标股票的句子，请删除或改写。"
                "直接输出 Markdown 正文，不要开场白、不要复述验证意见、不要写「好的，这是…」。"
                "「数据局限」须用 #### 四级标题单独成段；不要写 charts/ 路径、不要写「请参考图表」或正文内嵌图注。"
                "分段落、用小标题或 bullet 组织，不要一大段连在一起。",
                json.dumps(
                    {
                        "section_name": name,
                        "original_section": content,
                        "section_feedback": section_notes,
                        "stock_relevance_feedback": section_relevance,
                        "global_action_items": action_items,
                        "data": prompt_data,
                    },
                    ensure_ascii=False,
                )[:18000],
            )
            return normalize_section_text(text, name)
        except Exception:
            return content

    with ThreadPoolExecutor(max_workers=_get_max_workers()) as executor:
        future_map = {executor.submit(_revise_one, name, content): name for name, content in sections.items()}
        for future in as_completed(future_map):
            revised[future_map[future]] = future.result()
    return revised


def refinement_loop(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    validation: dict[str, Any],
    order_book_id: str,
    stock_code: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    chart_output_dir: Path,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Allow one bounded data/chart retry after the validator sees the draft."""
    requests = _refinement_requests(validation)
    if not requests:
        chart_review = _chart_quality_review(data=data, charts=charts)
        charts = _prune_charts(charts, chart_review)
        validation["chart_quality_review"] = chart_review
        return data, charts, validation
    next_lookback = max(lookback_days, int(requests.get("lookback_days") or lookback_days))
    if requests.get("refresh_data"):
        data = data_executor_agent(
            order_book_id=order_book_id,
            stock_code=stock_code,
            as_of=as_of,
            lookback_days=next_lookback,
            output_dir=output_dir,
        )
    if requests.get("refresh_charts"):
        chart_files = chart_agent(data=data, output_dir=chart_output_dir)
        charts = {name: _markdown_path(path, output_dir) for name, path in chart_files.items()}
    chart_review = _chart_quality_review(data=data, charts=charts)
    charts = _prune_charts(charts, chart_review)
    validation["chart_quality_review"] = chart_review
    validation["refinement_performed"] = {
        "refresh_data": bool(requests.get("refresh_data")),
        "refresh_charts": bool(requests.get("refresh_charts")),
        "lookback_days": next_lookback,
        "reason": requests.get("reason"),
    }
    _finalize_validation_after_refinement(validation, charts)
    return data, charts, validation


def chart_placement_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validation or {}
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    blocked = {str(name) for name in delete}
    fallback = build_default_chart_placement(charts=charts, sections=sections, blocked=blocked)
    return fill_missing_section_placements(
        fallback, charts=charts, sections=sections, blocked=blocked
    )


def _charts_needing_figure_notes(placement: dict[str, Any], charts: dict[str, str]) -> list[str]:
    names: list[str] = []
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        for name in item.get("charts") or []:
            if name in charts and name not in names:
                names.append(str(name))
    for name in placement.get("unused") or []:
        if name in charts and name not in names:
            names.append(str(name))
    return names


def chart_figure_notes_agent(
    *,
    data: dict[str, Any],
    charts: dict[str, str],
    chart_names: list[str] | None = None,
) -> dict[str, str]:
    """为每张图生成研报式图注；无 LLM 时回退到规则模板。"""
    names = [name for name in (chart_names or list(charts.keys())) if name in charts]
    if not names:
        return {}
    if not get_env("OPENAI_API_KEY"):
        return {name: fallback_chart_note(name, data) for name in names}

    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    chart_items = [
        {
            "chart_name": name,
            "caption": CHART_CAPTIONS.get(name, name.replace("_", " ")),
            "fallback_note": fallback_chart_note(name, data),
        }
        for name in names
    ]
    try:
        result = llm_json(
            "你是 chart_interpreter agent，为研报图表撰写图注。"
            "要求：结合 JSON 中的具体数值解读每张图的关键信息；说明趋势、对比或异常；"
            "每条 1-2 句，学术研报口吻；禁止写文件路径、禁止「请参考/见上图」等空泛引用；"
            "输出 JSON：{\"notes\": {\"chart_name\": \"图注正文\"}}，chart_name 必须与输入一致。",
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "technical": technical,
                    "factor": factor,
                    "charts": chart_items,
                },
                ensure_ascii=False,
            )[:14000],
        )
        raw_notes = result.get("notes") if isinstance(result.get("notes"), dict) else result
        notes: dict[str, str] = {}
        if isinstance(raw_notes, dict):
            for name in names:
                value = raw_notes.get(name)
                if value:
                    notes[name] = str(value).strip()
        for name in names:
            notes.setdefault(name, fallback_chart_note(name, data))
        return notes
    except Exception:
        return {name: fallback_chart_note(name, data) for name in names}


def _executive_summary_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
) -> str:
    if not get_env("OPENAI_API_KEY"):
        return _local_executive_summary(plan=plan, data=data, sections=sections)
    try:
        text = llm_text(
            "你是最终汇总 Agent。只能基于输入 JSON 和各分段结论写执行摘要，不给买卖建议。"
            "禁止添加宏观、行业、新闻、Wind、券商预测、管理层指引等输入中不存在的信息。"
            "如果某类信息没有采集，就明确写为数据局限。"
            "输出格式：先 1 句核心结论，再 3-5 条 bullet；每条不超过 40 字，精炼可读。"
            "只输出 Markdown，不要 JSON、代码块或键值对。",
            json.dumps(
                {
                    "plan": plan,
                    "technical": data.get("technical"),
                    "factor": data.get("factor"),
                    "industry": data.get("industry"),
                    "validation": validation,
                    "sections": sections,
                },
                ensure_ascii=False,
            )[:18000],
        )
        return normalize_section_text(text, "执行摘要")
    except Exception:
        return _local_executive_summary(plan=plan, data=data, sections=sections)


def _local_executive_summary(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
) -> str:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    lines = [
        f"{data.get('order_book_id', '目标标的')} 多智能体研究已完成，以下为本地规则摘要。",
        "",
        f"- 最新收盘价 {technical.get('latest_close', '—')}，20 日收益率 {technical.get('return_20d', '—')}",
        f"- PE(TTM) {factor.get('pe_ratio_ttm', '—')}，PB(TTM) {factor.get('pb_ratio_ttm', '—')}",
    ]
    for name in [item.get("name") for item in plan.get("sections") or [] if isinstance(item, dict)][:3]:
        excerpt = normalize_section_text(sections.get(str(name), ""), str(name))
        if excerpt == "_本节暂无可用内容。_":
            continue
        first = excerpt.split("\n")[0].strip()[:60]
        if first:
            lines.append(f"- {name}：{first}")
    return "\n".join(lines)


def final_synthesis_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
) -> str:
    """兼容旧调用：生成执行摘要并渲染 Markdown。"""
    summary = _executive_summary_agent(plan=plan, data=data, sections=sections, validation=validation)
    chart_placement = chart_placement_agent(
        plan=plan, data=data, charts=charts, sections=sections, validation=validation
    )
    figure_note_charts = _charts_needing_figure_notes(chart_placement, charts)
    figure_notes = chart_figure_notes_agent(data=data, charts=charts, chart_names=figure_note_charts)
    sections, unused_charts = apply_chart_placements(
        sections, charts, chart_placement, figure_notes=figure_notes, data=data
    )
    sections[CHART_INTERPRETATION_SECTION] = build_chart_interpretation_section(
        unused_charts, charts, figure_notes=figure_notes, data=data
    )
    return render_multi_markdown(
        summary=summary,
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        inline_charts=True,
        unused_charts=[],
        validation=validation,
    )


def _should_revise(validation: dict[str, Any]) -> bool:
    if not get_env("OPENAI_API_KEY"):
        return False
    from .multi_report import validation_passed

    if validation_passed(validation):
        return False
    feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
    action_items = _string_list(validation.get("action_items"))
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    has_feedback = any(_string_list(value) for value in feedback.values())
    return bool(has_feedback or action_items or has_relevance_rewrite)


def _write_section(*, agent: str, section_name: str, data: dict[str, Any]) -> str:
    if section_name == CHART_INTERPRETATION_SECTION or agent == "chart_writer":
        return normalize_section_text("_本节由图表编排阶段自动生成。_", section_name)
    if not get_env("OPENAI_API_KEY"):
        return normalize_section_text(
            f"{agent} 本地摘要：{section_name} 已基于可用数据完成。",
            section_name,
        )
    try:
        text = llm_text(
            f"你是 {agent}。请写研报中的《{section_name}》章节。"
            "只能使用用户提供的 JSON 数据，不得补充外部来源、宏观、行业、新闻、Wind、券商预测或未采集信息。"
            "所有数值结论必须能从 JSON 中追溯；没有数据就写数据局限。不要给买卖建议。"
            "输出 Markdown 正文：分段落、用小标题或 bullet 组织，不要一大段连在一起；"
            "「数据局限」须用 #### 四级标题单独成段；不要写 charts/ 路径、不要写「请参考图表」或正文图表解读（图表与图注由系统编排）。"
            "不要输出 JSON 或代码块。",
            json.dumps(data, ensure_ascii=False)[:16000],
        )
        return normalize_section_text(text, section_name)
    except Exception as exc:
        return normalize_section_text(
            f"{agent} 章节生成失败，已保留数据摘要。错误：{exc}",
            section_name,
        )


def _previous_trading_date(rqdatac: Any, value: date) -> date:
    if rqdatac.is_trading_date(value):
        return value
    return rqdatac.get_previous_trading_date(value)


def _safe_rq_call(name: str, fn: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        print(f"[rqdatac] {name} skipped: {type(exc).__name__}: {exc}")
        return pd.DataFrame()


def _flatten_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.reset_index()
    rename = {"tradedate": "date", "trading_date": "date"}
    frame = frame.rename(columns=rename)
    for col in ("date", "datetime"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col]).dt.date.astype(str)
    return frame


def _frame_summary(df: pd.DataFrame, *, tail: int) -> dict[str, Any]:
    return {"rows": _records(df.tail(tail)), "row_count": int(len(df)), "columns": list(df.columns)}


def _capital_flow_summary(df: pd.DataFrame) -> dict[str, Any]:
    rows = _records(df)
    if df.empty:
        return {"rows": rows, "row_count": 0, "net_buy_value_sum": None}
    net = float((df["buy_value"] - df["sell_value"]).sum()) if {"buy_value", "sell_value"}.issubset(df.columns) else None
    return {"rows": rows, "row_count": int(len(df)), "net_buy_value_sum": net, "columns": list(df.columns)}


def _latest_row(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    return _records(df.tail(1))[0]


def _technical_summary(df: pd.DataFrame) -> dict[str, Any]:
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


def _data_inventory(data: dict[str, Any]) -> dict[str, Any]:
    inventory = {}
    for key, value in data.items():
        if isinstance(value, dict) and "row_count" in value:
            inventory[key] = {"row_count": value.get("row_count"), "columns": value.get("columns")}
        elif key in {"factor", "industry", "technical"}:
            inventory[key] = value
    return inventory


def _local_validation(*, data: dict[str, Any], charts: dict[str, str], sections: dict[str, str], draft_markdown: str) -> dict[str, Any]:
    action_items = []
    chart_review = _chart_quality_review(data=data, charts=charts)
    relevance_review = _stock_relevance_review(data=data, sections=sections)
    if len(charts) < 8:
        action_items.append(f"图表数量只有 {len(charts)} 张，建议补充到至少 8 张。")
    for name, reason in chart_review.get("delete", {}).items():
        action_items.append(f"图表 {name} 信息含量不足或量纲不合适，建议删除或重画：{reason}")
    for name, review in relevance_review.items():
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 与目标股票关联不足，需要改写：{review.get('reason')}")
    for key in ("price", "factor_history", "capital_flow", "securities_margin", "dividend", "shares", "interbank_rate", "yield_curve", "pit_financials"):
        value = data.get(key)
        if isinstance(value, dict) and int(value.get("row_count") or 0) == 0:
            action_items.append(f"{key} 没有返回可用行，需要在报告中说明数据局限。")
    unsupported = []
    for token in ("Wind", "券商预测", "新闻", "管理层指引"):
        if token in draft_markdown:
            unsupported.append(token)
    return {
        "score": 80 if not unsupported and len(charts) >= 8 else 65,
        "action_items": action_items,
        "section_feedback": {},
        "unsupported_claims": unsupported,
        "missing_data_notes": action_items,
        "chart_quality_review": chart_review,
        "stock_relevance_review": relevance_review,
        "final_decision": "revise" if action_items or unsupported else "pass",
        "refinement_requests": {
            "refresh_data": False,
            "refresh_charts": len(charts) < 8 or bool(chart_review.get("redraw")),
            "lookback_days": None,
            "reason": "图表数量不足或存在低质量图" if len(charts) < 8 or chart_review.get("redraw") else None,
        },
    }


def _sanitize_validation(validation: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(validation) if isinstance(validation, dict) else {}
    result["score"] = int(_float(result.get("score")) or fallback["score"])
    result["action_items"] = _string_list(result.get("action_items")) or fallback["action_items"]
    result["unsupported_claims"] = _string_list(result.get("unsupported_claims"))
    result["missing_data_notes"] = _string_list(result.get("missing_data_notes"))
    chart_review = result.get("chart_quality_review")
    result["chart_quality_review"] = chart_review if isinstance(chart_review, dict) else fallback.get("chart_quality_review", {})
    relevance_review = result.get("stock_relevance_review")
    result["stock_relevance_review"] = relevance_review if isinstance(relevance_review, dict) else fallback.get("stock_relevance_review", {})
    feedback = result.get("section_feedback")
    result["section_feedback"] = feedback if isinstance(feedback, dict) else {}
    decision = str(result.get("final_decision") or fallback["final_decision"]).lower()
    result["final_decision"] = decision if decision in {"pass", "revise", "block"} else "revise"
    requests = result.get("refinement_requests")
    result["refinement_requests"] = requests if isinstance(requests, dict) else fallback.get("refinement_requests", {})
    return result


def _refinement_requests(validation: dict[str, Any]) -> dict[str, Any]:
    requests = validation.get("refinement_requests") if isinstance(validation.get("refinement_requests"), dict) else {}
    action_text = " ".join(_string_list(validation.get("action_items")))
    refresh_charts = bool(requests.get("refresh_charts")) or "图表" in action_text
    refresh_data = bool(requests.get("refresh_data"))
    result = {
        "refresh_data": refresh_data,
        "refresh_charts": refresh_charts,
        "lookback_days": requests.get("lookback_days"),
        "reason": requests.get("reason") or action_text[:160],
    }
    return result if refresh_data or refresh_charts else {}


def _chart_quality_review(*, data: dict[str, Any], charts: dict[str, str]) -> dict[str, Any]:
    delete: dict[str, str] = {}
    redraw: dict[str, str] = {}
    keep: dict[str, str] = {}
    if "latest_valuation_snapshot" in charts:
        delete["latest_valuation_snapshot"] = "市值、PE、PB、PS、股息率量纲差异过大，放在同一柱状图会误导比较。"
    if "latest_quality_snapshot" in charts:
        keep["latest_quality_snapshot"] = "盈利能力和偿债指标虽量纲不同，但用于最新横截面风险提示仍可保留。"
    shares = pd.DataFrame(data.get("shares", {}).get("rows", []))
    if "share_structure" in charts and not shares.empty:
        cols = [col for col in ("total", "circulation_a", "free_circulation") if col in shares.columns]
        if cols and all(pd.to_numeric(shares[col], errors="coerce").nunique(dropna=True) <= 1 for col in cols):
            delete["share_structure"] = "股本结构在区间内基本不变，折线图信息量低，正文说明即可。"
    dividend = pd.DataFrame(data.get("dividend", {}).get("rows", []))
    if "dividend_history" in charts and len(dividend) < 3:
        delete["dividend_history"] = "分红样本点过少，图形解释力不足。"
    if "price_volume" in charts and "moving_averages" in charts:
        keep["price_volume"] = "量价结合展示交易活跃度。"
        keep["moving_averages"] = "均线图用于趋势判断，和量价图用途不同。"
    if len(charts) - len(delete) < 8:
        redraw["chart_count"] = "删除低质量图后图表不足 8 张，应优先补充非重复、可解释的两融/宏观/估值趋势图。"
    return {"requirements": CHART_QUALITY_REQUIREMENTS, "keep": keep, "redraw": redraw, "delete": delete}


def _prune_charts(charts: dict[str, str], chart_review: dict[str, Any]) -> dict[str, str]:
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    if not delete:
        return charts
    return {name: path for name, path in charts.items() if name not in delete}


def _finalize_validation_after_refinement(validation: dict[str, Any], charts: dict[str, str]) -> None:
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    remaining_redraw = chart_review.get("redraw") if isinstance(chart_review.get("redraw"), dict) else {}
    unsupported = _string_list(validation.get("unsupported_claims"))
    if len(charts) >= 8 and not has_relevance_rewrite and not remaining_redraw and not unsupported:
        validation["final_decision"] = "pass_after_revision"
        validation["score"] = max(int(_float(validation.get("score")) or 0), 85)


def _stock_relevance_review(*, data: dict[str, Any], sections: dict[str, str]) -> dict[str, Any]:
    target = str(data.get("order_book_id") or "")
    code = target.split(".")[0] if target else ""
    industry = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    industry_terms = [str(value) for key, value in industry.items() if "industry" in key and value]
    target_terms = [term for term in [target, code, "该股", "该公司", "目标股票", *industry_terms] if term]
    data_terms = [
        "close",
        "volume",
        "turnover",
        "PE",
        "PB",
        "PS",
        "market_cap",
        "dividend",
        "margin",
        "Shibor",
        "yield",
        "资金流",
        "换手",
        "分红",
        "两融",
        "股本",
        "估值",
        "收益率",
        "图",
    ]
    generic_terms = ["宏观", "行业", "市场", "方法论", "一般而言", "整体来看", "通常", "投资者应"]
    review: dict[str, Any] = {}
    for name, content in sections.items():
        text = str(content or "")
        has_target = any(term in text for term in target_terms)
        has_data = any(term in text for term in data_terms)
        is_generic = any(term in text for term in generic_terms)
        if has_target and has_data:
            review[name] = {"decision": "pass", "reason": "章节同时引用目标股票或行业归属，并使用了目标股票数据/图表口径。"}
        elif has_data and not is_generic:
            review[name] = {"decision": "pass", "reason": "章节使用了目标股票数据口径，但建议在改写时更明确点名目标股票。"}
        else:
            review[name] = {
                "decision": "rewrite",
                "reason": f"本节缺少对 {target or '目标股票'} 的直接数据、图表或行业归属连接，容易变成泛泛分析。",
            }
    return review


def _validation_markdown(validation: dict[str, Any] | None) -> list[str]:
    if not validation:
        return ["- 未运行验证 Agent。"]
    lines = [
        f"- 评分：{validation.get('score', 'N/A')}",
        f"- 结论：{validation.get('final_decision', 'N/A')}",
    ]
    if validation.get("refinement_performed"):
        lines.append(f"- 已执行补采/补图：{json.dumps(validation['refinement_performed'], ensure_ascii=False)}")
    for item in _string_list(validation.get("action_items"))[:8]:
        lines.append(f"- 修改建议：{item}")
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    for name, review in list(relevance.items())[:8]:
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            lines.append(f"- 目标股票相关性：{name} 需要改写，原因：{review.get('reason')}")
    for item in _string_list(validation.get("unsupported_claims"))[:5]:
        lines.append(f"- 疑似未支撑表述：{item}")
    if len(lines) == 2:
        lines.append("- 未发现需要强制返工的问题。")
    return lines


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


SECTION_PROMPT_KEYS: dict[str, tuple[str, ...]] = {
    "量价与趋势": ("technical", "price_recent", "price_change_rate_recent", "turnover_recent", "charts"),
    "基本面与估值": ("factor", "industry", "pit_financials", "dividend_recent", "shares_recent", "charts"),
    "资金与交易结构": ("capital_flow", "securities_margin_recent", "charts"),
    "技术因素": ("technical", "price_recent", "price_change_rate_recent", "charts"),
    "宏观利率背景": ("macro_rate_recent", "charts"),
    "综合风险与数据局限": ("status_checks", "technical", "factor", "industry", "pit_financials", "charts"),
}

_PIT_FINANCIAL_KEYS = (
    "year",
    "quarter",
    "revenue",
    "operating_revenue",
    "net_profit_parent_company",
    "cash_flow_from_operating_activities",
    "total_assets",
    "total_liabilities",
    "equity_parent_company",
)


def _slim_pit_financials(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slim_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slim = {key: row.get(key) for key in _PIT_FINANCIAL_KEYS if row.get(key) not in (None, "")}
        if "year" not in slim and row.get("quarter"):
            slim["year"] = int(str(row["quarter"])[:4])
        if slim:
            slim_rows.append(_json_ready(slim))
    return slim_rows


def _compact_data_for_prompt(data: dict[str, Any], charts: dict[str, str], section_name: str) -> dict[str, Any]:
    full = {
        "section_name": section_name,
        "order_book_id": data.get("order_book_id"),
        "date_range": [data.get("start_date"), data.get("end_date")],
        "technical": data.get("technical"),
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "pit_financials": data.get("pit_financials"),
        "capital_flow": {k: v for k, v in data.get("capital_flow", {}).items() if k != "rows"}
        | {"recent_rows": data.get("capital_flow", {}).get("rows", [])[-8:]},
        "price_recent": data.get("price", {}).get("rows", [])[-12:],
        "price_change_rate_recent": data.get("price_change_rate", {}).get("rows", [])[-12:],
        "turnover_recent": data.get("turnover", {}).get("rows", [])[-12:],
        "securities_margin_recent": data.get("securities_margin", {}).get("rows", [])[-12:],
        "dividend_recent": data.get("dividend", {}).get("rows", [])[-8:],
        "shares_recent": data.get("shares", {}).get("rows", [])[-8:],
        "macro_rate_recent": {
            "interbank_rate": data.get("interbank_rate", {}).get("rows", [])[-8:],
            "yield_curve": data.get("yield_curve", {}).get("rows", [])[-8:],
        },
        "status_checks": {
            "suspended_recent": data.get("suspended", {}).get("rows", [])[-8:],
            "st_recent": data.get("st_stock", {}).get("rows", [])[-8:],
        },
        "charts": charts,
    }
    keys = SECTION_PROMPT_KEYS.get(section_name)
    if not keys:
        return full
    picked = {key: full[key] for key in keys if key in full}
    picked["section_name"] = section_name
    picked["order_book_id"] = full["order_book_id"]
    picked["date_range"] = full["date_range"]
    return picked


def _write_data_log(
    output_dir: Path,
    order_book_id: str,
    start_date: date,
    end_date: date,
    factors: list[str],
    frames: dict[str, pd.DataFrame],
    *,
    pit_row_count: int = 0,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{order_book_id.replace('.', '_')}_data_agent.log"
    key_to_tool = {
        "price": "get_price",
        "price_change_rate": "get_price_change_rate",
        "turnover": "get_turnover_rate",
        "capital_flow": "get_capital_flow",
        "securities_margin": "get_securities_margin",
        "dividend": "get_dividend",
        "shares": "get_shares",
        "suspended": "is_suspended",
        "st_stock": "is_st_stock",
        "industry": "get_instrument_industry",
        "interbank_rate": "get_interbank_offered_rate",
        "yield_curve": "get_yield_curve",
        "factor": "get_factor(latest)",
        "factor_history": "get_factor(history)",
        "pit_financials": "get_pit_financials_ex",
    }
    lines = [
        f"[{datetime.now().isoformat(timespec='seconds')}] FinAgent data_executor_agent",
        f"order_book_id={order_book_id}",
        f"start_date={start_date.isoformat()}",
        f"end_date={end_date.isoformat()}",
        f"factors={factors}",
        "",
        "[data_fetch_summary]",
    ]
    for key, tool in key_to_tool.items():
        if key == "pit_financials":
            if pit_row_count > 0:
                lines.append(f"- {tool}: OK row_count={pit_row_count}")
            else:
                lines.append(f"- {tool}: EMPTY row_count=0")
            continue
        frame = frames.get(key)
        if frame is None or frame.empty:
            lines.append(f"- {tool}: EMPTY row_count=0")
            continue
        cols = ", ".join(str(col) for col in frame.columns[:12])
        if len(frame.columns) > 12:
            cols += ", ..."
        lines.append(f"- {tool}: OK row_count={len(frame)} columns=[{cols}]")
    lines.extend(
        [
            "",
            "[note]",
            "本日志记录 multi-analyze 数据执行阶段的米筐拉取结果，便于追溯与排查。",
            "如需复现数据，请使用 FinAgent multi-analyze 命令并参考上述参数。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _markdown_path(path: str, base_dir: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(base_dir.resolve())
    except Exception:
        rel = Path(path)
    return rel.as_posix()


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_ready(row) for row in df.to_dict(orient="records")]


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value
