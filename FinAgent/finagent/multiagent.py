from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .chart_dynamic import (
    build_placement_from_chart_need,
    dynamic_chart_pipeline,
)
from .chart_plots import chart_agent
from .data_registry import DATA_KEY_TO_TOOL, benchmark_index_id
from .technical import safe_float, technical_summary
from .data_capabilities import (
    build_data_capability_inventory,
    build_data_gap_review,
    normalize_executive_summary_gaps,
    reconcile_validation_gaps,
)
from .cninfo import default_as_of, normalize_stock_code, to_order_book_id
from .env import get_env, load_dotenv
from .llm import llm_json, llm_text
from .multi_report import (
    CHART_CAPTIONS,
    CHART_INTERPRETATION_SECTION,
    DATA_LIMITATIONS_SECTION,
    DEFERRED_SECTIONS,
    MARKET_TECH_SECTION,
    RISK_SECTION,
    SYNTHESIS_SECTION,
    analysis_section_names,
    apply_chart_placement_fixes,
    apply_chart_placements,
    build_chart_catalog,
    build_default_chart_placement,
    build_multi_json_payload,
    build_unified_data_limitations,
    extract_section_structure,
    fallback_chart_note,
    fill_missing_section_placements,
    finalize_inline_only_placement,
    flatten_chart_placements,
    local_chart_placement_review,
    normalize_chart_placement,
    normalize_section_text,
    prune_charts_dict,
    render_multi_html,
    render_multi_markdown,
    section_digest,
    strip_all_section_limitations,
    validation_passed,
)
from .report_format import write_report
from .report_html import write_html_report
from .rqdata_client import _init_rqdata, fetch_financials


def _get_max_workers() -> int:
    try:
        return max(1, int(get_env("FINAGENT_MAX_WORKERS", "4")))
    except (TypeError, ValueError):
        return 4


def _get_validation_max_rounds() -> int:
    try:
        return max(1, int(get_env("FINAGENT_VALIDATION_MAX_ROUNDS", "2")))
    except (TypeError, ValueError):
        return 2


def _get_chart_placement_max_rounds() -> int:
    try:
        return max(1, int(get_env("FINAGENT_CHART_PLACEMENT_MAX_ROUNDS", "2")))
    except (TypeError, ValueError):
        return 2


TOOL_REGISTRY = {
    "get_price": "量价行情：open/high/low/close/volume/total_turnover",
    "get_price_change_rate": "日涨跌幅序列，用于收益率和波动分析",
    "get_turnover_rate": "换手率：today/week/month/year/current_year",
    "get_capital_flow": "资金流向：buy_volume/buy_value/sell_volume/sell_value",
    "get_factor": "估值、盈利、偿债、成长和分红因子：market_cap/pe/pb/ps/dividend_yield/margin/debt/liquidity/growth",
    "get_securities_margin": "融资融券：margin_balance/buy_on_margin_value/short_balance/total_balance",
    "get_dividend": "分红方案：现金分红、除权除息日、支付日、报告期",
    "get_shares": "股本结构：total/circulation_a/free_circulation 等",
    "get_instrument_industry": "中信一级/二级行业归属，用于限定可比口径和行业背景",
    "get_block_trade": "大宗交易：成交价、成交量、成交额、买方/卖方营业部",
    "get_benchmark_index": "基准指数收盘价（沪深300/创业板指/科创50 等），用于相对强弱对比",
    "is_suspended": "停牌状态检查",
    "is_st_stock": "ST 状态检查",
    "get_interbank_offered_rate": "Shibor 同业拆借利率，用作宏观流动性背景",
    "get_yield_curve": "中国收益率曲线，用作无风险利率和期限结构背景",
    "get_pit_financials_ex": "年报口径三表财务字段，复用 FinAgent 原有财务数据模块",
}

DEFAULT_SECTIONS = [
    {
        "name": MARKET_TECH_SECTION,
        "agent": "market_technical_writer",
        "data": ["get_price", "get_price_change_rate", "get_turnover_rate", "get_benchmark_index"],
    },
    {
        "name": "基本面与估值",
        "agent": "fundamental_writer",
        "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares", "get_instrument_industry"],
    },
    {
        "name": "资金与交易结构",
        "agent": "capital_flow_writer",
        "data": ["get_capital_flow", "get_securities_margin", "get_block_trade"],
    },
    {"name": "宏观利率背景", "agent": "macro_rate_writer", "data": ["get_interbank_offered_rate", "get_yield_curve"]},
    {"name": SYNTHESIS_SECTION, "agent": "synthesis_judgment_writer", "data": ["section_summaries"]},
    {"name": RISK_SECTION, "agent": "risk_synthesis_writer", "data": ["all_collected_data", "is_suspended", "is_st_stock"]},
    {"name": DATA_LIMITATIONS_SECTION, "agent": "data_limitations_builder", "data": ["all_collected_data"]},
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
    "roe_ttm",
    "operating_revenue_growth_ratio_ttm",
    "inventory_turnover_rate_ttm",
    "total_asset_turnover_ttm",
]

CHART_QUALITY_REQUIREMENTS = [
    "每张图必须回答一个明确问题，不能为了凑数量画单一常数或重复口径。",
    "同一信息只保留最有解释力的一张图，避免价格/收益/均线图之间无差别堆叠。",
    "不同量纲不要直接放在同一柱状图里比较；市值、PE、PB、股息率等需拆分或只写入正文。",
    "宏观利率图必须服务于估值折现率或流动性背景，不得泛泛而谈。",
    "分红、股本、两融等事件型或结构型数据若变化很少，优先在正文表述，图表可删除。",
]

_SECTION_WRITING_STYLE = (
    "全章统一采用「结论先行」叙事，写法对标《宏观利率背景》："
    "（1）每个 ### 小标题用「主题：判断」格式（如「资金面与短端利率：融资成本边际变化」），标题本身给出方向；"
    "（2）小节首段 1-2 句先写结论/格局，再展开；禁止以日度行情流水账或指标清单开篇；"
    "（3）数字放在 bullet 里作证据，每条 bullet 尽量带一句含义，不要连续堆叠裸数字；"
    "（4）每个主题块末尾用 **对 {order_book_id} 的影响**（或同等句式）点明对目标股票的含义；"
    "（5）章末必须有 ### 综合判断，用 2-4 条收束全章主线。"
    "禁止把章节写成数据清单、字段复述或「先列数字、后补一句总结」。"
)

_NARRATIVE_SECTIONS = frozenset(
    {
        MARKET_TECH_SECTION,
        "基本面与估值",
        "资金与交易结构",
        RISK_SECTION,
    }
)


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
    sections = section_writer_agents(plan=plan, data=data, charts={})
    data, sections, validation, chart_meta = run_validation_cycle(
        plan=plan,
        data=data,
        sections=sections,
        order_book_id=order_book_id,
        stock_code=stock_code,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        output_dir=output_path.parent,
        chart_output_dir=chart_output_dir,
        markdown_base=output_path.parent,
    )
    charts = chart_meta.get("charts") or {}
    chart_placement = chart_placement_with_validation(
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        validation=validation,
        chart_need=chart_meta.get("need"),
    )
    figure_note_charts = _charts_needing_figure_notes(chart_placement, charts)
    figure_notes = chart_figure_notes_agent(data=data, charts=charts, chart_names=figure_note_charts)
    sections, omitted_charts = apply_chart_placements(
        sections, charts, chart_placement, figure_notes=figure_notes, data=data
    )
    sections.pop(CHART_INTERPRETATION_SECTION, None)
    charts = prune_charts_dict(charts, omitted_charts)
    sections, limitation_notes = strip_all_section_limitations(sections)
    sections[SYNTHESIS_SECTION] = synthesis_judgment_agent(
        plan=plan, data=data, sections=sections, validation=validation
    )
    validation = reconcile_validation_gaps(validation, data, charts)
    sections[DATA_LIMITATIONS_SECTION] = build_unified_data_limitations(
        data, limitation_notes, validation, charts=charts
    )
    summary = normalize_executive_summary_gaps(
        _executive_summary_agent(
            plan=plan, data=data, sections=sections, validation=validation, charts=charts
        )
    )
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
        unused_charts=omitted_charts,
        figure_notes=figure_notes,
        chart_need=chart_meta.get("need"),
        chart_pipeline=chart_meta,
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
        "objective": "生成有主线的 A 股多智能体研究报告：分析章节 → 综合判断 → 风险 → 统一数据局限",
        "tools": list(TOOL_REGISTRY),
        "sections": DEFAULT_SECTIONS,
        "risk_controls": [
            "仅基于可取得数据写结论",
            "各分析章节采用结论先行结构，对标《宏观利率背景》",
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
    benchmark_id, benchmark_label = benchmark_index_id(order_book_id)

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
        "industry_l2": lambda: rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=2, date=end_date),
        "index_benchmark": lambda: rqdatac.get_price(
            benchmark_id,
            start_date=start_date,
            end_date=end_date,
            frequency="1d",
            fields=["close"],
        ),
        "block_trade": lambda: rqdatac.get_block_trade(order_book_id, start_date=start_date, end_date=end_date),
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
    industry_l2 = fetched["industry_l2"]
    index_benchmark = fetched["index_benchmark"]
    block_trade = fetched["block_trade"]
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
        "industry_l2": _flatten_frame(industry_l2),
        "index_benchmark": _flatten_frame(index_benchmark),
        "block_trade": _flatten_frame(block_trade),
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
        "benchmark_index": {"id": benchmark_id, "label": benchmark_label},
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
        "industry": _merge_industry_rows(frames["industry"], frames["industry_l2"]),
        "industry_l2": _latest_row(frames["industry_l2"]),
        "index_benchmark": _frame_summary(frames["index_benchmark"], tail=max(260, lookback_days)),
        "block_trade": _frame_summary(frames["block_trade"], tail=40),
        "interbank_rate": _frame_summary(frames["interbank_rate"], tail=120),
        "yield_curve": _frame_summary(frames["yield_curve"], tail=120),
        "factor": _latest_row(frames["factor"]),
        "factor_history": _frame_summary(frames["factor_history"], tail=max(260, lookback_days)),
        "pit_financials": pit_financials,
        "technical": technical_summary(frames["price"], frames.get("price_change_rate")),
    }


def section_writer_agents(*, plan: dict[str, Any], data: dict[str, Any], charts: dict[str, str]) -> dict[str, str]:
    specs = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    specs = [spec for spec in specs if str(spec.get("name") or "") not in DEFERRED_SECTIONS]
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
    capability = build_data_capability_inventory(data, charts)
    if not get_env("OPENAI_API_KEY"):
        return reconcile_validation_gaps(fallback, data, charts)
    try:
        validation = llm_json(
            "你是研报验证 Agent。只返回 JSON，不写 Markdown。"
            "你的任务是检查报告是否忠于已采集数据、是否遗漏应内嵌的重要图表、是否有应补充或应收敛的结论。"
            "你必须逐章节检查是否和目标股票直接相关；泛泛讲宏观、行业、市场或方法论但没有落到目标股票的数据、图表或结论的部分，必须要求改写。"
            "分析章节（量价与技术面、基本面与估值、资金与交易结构、综合风险）须采用结论先行结构："
            "小标题含判断、段首先结论、数字作证据、块末点明对目标股票的影响、章末有综合判断；"
            "若以日期/指标堆叠为主、缺少判断性表述，须在 section_feedback 中要求按《宏观利率背景》改写。"
            "禁止要求补充 Wind、新闻、券商预测、管理层指引等本系统未采集数据。"
            "务必阅读 data_capability_inventory：MACD/回撤/RSI 若已在 computed 中 available，不得写「未采集」；"
            "pit_financials 仅年报 q4，不得要求季度环比；capital_flow row_count=0 时可建议 refresh_data 重拉一次。",
            json.dumps(
                {
                    "plan": plan,
                    "target_stock": {
                        "order_book_id": data.get("order_book_id"),
                        "industry": data.get("industry"),
                    },
                    "data_inventory": _data_inventory(data),
                    "data_capability_inventory": capability,
                    "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
                    "local_chart_review": _chart_quality_review(data=data, charts=charts),
                    "local_stock_relevance_review": _stock_relevance_review(data=data, sections=sections),
                    "local_narrative_review": _section_narrative_review(sections=sections),
                    "section_writing_style": _SECTION_WRITING_STYLE,
                    "charts": charts,
                    "sections": sections,
                    "draft_markdown": draft_markdown[:14000],
                    "local_checks": fallback,
                },
                ensure_ascii=False,
            )[:22000]
            + "\n你可以通过 refinement_requests / agent_rerun_requests 要求系统循环重做其他 Agent。"
            "\nagent_rerun_requests 字段：refresh_data/refresh_charts/replan_charts_only/rerun_section_writers/rewrite_sections/sections_to_rewrite/lookback_days/reason。"
            "\n- refresh_data：仅当 data_capability_inventory 中某 collectable 数据源 empty 且可能重试时使用；"
            "refresh_charts：重跑 chart_need + 出图；replan_charts_only：正文变更后仅重算要不要图。"
            "\n如果图表低信息量、重复、量纲混乱或无法支撑正文结论，请在 chart_quality_review.delete/redraw 中列出，并把 refresh_charts 设为 true。"
            + "\n必须返回 score/action_items/section_feedback/unsupported_claims/missing_data_notes/data_gap_review/"
            "chart_quality_review/stock_relevance_review/refinement_requests/agent_rerun_requests/final_decision。"
            "\nscore 为 0-100；missing_data_notes 只列真实缺口，勿重复 computed 已 available 的指标。",
        )
        sanitized = _sanitize_validation(validation, fallback)
        return reconcile_validation_gaps(sanitized, data, charts)
    except Exception as exc:
        fallback["validator_error"] = f"{type(exc).__name__}: {exc}"
        return reconcile_validation_gaps(fallback, data, charts)


def revise_sections_with_validation(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any],
    only_sections: list[str] | None = None,
) -> dict[str, str]:
    feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
    action_items = validation.get("action_items") if isinstance(validation.get("action_items"), list) else []
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    narrative = validation.get("narrative_review") if isinstance(validation.get("narrative_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    has_narrative_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in narrative.values())
    if not get_env("OPENAI_API_KEY") or not (feedback or action_items or has_relevance_rewrite or has_narrative_rewrite):
        return sections
    revised = dict(sections)
    allowed = {str(name) for name in only_sections} if only_sections else None

    def _revise_one(name: str, content: str) -> str:
        if allowed is not None and name not in allowed:
            return content
        section_notes = _string_list(feedback.get(name))
        section_relevance = relevance.get(name) if isinstance(relevance.get(name), dict) else {}
        if section_relevance.get("decision") == "rewrite":
            section_notes.append(str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。"))
        section_narrative = narrative.get(name) if isinstance(narrative.get(name), dict) else {}
        if section_narrative.get("decision") == "rewrite":
            section_notes.append(str(section_narrative.get("reason") or "本节需要改为结论先行结构。"))
        if not section_notes and not action_items:
            return content
        prompt_data = _compact_data_for_prompt(data, charts, name)
        try:
            text = llm_text(
                f"你是 revise_agent。请根据验证 Agent 的意见，重写《{name}》章节。"
                f"{_SECTION_WRITING_STYLE}"
                "只能使用 JSON 中已有数据；不要新增未采集来源；不要给买卖建议。"
                "需要更可追溯的数字表述；不要在正文写图表解读或 charts/ 路径，图表与图注由系统统一编排。"
                "不要写「数据局限」小节（报告末尾有《数据覆盖与局限》专章统一收录）。"
                "每一段都必须回到目标股票本身：引用目标股票代码、目标股票的米筐数据字段或目标股票对应行业归属。"
                "如果原文有泛泛讲宏观、行业、市场或方法论但没有连接目标股票的句子，请删除或改写。"
                "如果原文以数字/日期堆叠为主，请改为结论先行：先判断、后证据、块末影响、章末综合判断。"
                "直接输出 Markdown 正文，不要开场白、不要复述验证意见、不要写「好的，这是…」。"
                "不要写 charts/ 路径、不要写「请参考图表」或正文内嵌图注。"
                "分段落、用小标题或 bullet 组织，不要一大段连在一起。",
                json.dumps(
                    {
                        "section_name": name,
                        "original_section": content,
                        "section_feedback": section_notes,
                        "stock_relevance_feedback": section_relevance,
                        "narrative_feedback": section_narrative,
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
    sections: dict[str, str],
    validation: dict[str, Any],
    order_book_id: str,
    stock_code: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    chart_output_dir: Path,
    markdown_base: Path,
    chart_meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any]]:
    """Allow one bounded data/chart retry after the validator sees the draft."""
    chart_meta = chart_meta or {}
    requests = _refinement_requests(validation)
    if not requests:
        chart_review = _chart_quality_review(data=data, charts=charts)
        charts = _prune_charts(charts, chart_review)
        validation["chart_quality_review"] = chart_review
        return data, charts, validation, chart_meta
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
        charts, chart_meta = dynamic_chart_pipeline(
            data=data,
            sections=sections,
            output_dir=chart_output_dir,
            plan=plan,
            markdown_base=markdown_base,
            validation=validation,
            chart_agent_fn=chart_agent,
        )
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
    return data, charts, validation, chart_meta


def run_validation_cycle(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
    order_book_id: str,
    stock_code: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    chart_output_dir: Path,
    markdown_base: Path,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any]]:
    """验证 Agent 驱动多轮循环；出图在章节写作之后按需执行。"""
    max_rounds = _get_validation_max_rounds()
    validation_history: list[dict[str, Any]] = []
    validation: dict[str, Any] = {}
    chart_meta: dict[str, Any] = {}

    for round_idx in range(max_rounds):
        draft_summary = _local_executive_summary(plan=plan, data=data, sections=sections)
        draft_markdown = render_multi_markdown(
            summary=draft_summary,
            plan=plan,
            data=data,
            charts=chart_meta.get("charts") or {},
            sections=sections,
            inline_charts=False,
        )
        validation = validation_agent(
            plan=plan,
            data=data,
            charts=chart_meta.get("charts") or {},
            sections=sections,
            draft_markdown=draft_markdown,
        )
        validation["round"] = round_idx + 1
        validation_history.append(
            {
                "round": round_idx + 1,
                "score": validation.get("score"),
                "final_decision": validation.get("final_decision"),
                "action_items": _string_list(validation.get("action_items"))[:6],
            }
        )

        if validation_passed(validation):
            break

        actions = _agent_rerun_requests(validation)
        if not actions:
            break

        performed: dict[str, Any] = {"round": round_idx + 1, "reason": actions.get("reason")}
        next_lookback = max(lookback_days, int(actions.get("lookback_days") or lookback_days))
        sections_changed = False

        if actions.get("refresh_data") or actions.get("refresh_charts"):
            validation = _merge_rerun_into_validation(validation, actions)
            data, charts, validation, chart_meta = refinement_loop(
                plan=plan,
                data=data,
                charts=chart_meta.get("charts") or {},
                sections=sections,
                validation=validation,
                order_book_id=order_book_id,
                stock_code=stock_code,
                as_of=as_of,
                lookback_days=next_lookback,
                output_dir=output_dir,
                chart_output_dir=chart_output_dir,
                markdown_base=markdown_base,
                chart_meta=chart_meta,
            )
            chart_meta["charts"] = charts
            performed["refresh_data"] = bool(actions.get("refresh_data"))
            performed["refresh_charts"] = bool(actions.get("refresh_charts"))

        if actions.get("rerun_section_writers"):
            sections = section_writer_agents(plan=plan, data=data, charts={})
            performed["rerun_section_writers"] = True
            sections_changed = True
        elif actions.get("rewrite_sections"):
            target_sections = actions.get("sections_to_rewrite")
            sections = revise_sections_with_validation(
                plan=plan,
                data=data,
                charts=chart_meta.get("charts") or {},
                sections=sections,
                validation=validation,
                only_sections=target_sections,
            )
            performed["rewrite_sections"] = True
            performed["sections_to_rewrite"] = target_sections
            sections_changed = True
        elif _should_revise(validation):
            sections = revise_sections_with_validation(
                plan=plan,
                data=data,
                charts=chart_meta.get("charts") or {},
                sections=sections,
                validation=validation,
            )
            performed["rewrite_sections"] = True
            sections_changed = True

        if sections_changed and (actions.get("replan_charts_only") or not actions.get("refresh_charts")):
            charts, replan_meta = dynamic_chart_pipeline(
                data=data,
                sections=sections,
                output_dir=chart_output_dir,
                plan=plan,
                markdown_base=markdown_base,
                validation=validation,
                chart_agent_fn=chart_agent,
                prior_need=chart_meta.get("need"),
                replan_only=bool(actions.get("replan_charts_only")),
            )
            chart_meta.update(replan_meta)
            chart_meta["charts"] = charts
            performed["replan_charts_only"] = bool(actions.get("replan_charts_only"))

        validation.setdefault("iteration_history", []).append(performed)
        lookback_days = next_lookback

        if round_idx + 1 >= max_rounds:
            break

    if not chart_meta.get("charts"):
        charts, chart_meta = dynamic_chart_pipeline(
            data=data,
            sections=sections,
            output_dir=chart_output_dir,
            plan=plan,
            markdown_base=markdown_base,
            validation=validation,
            chart_agent_fn=chart_agent,
        )
        chart_meta["charts"] = charts

    validation["validation_history"] = validation_history
    validation["chart_need"] = chart_meta.get("need")
    validation = reconcile_validation_gaps(validation, data, chart_meta.get("charts") or {})
    sections = {name: normalize_section_text(content, name) for name, content in sections.items()}
    return data, sections, validation, chart_meta


def chart_placement_with_validation(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
    chart_need: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """图表编排 + 多轮验证：重点匹配正文内容与图标题含义。"""
    validation = validation or {}
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    blocked = {str(name) for name in delete}

    need_seed = build_placement_from_chart_need(chart_need, charts) if chart_need else None
    if need_seed and need_seed.get("placements"):
        placement = fill_missing_section_placements(
            need_seed, charts=charts, sections=sections, blocked=blocked
        )
        placement = flatten_chart_placements(placement)
    else:
        placement = chart_placement_agent(
            plan=plan, data=data, charts=charts, sections=sections, validation=validation, blocked=blocked
        )
    review_history: list[dict[str, Any]] = []
    max_rounds = _get_chart_placement_max_rounds()

    for round_idx in range(max_rounds):
        review = chart_placement_validation_agent(
            placement=placement,
            sections=sections,
            charts=charts,
            plan=plan,
            data=data,
        )
        review["round"] = round_idx + 1
        review_history.append(review)
        if review.get("passed") or review.get("final_decision") == "pass":
            break
        previous = json.dumps(placement.get("placements") or [], ensure_ascii=False, sort_keys=True)
        placement = apply_chart_placement_fixes(
            placement, review, sections=sections, charts=charts, blocked=blocked
        )
        placement = fill_missing_section_placements(
            placement, charts=charts, sections=sections, blocked=blocked
        )
        placement = flatten_chart_placements(placement)
        if json.dumps(placement.get("placements") or [], ensure_ascii=False, sort_keys=True) == previous:
            break
        if round_idx + 1 < max_rounds and get_env("OPENAI_API_KEY"):
            placement = chart_placement_agent(
                plan=plan,
                data=data,
                charts=charts,
                sections=sections,
                validation=validation,
                blocked=blocked,
                prior_review=review,
            )

    placement["placement_validation_history"] = review_history
    placement["placement_validation_passed"] = bool(review_history and review_history[-1].get("passed"))
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    blocked = {str(name) for name in delete}
    return finalize_inline_only_placement(
        placement, charts=charts, sections=sections, blocked=blocked
    )


def chart_placement_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
    blocked: set[str] | None = None,
    prior_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validation or {}
    if blocked is None:
        chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
        delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
        blocked = {str(name) for name in delete}

    fallback = build_default_chart_placement(charts=charts, sections=sections, blocked=blocked)
    fallback = fill_missing_section_placements(fallback, charts=charts, sections=sections, blocked=blocked)
    fallback = flatten_chart_placements(fallback)

    if not get_env("OPENAI_API_KEY"):
        return fallback

    section_structure = extract_section_structure(sections)
    chart_catalog = build_chart_catalog(charts, blocked)
    if not chart_catalog:
        return fallback

    try:
        result = llm_json(
            "你是研报图表编排 Agent。只返回 JSON，不写 Markdown。"
            "任务：为每张可用图表选择最匹配的章节与小节，使图标题含义与正文内容一致。"
            "每张图单独一条 placement；charts 数组只能含 1 个 chart_name。"
            "anchor 必须是该章节正文中真实出现的 #### 小节标题关键词或正文短语，用于精确定位插入位置。"
            "优先匹配：图标题/keywords 与 #### 小节标题或相邻段落主题一致；不要把回撤图放在价格走势段、不要把均线图放在宏观利率段。"
            "blocked_charts 禁止使用；每张图必须嵌入正文章节，无法匹配正文的图应列入 omitted，禁止附录或独立图表章节。",
            json.dumps(
                {
                    "plan_sections": [item.get("name") for item in plan.get("sections") or [] if isinstance(item, dict)],
                    "section_structure": section_structure,
                    "chart_catalog": chart_catalog,
                    "prior_review": prior_review,
                    "blocked_charts": sorted(blocked),
                    "target_stock": data.get("order_book_id"),
                },
                ensure_ascii=False,
            )[:20000]
            + '\n返回：{"placements":[{"section":"章节名","charts":["单张图key"],"anchor":"小节标题或正文关键词","note":null}],'
            + '"omitted":["刻意不嵌入的chart_key"]}',
        )
        normalized = normalize_chart_placement(result, charts=charts, sections=sections, blocked=blocked)
        normalized = flatten_chart_placements(normalized)
        if not normalized.get("placements"):
            return fallback
        return fill_missing_section_placements(
            normalized, charts=charts, sections=sections, blocked=blocked
        )
    except Exception as exc:
        fallback["placement_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


def chart_placement_validation_agent(
    *,
    placement: dict[str, Any],
    sections: dict[str, str],
    charts: dict[str, str],
    plan: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    fallback = local_chart_placement_review(placement, sections=sections, charts=charts)
    if not get_env("OPENAI_API_KEY"):
        return fallback

    structure = extract_section_structure(sections)
    placements_brief = []
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        for chart_name in item.get("charts") or []:
            placements_brief.append(
                {
                    "chart": chart_name,
                    "caption": CHART_CAPTIONS.get(str(chart_name), str(chart_name)),
                    "section": item.get("section"),
                    "anchor": item.get("anchor"),
                }
            )

    try:
        review = llm_json(
            "你是图表编排验证 Agent。只返回 JSON。"
            "逐张检查：图标题/含义是否与目标章节及 anchor 所指正文段落一致。"
            "不匹配时给出 suggested_section（必须是已有章节名）与 suggested_anchor（须能在该章节正文找到）。"
            "passed=true 仅当全部 placement 语义匹配；final_decision 为 pass 或 revise。",
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "section_structure": structure,
                    "placements": placements_brief,
                    "local_review": fallback,
                },
                ensure_ascii=False,
            )[:18000]
            + '\n返回：{"passed":bool,"score":0-100,"final_decision":"pass|revise",'
            + '"issues":[{"chart":"key","caption":"标题","section":"章节","anchor":"原anchor",'
            + '"problem":"原因","suggested_section":"章节","suggested_anchor":"关键词"}]}',
        )
        merged = dict(fallback)
        if isinstance(review, dict):
            llm_issues = review.get("issues") if isinstance(review.get("issues"), list) else []
            local_issues = fallback.get("issues") if isinstance(fallback.get("issues"), list) else []
            merged["issues"] = _merge_chart_placement_issues(local_issues, llm_issues)
            merged["score"] = int(safe_float(review.get("score")) or fallback.get("score") or 0)
            merged["passed"] = not merged["issues"] and bool(review.get("passed", fallback.get("passed")))
            merged["final_decision"] = "pass" if merged["passed"] else "revise"
        return merged
    except Exception as exc:
        fallback["validator_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


def _charts_needing_figure_notes(placement: dict[str, Any], charts: dict[str, str]) -> list[str]:
    names: list[str] = []
    omitted = set(placement.get("omitted") or [])
    for item in placement.get("placements") or []:
        if not isinstance(item, dict):
            continue
        for name in item.get("charts") or []:
            if name in charts and name not in names and name not in omitted:
                names.append(str(name))
    return names


def chart_figure_notes_agent(
    *,
    data: dict[str, Any],
    charts: dict[str, str],
    chart_names: list[str] | None = None,
) -> dict[str, str]:
    """为每张图生成形态图注（规则提取，不依赖多模态）。"""
    from .chart_pattern import build_chart_pattern, chart_pattern_note

    names = [name for name in (chart_names or list(charts.keys())) if name in charts]
    if not names:
        return {}

    if not get_env("OPENAI_API_KEY"):
        return {name: chart_pattern_note(name, data) for name in names}

    chart_items = [
        {
            "chart_name": name,
            "caption": CHART_CAPTIONS.get(name, name.replace("_", " ")),
            "pattern": build_chart_pattern(name, data),
            "fallback_note": chart_pattern_note(name, data),
        }
        for name in names
    ]
    try:
        result = llm_json(
            "你是 chart_interpreter agent，为研报图表撰写图注。"
            "要求：只描述曲线/柱状/快照的形态与走势（如上行、下行、震荡、背离、强于基准、曲线陡峭等）；"
            "禁止出现具体数值、百分比、价格、倍数；每条 1 句；学术研报口吻；"
            "必须基于 JSON 中 pattern.shape 与 fallback_note，不得臆造与形态矛盾的方向；"
            "禁止写文件路径、禁止「请参考/见上图」等空泛引用；"
            "输出 JSON：{\"notes\": {\"chart_name\": \"图注正文\"}}，chart_name 必须与输入一致。",
            json.dumps({"order_book_id": data.get("order_book_id"), "charts": chart_items}, ensure_ascii=False)[
                :14000
            ],
        )
        raw_notes = result.get("notes") if isinstance(result.get("notes"), dict) else result
        notes: dict[str, str] = {}
        if isinstance(raw_notes, dict):
            for name in names:
                value = raw_notes.get(name)
                if value:
                    notes[name] = str(value).strip()
        for name in names:
            notes.setdefault(name, chart_pattern_note(name, data))
        return notes
    except Exception:
        return {name: chart_pattern_note(name, data) for name in names}


def synthesis_judgment_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
) -> str:
    if not get_env("OPENAI_API_KEY"):
        return _local_synthesis_judgment(plan=plan, data=data, sections=sections)
    try:
        text = llm_text(
            "你是 synthesis_judgment_writer。请写《综合判断》章节，将各分析维度交叉印证，形成一条主线叙事。"
            "禁止重复各章节的日度价格流水账；禁止写数据局限（另有《数据覆盖与局限》专章）；禁止买卖建议；禁止外部来源。"
            "结构固定：### 总体判断（2-3句）→ ### 跨维度对照（3-5条 bullet，格式 **维度A vs 维度B**：结论）"
            "→ ### 主要不确定性（2-3条）。只能使用 section_digest 与 JSON 中已有数据。",
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "technical": data.get("technical"),
                    "factor": data.get("factor"),
                    "industry": data.get("industry"),
                    "section_digest": section_digest(sections, plan),
                    "validation": validation,
                },
                ensure_ascii=False,
            )[:18000],
        )
        return normalize_section_text(text, SYNTHESIS_SECTION)
    except Exception:
        return _local_synthesis_judgment(plan=plan, data=data, sections=sections)


def _local_synthesis_judgment(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
) -> str:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    target = data.get("order_book_id", "目标标的")
    r20 = technical.get("return_20d")
    pe = factor.get("pe_ratio_ttm")
    growth = factor.get("net_profit_growth_ratio_ttm")
    lines = [
        "### 总体判断",
        "",
        f"{target} 在技术面（20 日收益 {r20 if r20 is not None else '—'}）与基本面（PE(TTM) {pe if pe is not None else '—'}、"
        f"净利润增速 {growth if growth is not None else '—'}）之间需对照阅读；以下对照基于各章已写结论的本地汇总。",
        "",
        "### 跨维度对照",
    ]
    for item in section_digest(sections, plan)[:4]:
        first = item["excerpt"].split("\n")[0].strip()[:80]
        if first:
            lines.append(f"- **{item['section']}**：{first}")
    lines.extend(
        [
            "",
            "### 主要不确定性",
            "- 缺少行业可比与历史估值分位，跨公司/跨周期判断需降级。",
            "- 部分数据源缺失时，相关维度结论仅作单点描述。",
        ]
    )
    return normalize_section_text("\n".join(lines), SYNTHESIS_SECTION)


def _executive_summary_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
    charts: dict[str, str] | None = None,
) -> str:
    if not get_env("OPENAI_API_KEY"):
        return normalize_executive_summary_gaps(
            _local_executive_summary(plan=plan, data=data, sections=sections, charts=charts)
        )
    try:
        text = llm_text(
            "你是最终汇总 Agent。只能基于输入 JSON、各分段结论及《综合判断》写执行摘要，不给买卖建议。"
            "禁止添加宏观、行业、新闻、Wind、券商预测、管理层指引等输入中不存在的信息。"
            "数据缺口：最多 3 条简述，每条只写缺口本身，不要在每条末尾写「详见《数据覆盖与局限》」；"
            "若本节有缺口，全部 bullet 写完后单独一行「详情见《数据覆盖与局限》」。"
            "输出格式：1 句核心结论；### 关键支撑（3-4 条 bullet）；### 主要风险（2-3 条 bullet）；"
            "### 数据缺口（0-3 条，与 data_capability_inventory 一致，勿把已计算的 MACD/回撤误报为未采集）。"
            "只输出 Markdown，不要 JSON、代码块或键值对。",
            json.dumps(
                {
                    "plan": plan,
                    "technical": data.get("technical"),
                    "factor": data.get("factor"),
                    "industry": data.get("industry"),
                    "validation": validation,
                    "sections": sections,
                    "data_capability_inventory": build_data_capability_inventory(data, charts or {}),
                },
                ensure_ascii=False,
            )[:18000],
        )
        return normalize_executive_summary_gaps(normalize_section_text(text, "执行摘要"))
    except Exception:
        return normalize_executive_summary_gaps(
            _local_executive_summary(plan=plan, data=data, sections=sections, charts=charts)
        )


def _local_executive_summary(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    sections: dict[str, str],
    charts: dict[str, str] | None = None,
) -> str:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    lines = [
        f"{data.get('order_book_id', '目标标的')} 多智能体研究已完成。",
        "",
        f"最新收盘价 {technical.get('latest_close', '—')}，20 日收益率 {technical.get('return_20d', '—')}；"
        f"PE(TTM) {factor.get('pe_ratio_ttm', '—')}。",
        "",
        "### 关键支撑",
    ]
    synthesis = normalize_section_text(sections.get(SYNTHESIS_SECTION, ""), SYNTHESIS_SECTION)
    if synthesis and synthesis != "_本节暂无可用内容。_":
        for line in synthesis.splitlines():
            if line.strip().startswith("- "):
                lines.append(line.strip())
                if sum(1 for x in lines if x.startswith("- ")) >= 3:
                    break
    else:
        for name in analysis_section_names(plan)[:3]:
            excerpt = normalize_section_text(sections.get(name, ""), name)
            if excerpt == "_本节暂无可用内容。_":
                continue
            first = excerpt.split("\n")[0].strip()[:60]
            if first:
                lines.append(f"- {name}：{first}")
    gap_review = build_data_gap_review(data, charts or {})
    gap_notes = [str(g.get("note") or "").strip() for g in gap_review.get("gaps", []) if g.get("note")]
    lines.extend(["", "### 数据缺口"])
    if gap_notes:
        for note in gap_notes[:3]:
            lines.append(f"- {note}")
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
    chart_placement = chart_placement_with_validation(
        plan=plan, data=data, charts=charts, sections=sections, validation=validation
    )
    chart_placement = finalize_inline_only_placement(
        chart_placement, charts=charts, sections=sections, blocked=set()
    )
    figure_note_charts = _charts_needing_figure_notes(chart_placement, charts)
    figure_notes = chart_figure_notes_agent(data=data, charts=charts, chart_names=figure_note_charts)
    sections, omitted_charts = apply_chart_placements(
        sections, charts, chart_placement, figure_notes=figure_notes, data=data
    )
    sections.pop(CHART_INTERPRETATION_SECTION, None)
    charts = prune_charts_dict(charts, omitted_charts)
    sections, limitation_notes = strip_all_section_limitations(sections)
    sections[SYNTHESIS_SECTION] = synthesis_judgment_agent(
        plan=plan, data=data, sections=sections, validation=validation
    )
    validation = reconcile_validation_gaps(validation, data, charts)
    sections[DATA_LIMITATIONS_SECTION] = build_unified_data_limitations(
        data, limitation_notes, validation, charts=charts
    )
    summary = normalize_executive_summary_gaps(
        _executive_summary_agent(
            plan=plan, data=data, sections=sections, validation=validation, charts=charts
        )
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
    if validation_passed(validation):
        return False
    feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
    action_items = _string_list(validation.get("action_items"))
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    has_feedback = any(_string_list(value) for value in feedback.values())
    return bool(has_feedback or action_items or has_relevance_rewrite)


_NO_DATA_LIMITATION_HINT = (
    "禁止在正文中写「数据局限」或 #### 数据局限 小节（统一收录于报告末尾《数据覆盖与局限》）。"
    "仅当某数据源 row_count=0 时可一句带过「该口径本次未采集」；"
    "technical 中已有 macd/macd_signal/latest_drawdown/max_drawdown/rsi14 时必须引用，勿写未采集。"
)

def _write_section(*, agent: str, section_name: str, data: dict[str, Any]) -> str:
    if section_name in DEFERRED_SECTIONS:
        return normalize_section_text("_本节由报告汇总阶段自动生成。_", section_name)
    if not get_env("OPENAI_API_KEY"):
        return normalize_section_text(
            f"{agent} 本地摘要：{section_name} 已基于可用数据完成。",
            section_name,
        )
    try:
        hint = SECTION_WRITER_HINTS.get(section_name, "")
        prompt = (
            f"你是 {agent}。请写研报中的《{section_name}》章节。"
            f"{_SECTION_WRITING_STYLE}"
            f"{hint}{_NO_DATA_LIMITATION_HINT}"
            "只能使用用户提供的 JSON 数据，不得补充外部来源、宏观、行业、新闻、Wind、券商预测或未采集信息。"
            "所有数值结论必须能从 JSON 中追溯。不要给买卖建议。"
            "输出 Markdown 正文：分段落、用小标题或 bullet 组织，不要一大段连在一起；"
            "优先用自然语言写结论与数值，避免「根据 xxx 数据」「xxx 字段」等元数据句式；"
            "确需引用米筐字段名时用反引号标注英文字段名即可，不要重复 quarter/2025q4 等口径说明。"
            "不要写 charts/ 路径、不要写「请参考图表」或正文图表解读（图表与图注由系统编排）。"
            "不要输出 JSON 或代码块。"
        )
        text = llm_text(
            prompt,
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


def _merge_industry_rows(l1: pd.DataFrame, l2: pd.DataFrame) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if not l1.empty:
        merged.update(_latest_row(l1))
    if not l2.empty:
        row = _latest_row(l2)
        merged["second_industry_code"] = row.get("second_industry_code") or row.get("industry_code")
        merged["second_industry_name"] = row.get("second_industry_name") or row.get("industry_name")
    return merged


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
    narrative_review = _section_narrative_review(sections=sections)
    gap_review = build_data_gap_review(data, charts)
    if len(charts) < 8:
        action_items.append(f"图表数量只有 {len(charts)} 张，建议补充到至少 8 张。")
    for name, reason in chart_review.get("delete", {}).items():
        action_items.append(f"图表 {name} 信息含量不足或量纲不合适，建议删除或重画：{reason}")
    for name, review in relevance_review.items():
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 与目标股票关联不足，需要改写：{review.get('reason')}")
    for name, review in narrative_review.items():
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 叙事结构需改写：{review.get('reason')}")
    missing_data_notes = [
        str(g.get("note") or "").strip()
        for g in gap_review.get("gaps", [])
        if g.get("note") and g.get("status") != "false_alarm"
    ]
    unsupported = []
    for token in ("Wind", "券商预测", "新闻", "管理层指引"):
        if token in draft_markdown:
            unsupported.append(token)
    refresh_data = bool(gap_review.get("refresh_data_recommended"))
    return {
        "score": 80 if not unsupported and len(charts) >= 8 else 65,
        "action_items": action_items + missing_data_notes,
        "section_feedback": {},
        "unsupported_claims": unsupported,
        "missing_data_notes": missing_data_notes,
        "data_gap_review": gap_review,
        "chart_quality_review": chart_review,
        "stock_relevance_review": relevance_review,
        "narrative_review": narrative_review,
        "final_decision": "revise" if action_items or unsupported or missing_data_notes else "pass",
        "refinement_requests": {
            "refresh_data": refresh_data,
            "refresh_charts": len(charts) < 8 or bool(chart_review.get("redraw")),
            "lookback_days": None,
            "reason": (
                "存在可重试的空数据源：" + ", ".join(gap_review.get("refresh_keys") or [])
                if refresh_data
                else ("图表数量不足或存在低质量图" if len(charts) < 8 or chart_review.get("redraw") else None)
            ),
        },
        "agent_rerun_requests": {
            "refresh_data": refresh_data,
            "refresh_charts": len(charts) < 8 or bool(chart_review.get("redraw")),
            "replan_charts_only": False,
            "rerun_section_writers": False,
            "rewrite_sections": bool(action_items),
            "sections_to_rewrite": sorted(
                {
                    name
                    for name, review in relevance_review.items()
                    if isinstance(review, dict) and review.get("decision") == "rewrite"
                }
                | {
                    name
                    for name, review in narrative_review.items()
                    if isinstance(review, dict) and review.get("decision") == "rewrite"
                }
            ),
            "lookback_days": None,
            "reason": "本地规则检测到需返工项" if action_items or missing_data_notes else None,
        },
    }


def _sanitize_validation(validation: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(validation) if isinstance(validation, dict) else {}
    result["score"] = int(safe_float(result.get("score")) or fallback["score"])
    result["action_items"] = _string_list(result.get("action_items")) or fallback["action_items"]
    result["unsupported_claims"] = _string_list(result.get("unsupported_claims"))
    result["missing_data_notes"] = _string_list(result.get("missing_data_notes"))
    chart_review = result.get("chart_quality_review")
    result["chart_quality_review"] = chart_review if isinstance(chart_review, dict) else fallback.get("chart_quality_review", {})
    relevance_review = result.get("stock_relevance_review")
    result["stock_relevance_review"] = relevance_review if isinstance(relevance_review, dict) else fallback.get("stock_relevance_review", {})
    narrative_review = result.get("narrative_review")
    result["narrative_review"] = narrative_review if isinstance(narrative_review, dict) else fallback.get("narrative_review", {})
    feedback = result.get("section_feedback")
    result["section_feedback"] = feedback if isinstance(feedback, dict) else {}
    decision = str(result.get("final_decision") or fallback["final_decision"]).lower()
    result["final_decision"] = decision if decision in {"pass", "revise", "block"} else "revise"
    requests = result.get("refinement_requests")
    result["refinement_requests"] = requests if isinstance(requests, dict) else fallback.get("refinement_requests", {})
    rerun = result.get("agent_rerun_requests")
    result["agent_rerun_requests"] = rerun if isinstance(rerun, dict) else fallback.get("agent_rerun_requests", {})
    return result


def _agent_rerun_requests(validation: dict[str, Any]) -> dict[str, Any]:
    """解析验证 Agent 触发的下游 Agent 重做指令。"""
    rerun = validation.get("agent_rerun_requests") if isinstance(validation.get("agent_rerun_requests"), dict) else {}
    refine = validation.get("refinement_requests") if isinstance(validation.get("refinement_requests"), dict) else {}
    action_text = " ".join(_string_list(validation.get("action_items")))

    refresh_data = bool(rerun.get("refresh_data") or refine.get("refresh_data"))
    refresh_charts = bool(rerun.get("refresh_charts") or refine.get("refresh_charts")) or "图表" in action_text
    replan_charts_only = bool(rerun.get("replan_charts_only"))
    rerun_section_writers = bool(rerun.get("rerun_section_writers"))
    rewrite_sections = bool(rerun.get("rewrite_sections"))

    sections_to_rewrite = _string_list(rerun.get("sections_to_rewrite"))
    if not sections_to_rewrite:
        feedback = validation.get("section_feedback") if isinstance(validation.get("section_feedback"), dict) else {}
        sections_to_rewrite = [name for name, notes in feedback.items() if _string_list(notes)]

    if not rewrite_sections and not rerun_section_writers and _should_revise(validation):
        rewrite_sections = True

    lookback_days = rerun.get("lookback_days") or refine.get("lookback_days")
    reason = str(rerun.get("reason") or refine.get("reason") or action_text[:160] or "").strip() or None

    if not any((refresh_data, refresh_charts, replan_charts_only, rerun_section_writers, rewrite_sections)):
        return {}

    return {
        "refresh_data": refresh_data,
        "refresh_charts": refresh_charts,
        "replan_charts_only": replan_charts_only,
        "rerun_section_writers": rerun_section_writers,
        "rewrite_sections": rewrite_sections,
        "sections_to_rewrite": sections_to_rewrite or None,
        "lookback_days": lookback_days,
        "reason": reason,
    }


def _merge_rerun_into_validation(validation: dict[str, Any], actions: dict[str, Any]) -> dict[str, Any]:
    merged = dict(validation)
    requests = dict(merged.get("refinement_requests") or {})
    requests["refresh_data"] = bool(actions.get("refresh_data"))
    requests["refresh_charts"] = bool(actions.get("refresh_charts"))
    requests["lookback_days"] = actions.get("lookback_days")
    requests["reason"] = actions.get("reason")
    merged["refinement_requests"] = requests
    rerun = dict(merged.get("agent_rerun_requests") or {})
    rerun.update(
        {
            k: actions.get(k)
            for k in (
                "refresh_data",
                "refresh_charts",
                "replan_charts_only",
                "rerun_section_writers",
                "rewrite_sections",
                "lookback_days",
                "reason",
            )
        }
    )
    if actions.get("sections_to_rewrite"):
        rerun["sections_to_rewrite"] = actions.get("sections_to_rewrite")
    merged["agent_rerun_requests"] = rerun
    return merged


def _merge_chart_placement_issues(local_issues: list[Any], llm_issues: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*local_issues, *llm_issues]:
        if not isinstance(item, dict):
            continue
        chart = str(item.get("chart") or "").strip()
        if not chart:
            continue
        current = merged.get(chart, {})
        current.update({k: v for k, v in item.items() if v not in (None, "")})
        merged[chart] = current
    return list(merged.values())


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
        validation["score"] = max(int(safe_float(validation.get("score")) or 0), 85)


def _section_narrative_review(*, sections: dict[str, str]) -> dict[str, Any]:
    """检测分析章节是否符合结论先行结构（对标《宏观利率背景》）。"""
    judgment_re = re.compile(
        r"构成|显示|表明|支撑|压力|偏弱|偏强|走弱|走强|分化|格局|意味着|反映|暗示|"
        r"总体|综合判断|结论|边际|提供|抬升|下行|上行|背离|修复|承压|净流入|净流出"
    )
    impact_re = re.compile(r"\*\*对[^*]{0,48}影响\*\*|###\s*综合判断")
    colon_heading_re = re.compile(r"^###\s*.+：.+", re.MULTILINE)
    date_re = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}")
    review: dict[str, Any] = {}
    for name, content in sections.items():
        if name not in _NARRATIVE_SECTIONS:
            continue
        text = str(content or "").strip()
        if len(text) < 120:
            continue
        judgments = len(judgment_re.findall(text))
        impacts = len(impact_re.findall(text))
        dates = len(date_re.findall(text))
        colon_headings = len(colon_heading_re.findall(text))
        has_synthesis = "### 综合判断" in text
        issues: list[str] = []
        if judgments < 2:
            issues.append("判断性表述不足")
        if impacts < 1 and not has_synthesis:
            issues.append("缺少「对目标股票的影响」或章末综合判断")
        if dates >= 4 and judgments < max(3, dates // 2):
            issues.append("日期/数字堆叠过多，结论先行不足")
        if colon_headings < 1 and name != RISK_SECTION:
            issues.append("小标题未采用「主题：判断」格式")
        if issues:
            review[name] = {
                "decision": "rewrite",
                "reason": "；".join(issues) + "。请参照《宏观利率背景》采用结论先行结构。",
            }
        else:
            review[name] = {"decision": "pass", "reason": "叙事结构符合结论先行要求。"}
    return review


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
    narrative = validation.get("narrative_review") if isinstance(validation.get("narrative_review"), dict) else {}
    for name, review in list(narrative.items())[:8]:
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            lines.append(f"- 叙事结构：{name} 需要改写，原因：{review.get('reason')}")
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
    MARKET_TECH_SECTION: ("technical", "price_recent", "price_change_rate_recent", "turnover_recent", "index_benchmark_recent", "charts"),
    "基本面与估值": ("factor", "industry", "pit_financials", "dividend_recent", "shares_recent", "charts"),
    "资金与交易结构": ("capital_flow", "securities_margin_recent", "block_trade_recent", "charts"),
    "宏观利率背景": ("macro_rate_recent", "charts"),
    RISK_SECTION: ("status_checks", "technical", "factor", "industry", "pit_financials", "charts"),
}

SECTION_WRITER_HINTS: dict[str, str] = {
    MARKET_TECH_SECTION: (
        "本章合并量价与技术，须按固定小节组织，禁止重复描述同一走势或同一指标。"
        "每节遵循结论先行："
        "（1）### 近期价格与量价：主题句概括短期走势（如震荡下行后反弹、量价是否配合），"
        "再用 2-4 条 bullet 列关键价位/量/换手，禁止逐日流水账；"
        "（2）### 均线与区间收益：先判断多空格局（如价在 MA20 下、MA60 上），再列 MA 与 return_20d/return_60d；"
        "（3）### 动量与风险指标：先给动能总判断（偏弱/修复/背离），再列 technical 中的 rsi14、macd、macd_signal、latest_drawdown、max_drawdown；"
        "禁止写「MACD/回撤未采集」。章末 ### 综合判断 收束短中长期含义。"
    ),
    "基本面与估值": (
        "按 ### 估值倍数、### 盈利与增长、### 财务健康 组织。"
        "每节首句给出总判断（如估值中等、盈利高增、现金流覆盖良好），再用 bullet 列关键倍数/增速；"
        "禁止罗列全部年份流水账，只保留最有说明力的 2-3 个对比点；"
        "每个主题块末尾点明对目标股票估值或信用含义。章末 ### 综合判断。"
    ),
    "资金与交易结构": (
        "按 ### 两融资金、### 大宗交易 组织；若 capital_flow row_count=0，单独 ### 资金流向 一句说明未采集即可。"
        "每节首句给出结论（如杠杆净流入、机构分歧、大单减持），bullet 仅作证据；"
        "禁止先列逐笔交易再总结。章末 ### 综合判断 概括资金面对价格含义。"
    ),
    "宏观利率背景": (
        "本章为结论先行范本：小标题含判断、段首先结论、数字作证据、块末 **对目标股票的影响**、章末 ### 综合判断。"
        "必须说明利率/收益率变动如何作用于目标股票的融资成本或估值折现率，禁止脱离标的的宏观教科书式叙述。"
    ),
    RISK_SECTION: (
        "开篇 1-2 句给出总体风险画像，再按 ### 小标题分类（如交易状态、估值、盈利波动、技术面）；"
        "每条风险用「判断 + 关键数字」表述，禁止逐指标复述 technical 或 pit_financials 清单；"
        "禁止重复《综合判断》的跨维度对照。章末可 ### 综合判断 列出最需关注的 2-3 个风险。"
    ),
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
        "index_benchmark_recent": data.get("index_benchmark", {}).get("rows", [])[-12:],
        "securities_margin_recent": data.get("securities_margin", {}).get("rows", [])[-12:],
        "block_trade_recent": data.get("block_trade", {}).get("rows", [])[-8:],
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
    key_to_tool = {**DATA_KEY_TO_TOOL, "pit_financials": "get_pit_financials_ex"}
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
