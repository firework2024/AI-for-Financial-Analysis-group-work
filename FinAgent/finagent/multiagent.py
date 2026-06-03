from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .stock_utils import default_as_of, normalize_stock_code, resolve_as_of, to_order_book_id
from .concurrency import env_flag, finagent_max_workers, parallel_map
from .env import get_env, load_dotenv
from .llm import llm_json, llm_text
from .chart_catalog import MARKET_TECH_SECTION
from .multi_report import (
    apply_chart_placements,
    apply_chart_placements_agent,
    build_multi_json_payload,
    multi_report_display_title,
    render_multi_html,
    render_multi_markdown,
    resolve_multi_report_title,
)
from .narrative_plan import (
    build_plan_data_briefing,
    data_briefing_planner_preamble,
    is_operating_quality_section,
)
from .visual_placement import resolve_section_visuals
from .report_format import normalize_section_text, normalize_sections, section_writing_style_hint
from .report_writing import (
    analytical_writing_core,
    build_analytical_evidence,
    fundamental_narrative_system_prompt,
    section_opening_conclusion_rule,
    summarize_annual_financial_data,
)
from .rqdata_client import _init_rqdata
from .chart_plots import chart_agent
from .latex_exporter import export_latex
from .peer_analysis import (
    FACTOR_LABELS,
    PEER_FACTOR_CANDIDATES,
    _dedupe,
    fetch_industry_comparison,
)
from .plan_execution import sanitize_plan_sections
import re

OPERATING_QUALITY_SECTION = "经营质量分析"

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
    {"name": MARKET_TECH_SECTION, "agent": "market_tech_writer", "data": ["get_price", "get_price_change_rate", "get_turnover_rate"]},
    {"name": OPERATING_QUALITY_SECTION, "agent": "fundamental_writer", "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares"]},
    {"name": "资金与交易结构", "agent": "capital_flow_writer", "data": ["get_capital_flow", "get_securities_margin"]},
    {"name": "宏观利率背景", "agent": "macro_rate_writer", "data": ["get_interbank_offered_rate", "get_yield_curve"]},
    {"name": "综合风险与数据局限", "agent": "risk_synthesis_writer", "data": ["all_collected_data", "is_suspended", "is_st_stock"]},
]


FACTOR_CANDIDATES = [
    "market_cap",
    "pe_ratio_ttm",
    "pb_ratio_ttm",
    "ps_ratio_ttm",
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
    "dividend_yield_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "operating_revenue_growth_ratio_ttm",
    "account_receivable_turnover_rate_ttm",
    "current_asset_turnover_ttm",
    *PEER_FACTOR_CANDIDATES,
]

CHART_QUALITY_REQUIREMENTS = [
    "每张图必须回答一个明确的分析问题，不画冗余或纯信息重复的图。",
    "同一种分析视角只保留最有解释力的一张图（例如价格走势用均线图就够了，无需同时画价格+收益）。",
    "优先使用能同时展示多个相关指标趋势的图表（如双轴图：股价 vs 资金流、PE vs 利润增速）。",
    "对于财务指标，尽量展示 3~5 年历史趋势并标注 CAGR 或近两年变动幅度。",
    "对于估值指标（PE/PB/PS），若数据充足应叠加历史百分位带（如 30%/70% 分位线），否则应在正文说明缺乏历史对比。",
    "不同量纲的指标禁止堆在同一柱状图；如需对比，可拆分为子图或使用双轴（左轴市值/右轴比率）。",
    "柱状图适用于离散事件（分红、股本变动）或少量分类对比；趋势数据优先用折线图。",
    "宏观利率图（Shibor、国债收益率）必须与目标股票的估值逻辑挂钩（如 DCF 折现率、股息率利差），否则不单独成图。",
    "自由现金流应搭配资本开支共同展示，以判断扩张效率。",
    "ROE 允许用杜邦分解图（净利率×周转率×权益乘数）替代单柱。",
    "两融余额图应同时展示融资余额与融券余额（双轴），突出杠杆结构。",
    "行业对比图必须同时显示目标股票与行业中位数/均值，不能只画个股绝对值。"
]


@dataclass
class MultiAgentOptions:
    stock: str
    as_of: str | None = None
    lookback_days: int = 260
    output: str | None = None
    workdir: str = "."
    use_cached_only: bool = False
    force_refresh: bool = False


def run_multi_agent(options: MultiAgentOptions) -> dict[str, Any]:
    from .progress import step, info, ok, warn, section, sub_section, data_table

    load_dotenv()
    root = Path(options.workdir)
    output_path = Path(options.output) if options.output else root / "outputs" / f"{normalize_stock_code(options.stock)}_multi_agent_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_as_of = default_as_of(options.as_of)
    as_of_date = resolve_as_of(options.as_of)
    stock_code = normalize_stock_code(options.stock)
    order_book_id = to_order_book_id(stock_code)

    section("多智能体研究报告流程")
    info(f"股票代码: {stock_code} → 米筐合约: {order_book_id}")
    if raw_as_of != as_of_date:
        info(f"截止日期: {raw_as_of} 非交易日，已按最近工作日取 {as_of_date}")
    else:
        info(f"截止日期: {as_of_date}")
    info(f"回看天数: {options.lookback_days}")

    try:
        from .chat.data_ingest import ensure_report_data_for_generation

        prep = ensure_report_data_for_generation(
            stock_code,
            lookback_days=options.lookback_days,
            workdir=root,
            use_cached_only=options.use_cached_only,
            force_refresh=options.force_refresh,
        )
        if prep.get("message") and not prep.get("skipped"):
            info(f"报告数据预检: {prep['message']}")
    except Exception as exc:
        from .chat.data_ingest import AnnualCacheError
        from .datastore.market_cache import MarketCacheError

        if isinstance(exc, (AnnualCacheError, MarketCacheError)):
            raise
        warn(f"报告数据预入库跳过: {type(exc).__name__}: {exc}")

    # ── 第 1 步：数据采集 ──
    section("步骤 1/8：数据执行 Agent — 采集米筐数据")
    step("初始化 RQData 并拉取全量数据")
    data = data_executor_agent(
        order_book_id=order_book_id,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        output_dir=output_path.parent,
        workdir=root,
        use_cached_only=options.use_cached_only,
        force_refresh=options.force_refresh,
    )
    sec_name = data.get("sec_name", "")
    info(f"公司名称: {sec_name or '（未获取）'}")
    info(f"数据区间: {data.get('start_date')} → {data.get('end_date')}")

    # 打印各数据集行数
    data_inventory = [
        ("量价行情", data.get("price", {}).get("row_count", 0)),
        ("日涨跌幅", data.get("price_change_rate", {}).get("row_count", 0)),
        ("换手率", data.get("turnover", {}).get("row_count", 0)),
        ("资金流向", data.get("capital_flow", {}).get("row_count", 0)),
        ("融资融券", data.get("securities_margin", {}).get("row_count", 0)),
        ("分红方案", data.get("dividend", {}).get("row_count", 0)),
        ("股本结构", data.get("shares", {}).get("row_count", 0)),
        ("估值因子", data.get("factor", {}).get("row_count", 0) if isinstance(data.get("factor"), dict) else "N/A"),
        ("Shibor", data.get("interbank_rate", {}).get("row_count", 0)),
        ("收益率曲线", data.get("yield_curve", {}).get("row_count", 0)),
    ]
    data_table(["数据集", "记录数"], [[name, str(count)] for name, count in data_inventory])

    industry = data.get("industry", {})
    if industry:
        info(f"行业归属: {industry}")

    technical = data.get("technical", {})
    if technical:
        info(f"最新收盘价: {technical.get('latest_close')}")
        info(f"20日收益: {technical.get('return_20d')}, 60日收益: {technical.get('return_60d')}")
        info(f"MA20: {technical.get('ma20')}, MA60: {technical.get('ma60')}")
        info(f"RSI14: {technical.get('rsi14')}")

    pit = data.get("pit_financials", {})
    if pit:
        info(f"PIT 财务数据: {pit.get('row_count', 0)} 行, 最新报告期: {pit.get('report_year')}")

    # ── 第 2 步：数据驱动叙事规划 ──
    section("步骤 2/8：规划 Agent — 基于数据制定叙事与章节")
    plan = planner_agent(
        stock_code=stock_code,
        order_book_id=order_book_id,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        data=data,
    )
    report_title = resolve_multi_report_title(
        plan=plan,
        stock_code=stock_code,
        sec_name=str(sec_name or ""),
        suffix="多智能体研究报告",
    )
    objectives = str(plan.get("objective", ""))[:120]
    thesis = str(plan.get("narrative_thesis", ""))[:160]
    info(f"报告标题: {report_title}")
    if thesis:
        info(f"叙事主线: {thesis}")
    info(f"研究目标: {objectives}")
    tools = plan.get("tools", [])
    sections_spec = plan.get("sections", [])
    info(f"计划使用的米筐函数: {len(tools)} 个")
    info(f"计划生成的章节: {len(sections_spec)} 个")
    data_table(
        ["章节名称", "类型", "写作 Agent", "数据源"],
        [
            [
                s.get("name", ""),
                s.get("kind", ""),
                s.get("agent", ""),
                ", ".join(s.get("data", [])[:3]),
            ]
            for s in sections_spec
        ],
    )

    # ── 第 3 步：生成图表 ──
    section("步骤 3/8：图表 Agent — 生成可视化图表")
    chart_output_dir = output_path.parent / "charts" / output_path.stem
    step("执行 chart_agent", f"输出目录: {chart_output_dir}")
    chart_files = chart_agent(data=data, output_dir=chart_output_dir)
    charts = {name: _markdown_path(path, output_path.parent) for name, path in chart_files.items()}
    info(f"生成 {len(charts)} 张图表:")
    for name in charts:
        info(f"  └ {name}")
    if len(charts) < 8:
        warn(f"图表数量 ({len(charts)}) 不足 8 张，验证阶段可能要求补充")

    # ── 第 4 步：章节写作 ──
    section("步骤 4/8：章节写作 Agent — 各分段智能体并行写作")
    step("启动 section_writer_agents", f"共 {len(sections_spec)} 个章节")
    sections = section_writer_agents(plan=plan, data=data, charts=charts)
    for name, content in sections.items():
        info(f"  ✓ 《{name}》写作完成 ({len(content)} 字符)")

    # ── 第 5 步：生成草稿 ──
    section("步骤 5/8：渲染草稿 Markdown")
    draft_markdown = _render_draft_markdown(plan=plan, data=data, charts=charts, sections=sections)
    info(f"草稿长度: {len(draft_markdown)} 字符")

    # ── 第 6 步：验证 ──
    section("步骤 6/8：验证 Agent — 质量与一致性审查")
    step("执行 validation_agent")
    validation = validation_agent(plan=plan, data=data, charts=charts, sections=sections, draft_markdown=draft_markdown)
    score = validation.get("score", "N/A")
    decision = validation.get("final_decision", "N/A")
    info(f"验证评分: {score}/100")
    info(f"验证结论: {decision}")
    action_items = validation.get("action_items", [])
    if action_items:
        sub_section("验证修改建议")
        for item in action_items[:8]:
            info(f"  • {item}")
    unsupported = validation.get("unsupported_claims", [])
    if unsupported:
        warn(f"疑似未支撑表述: {unsupported[:3]}")
    structural = validation.get("structural_feedback", [])
    if structural:
        sub_section("结构反馈")
        for fb in structural[:5]:
            if isinstance(fb, dict):
                info(f"  [{fb.get('section', '?')}] {fb.get('issue', '')}: {fb.get('suggestion', '')[:100]}")

    # ── 精炼循环（数据/图表补采） ──
    section("步骤 6b/8：精炼循环 — 数据/图表补采（如需）")
    step("检查是否需要补充数据或图表")
    data, charts, validation = refinement_loop(
        plan=plan,
        data=data,
        charts=charts,
        validation=validation,
        order_book_id=order_book_id,
        as_of=as_of_date,
        lookback_days=options.lookback_days,
        output_dir=output_path.parent,
        chart_output_dir=chart_output_dir,
        use_cached_only=options.use_cached_only,
        force_refresh=options.force_refresh,
    )
    refined = validation.get("refinement_performed")
    if refined:
        info(f"补采数据: {refined.get('refresh_data')}, 补图: {refined.get('refresh_charts')}")
        info(f"原因: {refined.get('reason', '')[:120]}")
        if refined.get("refresh_charts"):
            ok(f"图表已更新为 {len(charts)} 张")
    else:
        info("无需补采，草稿质量合格")

    # ── 第 7 步：修订章节 ──
    section("步骤 7/8：修订 Agent — 根据验证反馈改写章节")
    step("执行 revise_sections_with_validation")
    sections = revise_sections_with_validation(plan=plan, data=data, charts=charts, sections=sections, validation=validation)
    for name, content in sections.items():
        info(f"  ✓ 《{name}》修订完成 ({len(content)} 字符)")

    # ── 第 8 步：组装最终报告 ──
    section("步骤 8/8：最终组装 — 生成 MD + HTML + JSON + LaTeX")
    step("生成执行摘要")
    final_markdown, payload = _assemble_multi_report(
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        validation=validation,
        output_path=output_path,
        json_path=output_path.with_suffix(".json"),
    )
    step("写入 Markdown", str(output_path))
    output_path.write_text(final_markdown, encoding="utf-8")
    ok(f"Markdown 报告已写入 ({output_path.stat().st_size} 字节)")

    step("写入 JSON", str(output_path.with_suffix(".json")))
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"JSON 数据已写入 ({json_path.stat().st_size} 字节)")

    payload["output_markdown"] = str(output_path)
    payload["output_json"] = str(json_path)
    payload["output_html"] = payload.get("meta", {}).get("output_html") or str(output_path.with_suffix(".html"))

    # 检查 HTML 是否存在
    html_path = payload["output_html"]
    if Path(html_path).exists():
        ok(f"HTML 报告已生成: {html_path}")

    if get_env("EXPORT_LATEX", "true").lower() == "true":
        from .latex_exporter import export_latex
        try:
            tex_path = output_path.with_suffix(".tex")
            compile_pdf = get_env("COMPILE_PDF", "false").lower() == "true"
            step("LaTeX 导出", f"编译 PDF: {compile_pdf}")
            export_latex(
                markdown_text=final_markdown,
                output_tex_path=tex_path,
                title=resolve_multi_report_title(
                    plan=plan,
                    stock_code=stock_code,
                    sec_name=str(data.get("sec_name") or ""),
                    suffix="多智能体研究报告",
                ),
                author="FinAgent",
                compile_pdf=compile_pdf,
            )
            payload["output_tex"] = str(tex_path)
            if compile_pdf:
                payload["output_pdf"] = str(tex_path.with_suffix(".pdf"))
            ok(f"LaTeX 导出完成: {tex_path}")
        except Exception as e:
            warn(f"LaTeX 导出失败: {e}")

    # 输出总结
    section("报告生成汇总")
    info(f"Markdown: {payload['output_markdown']}")
    info(f"HTML:     {payload['output_html']}")
    info(f"JSON:     {payload['output_json']}")
    if payload.get("output_tex"):
        info(f"LaTeX:    {payload['output_tex']}")
    if payload.get("output_pdf"):
        info(f"PDF:      {payload['output_pdf']}")
    info(f"图表:     {len(charts)} 张于 {chart_output_dir}/")

    return payload


def planner_agent(
    *,
    stock_code: str,
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = {
        "report_title": "",
        "narrative_thesis": "",
        "objective": "生成覆盖量价、基本面、资金流、技术因素的 A 股多智能体研究报告",
        "tools": list(TOOL_REGISTRY),
        "sections": DEFAULT_SECTIONS,
        "risk_controls": ["仅基于可取得数据写结论", "不输出买卖建议", "说明缺失数据"],
    }
    if not get_env("OPENAI_API_KEY"):
        return _sanitize_plan(fallback, fallback)
    briefing_block = ""
    if data:
        briefing = build_plan_data_briefing(data)
        briefing_block = (
            data_briefing_planner_preamble()
            + f"\n{json.dumps(briefing, ensure_ascii=False)[:8000]}"
        )
    try:
        plan = llm_json(
            "你是金融研究系统的计划 Agent。只返回 JSON，不要写 Markdown。",
            "请为 A 股研究报告制定多智能体执行计划。"
            f"\n股票: {stock_code} / {order_book_id}"
            f"\n截至日期: {as_of.isoformat()}，回看天数: {lookback_days}"
            f"\n可用米筐函数: {json.dumps(TOOL_REGISTRY, ensure_ascii=False)}"
            f"\n图表质量要求: {json.dumps(CHART_QUALITY_REQUIREMENTS, ensure_ascii=False)}"
            "\n必须返回 report_title, narrative_thesis, objective, tools, sections, risk_controls。"
            "\nreport_title: 中文定制标题（含公司简称或代码，体现本轮叙事，勿用泛化「多智能体报告」）。"
            "\nnarrative_thesis: 1-2 句主线（如「成长与估值错配」「资金驱动下的趋势延续」）。"
            "\nsections 每项包含 name, agent, data, kind, rationale。"
            "\n章节标题采用软引导：建议写成「类型：结论」结构（例如「量价趋势：中期上行但短期震荡」），"
            "保证标题本身先给判断，再在正文展开证据；这只是写作建议，不是硬性格式约束。"
            "\nkind 枚举: operating_quality|market|valuation|capital|macro|risk。"
            "\n需要 MD&A 深度经营分析时 kind=operating_quality（节名可自定义，不必叫「经营质量分析」）。"
            "\ndata 仅填可用米筐函数名；sections 可按研究重点自由规划章节名称与顺序。"
            "\n禁止规划宏观、行业、新闻、Wind、券商预测等未在可用函数中的数据。"
            + briefing_block,
        )
        return _sanitize_plan(plan, fallback)
    except Exception:
        return _sanitize_plan(fallback, fallback)


def _sanitize_plan(plan: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(plan) if isinstance(plan, dict) else {}
    allowed_tools = set(TOOL_REGISTRY)
    result["tools"] = [name for name in result.get("tools", []) if name in allowed_tools] or list(TOOL_REGISTRY)
    result["sections"] = sanitize_plan_sections(
        result,
        default_sections=DEFAULT_SECTIONS,
        allowed_tools=allowed_tools,
    )
    controls = result.get("risk_controls") if isinstance(result.get("risk_controls"), list) else []
    result["risk_controls"] = [
        *[str(item) for item in controls if str(item).strip()],
        "只能引用本系统实际采集的米筐数据与本地计算指标",
        "不得声称使用 Wind、行业调研、宏观数据、新闻或预测模型",
    ]
    result["report_title"] = str(result.get("report_title") or "").strip()[:120]
    result["narrative_thesis"] = str(result.get("narrative_thesis") or "").strip()[:400]
    result["objective"] = str(result.get("objective") or fallback["objective"])
    return result


def _read_instrument_symbol(instrument: Any) -> str:
    if instrument is None:
        return ""
    if isinstance(instrument, pd.DataFrame):
        if instrument.empty:
            return ""
        instrument = instrument.iloc[0]
    symbol = getattr(instrument, "symbol", None)
    if symbol is None and hasattr(instrument, "get"):
        symbol = instrument.get("symbol")
    return str(symbol or "").strip()


def _fetch_sec_name(rqdatac, order_book_id: str, stock_code: str) -> str:
    from .rqdata_quota import rqdata_quota_exhausted

    if rqdatac is not None and not rqdata_quota_exhausted():
        try:
            instrument = _safe_rq_call("instruments", lambda: rqdatac.instruments(order_book_id))
        except Exception:
            instrument = None
    else:
        instrument = None
    try:
        if instrument is not None:
            symbol = _read_instrument_symbol(instrument)
            if symbol and symbol != stock_code and not symbol.endswith((".XSHG", ".XSHE")):
                return symbol
    except Exception:
        pass
    try:
        from .datastore.db import get_annual_report

        annual = get_annual_report(stock_code)
        if annual and annual.get("sec_name"):
            return str(annual["sec_name"]).strip()
    except Exception:
        pass
    return ""


def _data_executor_eastmoney_fallback(
    *,
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """米筐额度用尽时：东方财富日 K + 现货估值，构建与 data_executor 兼容的载荷。"""
    from .chat.quote_sources import fetch_eastmoney_kline_series, fetch_eastmoney_quote
    from .progress import info
    from .stock_utils import calendar_trading_as_of

    stock_code = order_book_id.split(".")[0]
    info(f"量价数据：米筐不可用，改由东方财富拉取 {stock_code} 日 K（约 {lookback_days} 日）")
    rows = fetch_eastmoney_kline_series(stock_code, limit=max(30, lookback_days))
    if not rows:
        raise RuntimeError("米筐额度已用尽，且东方财富 K 线未返回数据，请稍后重试或先完成对话入库。")

    em = fetch_eastmoney_quote(stock_code)
    sec_name = str(em.get("name") or "").strip() or _fetch_sec_name(None, order_book_id, stock_code)
    end_date_str = str(rows[-1].get("date") or calendar_trading_as_of(as_of).isoformat())
    start_date_str = str(rows[0].get("date") or end_date_str)
    price_df = pd.DataFrame(rows)
    frames = {"price": _flatten_frame(price_df)}
    factor: dict[str, Any] = {}
    if em.get("pe_ttm") is not None:
        factor["pe_ratio_ttm"] = em.get("pe_ttm")
        factor["pe_ratio_ttm_source"] = "eastmoney"
    if em.get("pb") is not None:
        factor["pb_ratio_ttm"] = em.get("pb")
        factor["pb_ratio_ttm_source"] = "eastmoney"
    if em.get("market_cap") is not None:
        factor["market_cap"] = em.get("market_cap")
        factor["market_cap_source"] = "eastmoney"

    payload = {
        "order_book_id": order_book_id,
        "stock_code": stock_code,
        "sec_name": sec_name,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "source": "eastmoney_fallback",
        "rqdata_quota_fallback": True,
        "data_notes": [
            "米筐 API 额度已用尽；量价序列改由东方财富日 K 获取。",
            "两融、资金流向、宏观利率等米筐专属序列本报告可能缺失。",
        ],
        "tool_registry": TOOL_REGISTRY,
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
        "price": _frame_summary(frames["price"], tail=max(260, lookback_days)),
        "price_change_rate": {"rows": [], "row_count": 0, "columns": []},
        "turnover": {"rows": [], "row_count": 0, "columns": []},
        "capital_flow": {"rows": [], "row_count": 0, "net_buy_value_sum": None},
        "securities_margin": {"rows": [], "row_count": 0, "columns": []},
        "dividend": {"rows": [], "row_count": 0, "columns": []},
        "shares": {"rows": [], "row_count": 0, "columns": []},
        "suspended": {"rows": [], "row_count": 0, "columns": []},
        "st_stock": {"rows": [], "row_count": 0, "columns": []},
        "industry": {},
        "interbank_rate": {"rows": [], "row_count": 0, "columns": []},
        "yield_curve": {"rows": [], "row_count": 0, "columns": []},
        "factor": factor,
        "factor_history": {"rows": [], "row_count": 0, "columns": []},
        "industry_comparison": {
            "industry": {"source": "citics_2019", "selected_level": None},
            "peers": {
                "selected_level": None,
                "candidate_count": 0,
                "effective_count": 0,
                "order_book_ids": [],
                "sample_order_book_ids": [],
            },
            "metrics": {},
            "relative_signals": [],
            "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": "rqdata_quota"},
            "data_notes": ["行业对比依赖米筐，额度用尽时已跳过。"],
        },
        "technical": _technical_summary(frames["price"]),
    }
    _enrich_multi_factor_payload(payload, stock_code)
    from .datastore import persist_market_snapshot

    snapshot_id = persist_market_snapshot(payload, lookback_days=lookback_days, source="eastmoney_fallback")
    if snapshot_id is not None:
        payload["data_snapshot_id"] = snapshot_id
    _attach_stored_fundamentals(
        payload,
        stock_code,
        workdir=workdir or output_dir.parent,
        use_cached_only=False,
        force_refresh=False,
    )
    _enrich_multi_factor_payload(payload, stock_code)
    return payload


def data_executor_agent(
    *,
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    incremental_after: str | None = None,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    import rqdatac

    from .datastore.market_cache import MarketCacheError, load_executor_payload_from_snapshot, snapshot_usable_for_executor
    from .datastore.snapshot_merge import incremental_fetch_start

    stock_code = order_book_id.split(".")[0]

    def _finalize_cached_payload(cached: dict[str, Any], *, offline: bool) -> dict[str, Any]:
        from .progress import info

        if offline:
            info("量价数据：使用本地已入库序列（离线模式，不访问外网）")
            for note in cached.get("local_cache_warnings") or []:
                info(f"  · {note}")
        else:
            info("量价数据：使用本地 SQLite 已入库数据（跳过米筐拉取）")
        cached["tool_registry"] = TOOL_REGISTRY
        cached["chart_quality_requirements"] = CHART_QUALITY_REQUIREMENTS
        _ensure_technical_from_price_rows(cached)
        _enrich_multi_factor_payload(cached, stock_code)
        _attach_stored_fundamentals(
            cached,
            stock_code,
            workdir=workdir or output_dir.parent,
            use_cached_only=use_cached_only,
            force_refresh=force_refresh,
        )
        _enrich_multi_factor_payload(cached, stock_code)
        return cached

    if use_cached_only:
        if force_refresh:
            raise MarketCacheError("不能同时勾选「仅用本地数据」和「强制刷新外网数据」。")
        cached = load_executor_payload_from_snapshot(
            stock_code,
            lookback_days=lookback_days,
            relaxed=True,
            as_of=as_of,
        )
        if not cached:
            raise MarketCacheError(
                "本地没有已保存的报告级量价数据。"
                "请先在对话中对标的完成入库，或取消「仅用本地数据」。"
            )
        return _finalize_cached_payload(cached, offline=True)

    if not force_refresh:
        try:
            from .datastore.db import get_latest_snapshot

            snapshot = get_latest_snapshot(stock_code)
            if snapshot_usable_for_executor(snapshot, as_of=as_of, lookback_days=lookback_days):
                cached = load_executor_payload_from_snapshot(
                    stock_code,
                    lookback_days=lookback_days,
                    relaxed=False,
                    as_of=as_of,
                )
                if cached:
                    return _finalize_cached_payload(cached, offline=False)
        except MarketCacheError:
            raise
        except Exception as exc:
            print(f"[market_cache] load skipped: {type(exc).__name__}: {exc}")

    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted

    if rqdata_quota_exhausted():
        return _finalize_cached_payload(
            _data_executor_eastmoney_fallback(
                order_book_id=order_book_id,
                as_of=as_of,
                lookback_days=lookback_days,
                output_dir=output_dir,
                workdir=workdir,
            ),
            offline=False,
        )

    try:
        _init_rqdata(rqdatac)
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="data_executor.init")
            return _finalize_cached_payload(
                _data_executor_eastmoney_fallback(
                    order_book_id=order_book_id,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    output_dir=output_dir,
                    workdir=workdir,
                ),
                offline=False,
            )
        raise

    sec_name = _fetch_sec_name(rqdatac, order_book_id, stock_code)
    end_date = _previous_trading_date(rqdatac, as_of)
    start_date = incremental_fetch_start(
        end_date,
        lookback_days=lookback_days,
        last_end_date=incremental_after,
    )
    fundamentals_start = end_date - timedelta(days=730)
    macro_start = end_date - timedelta(days=120)
    try:
        available_factors = set(rqdatac.get_all_factor_names())
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="get_all_factor_names")
            return _finalize_cached_payload(
                _data_executor_eastmoney_fallback(
                    order_book_id=order_book_id,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    output_dir=output_dir,
                    workdir=workdir,
                ),
                offline=False,
            )
        available_factors = set()
    factors = list(dict.fromkeys(name for name in FACTOR_CANDIDATES if name in available_factors))

    rq_tasks: dict[str, Any] = {
        "price": lambda: rqdatac.get_price(
            order_book_id,
            start_date=start_date,
            end_date=end_date,
            frequency="1d",
            fields=["open", "high", "low", "close", "volume", "total_turnover"],
        ),
        "turnover": lambda: _safe_rq_call(
            "get_turnover_rate",
            lambda: rqdatac.get_turnover_rate(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "capital": lambda: _safe_rq_call(
            "get_capital_flow",
            lambda: rqdatac.get_capital_flow(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "price_change": lambda: _safe_rq_call(
            "get_price_change_rate",
            lambda: rqdatac.get_price_change_rate(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "margin": lambda: _safe_rq_call(
            "get_securities_margin",
            lambda: rqdatac.get_securities_margin(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "dividend": lambda: _safe_rq_call(
            "get_dividend",
            lambda: rqdatac.get_dividend(order_book_id, start_date=fundamentals_start, end_date=end_date),
        ),
        "shares": lambda: _safe_rq_call(
            "get_shares",
            lambda: rqdatac.get_shares(order_book_id, start_date=fundamentals_start, end_date=end_date),
        ),
        "suspended": lambda: _safe_rq_call(
            "is_suspended",
            lambda: rqdatac.is_suspended(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "st_stock": lambda: _safe_rq_call(
            "is_st_stock",
            lambda: rqdatac.is_st_stock(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "industry": lambda: _safe_rq_call(
            "get_instrument_industry",
            lambda: rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=1, date=end_date),
        ),
        "interbank_rate": lambda: _safe_rq_call(
            "get_interbank_offered_rate",
            lambda: rqdatac.get_interbank_offered_rate(start_date=macro_start, end_date=end_date),
        ),
        "yield_curve": lambda: _safe_rq_call(
            "get_yield_curve",
            lambda: rqdatac.get_yield_curve(start_date=macro_start, end_date=end_date),
        ),
    }
    if factors:
        rq_tasks["factor"] = lambda: rqdatac.get_factor(
            order_book_id, factors, start_date=end_date, end_date=end_date
        )
        rq_tasks["factor_history"] = lambda: rqdatac.get_factor(
            order_book_id, factors, start_date=start_date, end_date=end_date
        )

    rq_raw = parallel_map(
        rq_tasks,
        max_workers=finagent_max_workers(),
        parallel=env_flag("FINAGENT_RQDATA_PARALLEL", default=True),
    )

    def _rq_frame(key: str) -> pd.DataFrame:
        value = rq_raw.get(key)
        if isinstance(value, BaseException):
            print(f"[rqdatac] {key} skipped: {type(value).__name__}: {value}")
            return pd.DataFrame()
        if value is None:
            return pd.DataFrame()
        return value if isinstance(value, pd.DataFrame) else pd.DataFrame()

    price = _rq_frame("price")
    if (price.empty and rqdata_quota_exhausted()) or (
        isinstance(rq_raw.get("price"), BaseException) and is_rqdata_quota_error(rq_raw.get("price"))
    ):
        if isinstance(rq_raw.get("price"), BaseException):
            mark_rqdata_quota_exceeded(rq_raw.get("price"), where="price")
        return _finalize_cached_payload(
            _data_executor_eastmoney_fallback(
                order_book_id=order_book_id,
                as_of=as_of,
                lookback_days=lookback_days,
                output_dir=output_dir,
                workdir=workdir,
            ),
            offline=False,
        )
    turnover = _rq_frame("turnover")
    capital = _rq_frame("capital")
    price_change = _rq_frame("price_change")
    margin = _rq_frame("margin")
    dividend = _rq_frame("dividend")
    shares = _rq_frame("shares")
    suspended = _rq_frame("suspended")
    st_stock = _rq_frame("st_stock")
    industry = _rq_frame("industry")
    interbank_rate = _rq_frame("interbank_rate")
    yield_curve = _rq_frame("yield_curve")
    factor = _rq_frame("factor")
    factor_history = _rq_frame("factor_history")
    try:
        industry_comparison = fetch_industry_comparison(
            rqdatac,
            order_book_id=order_book_id,
            as_of=end_date,
            available_factors=available_factors,
        )
    except Exception as exc:
        print(f"[peer_analysis] industry comparison skipped: {type(exc).__name__}: {exc}")
        industry_comparison = {
            "industry": {"source": "citics_2019", "selected_level": None},
            "peers": {"selected_level": None, "candidate_count": 0, "effective_count": 0, "order_book_ids": [], "sample_order_book_ids": []},
            "metrics": {},
            "relative_signals": [],
            "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": str(exc)},
            "data_notes": [f"行业对比数据获取失败：{type(exc).__name__}: {exc}"],
        }

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
    }
    payload = {
        "order_book_id": order_book_id,
        "stock_code": stock_code,
        "sec_name": sec_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "tool_registry": TOOL_REGISTRY,
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
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
        "factor_history": _frame_summary(_flatten_frame(factor_history), tail=max(260, lookback_days)),
        "industry_comparison": industry_comparison,
        "technical": _technical_summary(frames["price"]),
    }
    _enrich_multi_factor_payload(payload, stock_code)
    from .datastore import persist_market_snapshot

    snapshot_id = persist_market_snapshot(payload, lookback_days=lookback_days, source="data_executor")
    if snapshot_id is not None:
        payload["data_snapshot_id"] = snapshot_id
    _attach_stored_fundamentals(
        payload,
        stock_code,
        workdir=workdir or output_dir.parent,
        use_cached_only=use_cached_only,
        force_refresh=force_refresh,
    )
    _enrich_multi_factor_payload(payload, stock_code)
    return payload


def _enrich_multi_factor_payload(payload: dict[str, Any], stock_code: str) -> None:
    """多智能体主路径复用对话侧教科书口径的本地估值补全。"""
    try:
        from .chat.data_tools import _apply_derived_financial_factors, _apply_derived_valuation
    except Exception as exc:
        print(f"[fundamentals] factor enrichment skipped: {type(exc).__name__}: {exc}")
        return

    factor = dict(payload.get("factor") or {})
    price_row = _latest_series_row(payload.get("price"))
    shares_row = _latest_series_row(payload.get("shares"))
    if factor.get("market_cap") is None:
        market_cap = _market_cap_from_rows(price_row, shares_row)
        if market_cap is not None:
            factor["market_cap"] = round(market_cap, 2)
            factor["market_cap_source"] = "derived_price_shares"

    factor = _apply_derived_financial_factors(
        factor,
        price_row,
        stock_code,
        technical=payload.get("technical") if isinstance(payload.get("technical"), dict) else None,
    )
    factor = _apply_derived_valuation(
        factor,
        price_row,
        stock_code,
        technical=payload.get("technical") if isinstance(payload.get("technical"), dict) else None,
    )
    if factor:
        payload["factor"] = factor

    history = payload.get("factor_history")
    rows = history.get("rows") if isinstance(history, dict) else None
    if isinstance(rows, list) and rows:
        latest = dict(rows[-1])
        latest.update({k: v for k, v in factor.items() if k not in latest or latest.get(k) is None})
        rows[-1] = latest
        columns = list(history.get("columns") or [])
        for key in latest:
            if key not in columns:
                columns.append(key)
        history["columns"] = columns


def _latest_series_row(summary: Any) -> dict[str, Any]:
    rows = summary.get("rows") if isinstance(summary, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[-1]
    return dict(row) if isinstance(row, dict) else {}


def _market_cap_from_rows(price_row: dict[str, Any], shares_row: dict[str, Any]) -> float | None:
    close = _safe_number(price_row.get("close"))
    shares = None
    for key in ("total", "total_shares", "total_a", "shares"):
        shares = _safe_number(shares_row.get(key))
        if shares and shares > 0:
            break
    if not close or close <= 0 or not shares or shares <= 0:
        return None
    return close * shares


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _attach_stored_fundamentals(
    payload: dict[str, Any],
    stock_code: str,
    *,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
) -> None:
    """挂载本地 SQLite 中的 PIT 财务与年报 MD&A，供经营质量章节深度分析。"""
    try:
        from .chat.data_ingest import AnnualCacheError, ensure_annual_report_in_store

        ensure_annual_report_in_store(
            stock_code,
            workdir=workdir,
            use_cached_only=use_cached_only,
            force_refresh=force_refresh,
        )
    except AnnualCacheError:
        raise
    except Exception as exc:
        print(f"[fundamentals] annual ensure skipped: {type(exc).__name__}: {exc}")

    annual = None
    try:
        from .datastore.db import get_annual_report, get_pit_financials, pit_cache_is_usable

        annual = get_annual_report(stock_code)
        pit = get_pit_financials(stock_code)
        if pit_cache_is_usable(pit):
            payload["pit_financials"] = {
                "rows": pit["rows"],
                "row_count": len(pit["rows"]),
                "report_year": pit.get("report_year"),
                "years": pit.get("years"),
            }
    except Exception as exc:
        print(f"[fundamentals] load cache skipped: {type(exc).__name__}: {exc}")

    if not payload.get("pit_financials"):
        if use_cached_only:
            # 仅用本地数据模式下，禁止触发任何外部财务拉取。
            pass
        else:
            try:
                from .stock_utils import default_as_of
                from .rqdata_client import fetch_financials

                report_year = int((annual or {}).get("report_year") or default_as_of(None).year)
                fetched = fetch_financials(stock_code, report_year, years=3)
                payload["pit_financials"] = {
                    "rows": fetched.rows,
                    "row_count": len(fetched.rows),
                    "report_year": report_year,
                    "years": 3,
                }
            except Exception as exc:
                print(f"[fundamentals] pit_financials fetch skipped: {type(exc).__name__}: {exc}")

    if use_cached_only and not payload.get("pit_financials") and annual:
        fin_rows = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
        if fin_rows:
            payload["pit_financials"] = {
                "rows": fin_rows,
                "row_count": len(fin_rows),
                "report_year": annual.get("report_year"),
                "years": len(fin_rows),
                "source": "annual_report_records",
            }

    if use_cached_only and not payload.get("pit_financials"):
        from .chat.data_ingest import AnnualCacheError

        raise AnnualCacheError(
            "本地没有已保存的财务序列或年报三表。"
            "请先在对话中完成入库，或取消「仅用本地数据」。"
        )

    if not annual:
        if use_cached_only:
            from .chat.data_ingest import AnnualCacheError

            raise AnnualCacheError(
                "本地没有已保存的年报数据。"
                "请先在对话中完成年报/PDF 入库，或取消「仅用本地数据」。"
            )
        return
    from .mda_analysis import build_annual_context_from_store

    # ── 加载年报上下文。multi-agent 路径不再额外生成基本面叙事成品文本。 ──
    try:
        ctx = build_annual_context_from_store(annual, with_narrative=False)
    except Exception as exc:
        print(f"[annual_analysis] context path failed ({type(exc).__name__}: {exc}), falling back to basic context")
        ctx = None
    if ctx:
        # 提取结构化财务分析，保持 annual_report_context 向后兼容。
        financial_analysis_raw = ctx.pop("_financial_analysis_raw", None)
        payload["annual_report_context"] = ctx

        # 注入多智能体专用的 annual_analysis 字段（独立于 pit_financials）
        annual_analysis: dict[str, Any] = {
            "report_year": ctx.get("report_year"),
            "sec_name": ctx.get("sec_name"),
            "financial_data": annual.get("financial_data") or [],
            "financial_analysis": financial_analysis_raw,
            "mda_full_text": annual.get("mda_text") or "",
        }
        if financial_analysis_raw:
            payload["annual_analysis"] = annual_analysis
        return

    # 降级路径：SQLite 有记录但 build_annual_context 返回空
    financial_data = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
    payload["annual_report_context"] = {
        "report_year": annual.get("report_year"),
        "sec_name": annual.get("sec_name"),
        "title": annual.get("title"),
        "mda_excerpt": str(annual.get("mda_text") or "")[:6000],
        "mda_meta": annual.get("mda_meta") or {},
        "financial_years": summarize_annual_financial_data(financial_data),
    }


def section_writer_agents(*, plan: dict[str, Any], data: dict[str, Any], charts: dict[str, str]) -> dict[str, str]:
    specs = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    if not specs:
        return {}

    def _write_spec(spec: dict[str, Any]) -> tuple[str, str]:
        name = str(spec.get("name") or "分析章节")
        agent = str(spec.get("agent") or "section_writer")
        prompt_data = _compact_data_for_prompt(data, charts, name, plan=plan)
        return name, _write_section(agent=agent, section_name=name, data=prompt_data, plan=plan)

    parallel = bool(get_env("OPENAI_API_KEY")) and env_flag("FINAGENT_SECTION_PARALLEL", default=True)
    if not parallel or len(specs) == 1:
        return {name: content for name, content in (_write_spec(spec) for spec in specs)}

    tasks = {str(spec.get("name") or f"section_{i}"): (lambda sp=spec: _write_spec(sp)) for i, spec in enumerate(specs)}
    results = parallel_map(tasks, max_workers=finagent_max_workers(), parallel=True)
    sections: dict[str, str] = {}
    for key, result in results.items():
        if isinstance(result, BaseException):
            sections[key] = normalize_section_text(f"本节生成失败：{type(result).__name__}", key)
            continue
        name, content = result
        sections[name] = content
    return sections


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
            system=(
                "你是研报验证 Agent。只返回 JSON，不写 Markdown。\n"
                "你的任务是检查报告是否忠于已采集数据、是否遗漏重要图表解读、是否有应补充或应收敛的结论。\n"
                "你必须逐章节检查是否和目标股票直接相关；泛泛讲宏观、行业、市场或方法论但没有落到目标股票的数据、图表或结论的部分，必须要求改写。\n"
                "禁止要求补充 Wind、新闻、券商预测、管理层指引等本系统未采集数据。\n\n"
                "## 图表质量标准（必须逐条核对每张图）\n"
                + "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(CHART_QUALITY_REQUIREMENTS))
                + "\n\n对每张图判断是否满足上述标准。\n"
                "不满足的，在 `chart_quality_review.delete` 或 `chart_quality_review.redraw` 中具体说明原因和修改方向。\n"
                "对于信息量可显著提升的图（如单指标折线图可改为双轴对比图、缺少历史分位的估值图），应放在 `redraw` 中，并给出具体建议（例如：'将 PE 和利润增速画在双轴图上'）。\n"
                "如果图表数量不足 8 张或存在大量低质量图，应在 `refinement_requests` 中将 `refresh_charts` 设为 true，并说明原因。\n\n"
                "## 整体报告质量要求\n"
                "除了逐图审核外，你还需要从整体视角评估报告的可读性和逻辑连贯性：\n"
                "1. **图文布局**：图表不应全部挤在「可视化」章节，应尽量分散到对应分析段落附近（例如在量价分析段插入价格图，在资金流段插入资金图）。\n"
                "2. **章节衔接**：相邻章节之间是否有过渡句或逻辑联系？例如「经营质量分析」之后是否自然引出「资金与交易结构」。\n"
                "3. **段落冗长**：是否有大段纯文字堆砌，缺乏小标题、列表或图表支撑？建议拆分为更易读的子段落。\n"
                "4. **结论先行**：每个章节开头应有小结或关键结论，避免让读者在段落中寻找要点。\n"
                "5. **图表引用**：正文中是否明确引用了图表（如“如图1所示”）？如果图表与正文脱节，应在 `action_items` 中要求补充引用。\n"
                "请在输出 JSON 中增加一个字段 `structural_feedback`，它是一个数组，每个元素包含 `section`（章节名）、`issue`（问题类型，如 `layout`、`cohesion`、`verbosity`）、`suggestion`（具体修改建议）。\n"
                "同时，如果多个章节内容重叠或可以合并，请在 `structural_feedback` 中建议合并，并给出合并后的标题。"
            ),
            user=json.dumps(
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
            + "\n必须返回 score/action_items/section_feedback/unsupported_claims/missing_data_notes/chart_quality_review/stock_relevance_review/refinement_requests/final_decision/structural_feedback。"
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
    rewrite_jobs: dict[str, Callable[[], tuple[str, str]]] = {}

    def _revise_one(name: str, content: str) -> tuple[str, str]:
        section_notes = _string_list(feedback.get(name))
        section_relevance = relevance.get(name) if isinstance(relevance.get(name), dict) else {}
        if section_relevance.get("decision") == "rewrite":
            section_notes.append(str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。"))
        prompt_data = _compact_data_for_prompt(data, charts, name, plan=plan)
        revise_director_guidance = ""
        if is_operating_quality_section(name, plan):
            revise_director_guidance = _operating_quality_writer_guidance()
        revise_industry_guidance = _industry_comparison_writer_guidance(name, prompt_data, plan=plan)
        try:
            text = normalize_section_text(
                llm_text(
                    f"你是 revise_agent。请根据验证 Agent 的意见，重写《{name}》章节。"
                    "只能使用 JSON 中已有数据；不要新增未采集来源；不要给买卖建议。"
                    "需要补充图表解读、数据局限和更可追溯的数字表述。"
                    "正文和表格展示层不要输出 raw JSON 字段路径或嵌套键名，例如 factor_trend.latest.xxx、data.xxx、margin_trajectory.xxx；"
                    "需要说明来源时用自然语言口径描述，例如“最新估值因子”“两融轨迹”“同比增长因子”。"
                    f"{analytical_writing_core()} "
                    f"{section_opening_conclusion_rule()} "
                    f"{section_writing_style_hint(name)} "
                    f"{revise_director_guidance}"
                    f"{revise_industry_guidance}"
                    "优先引用 data.analytical_evidence；多年数据须用 Markdown 表格（表头清晰、多指标对比优先宽表≥3列，禁止两行两列敷衍）；"
                    "若有 mda_crosswalk，融入盈利/现金流段落对照 MD&A，勿设独立勾稽章节。"
                    "每一段都必须回到目标股票本身：引用目标股票代码、具体指标、目标股票图表或目标股票对应行业归属。"
                    "如果原文有泛泛讲宏观、行业、市场或方法论但没有连接目标股票的句子，请删除或改写。"
                    "直接输出 Markdown 正文，不要写「好的」「根据您的反馈」「遵照您的指示」等开场白，不要重复章节标题。",
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
                ),
                name,
            )
            return name, text
        except Exception:
            return name, normalize_section_text(content, name)

    for name, content in sections.items():
        section_notes = _string_list(feedback.get(name))
        section_relevance = relevance.get(name) if isinstance(relevance.get(name), dict) else {}
        if section_relevance.get("decision") == "rewrite":
            section_notes.append(str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。"))
        if not section_notes and not action_items:
            continue
        rewrite_jobs[name] = lambda n=name, c=content: _revise_one(n, c)

    if not rewrite_jobs:
        return revised
    if len(rewrite_jobs) == 1 or not env_flag("FINAGENT_SECTION_PARALLEL", default=True):
        for name, fn in rewrite_jobs.items():
            key, text = fn()
            revised[key] = text
        return revised

    for name, result in parallel_map(rewrite_jobs, max_workers=finagent_max_workers(), parallel=True).items():
        if isinstance(result, BaseException):
            revised[name] = normalize_section_text(sections.get(name, ""), name)
        else:
            key, text = result
            revised[key] = text
    return revised


def refinement_loop(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    validation: dict[str, Any],
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    chart_output_dir: Path,
    use_cached_only: bool = False,
    force_refresh: bool = False,
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
            as_of=as_of,
            lookback_days=next_lookback,
            output_dir=output_dir,
            use_cached_only=use_cached_only,
            force_refresh=force_refresh,
        )
        data.pop("_chart_metadata", None)  # 显式清除旧元数据，防止 stale metadata 传递到组装阶段
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


def _render_draft_markdown(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
) -> str:
    return render_multi_markdown(
        summary="",
        plan=plan,
        data=data,
        charts=charts,
        sections=normalize_sections(sections),
        validation=None,
    )


def _blocked_chart_names(validation: dict[str, Any] | None) -> set[str]:
    validation = validation or {}
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    return {str(name) for name in delete}


def _assemble_multi_report(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None,
    output_path: Path,
    json_path: Path,
) -> tuple[str, dict[str, Any]]:
    normalized = normalize_sections(sections)
    blocked = _blocked_chart_names(validation)

    placement, visual_meta = resolve_section_visuals(
        sections=normalized,
        charts=charts,
        data=data,
        plan=plan,
        blocked=blocked,
        validation=validation,
    )

    sections_inline, unused = apply_chart_placements_agent(
        normalized,
        charts,
        placement,
        data=data,
        figure_notes=None,
    )

    executive_summary = generate_multi_executive_summary(data=data, sections=sections_inline, plan=plan)

    final_markdown = render_multi_markdown(
        summary=executive_summary,
        plan=plan,
        data=data,
        charts=charts,
        sections=sections_inline,
        inline_charts=True,
        unused_charts=unused,
        validation=validation,
    )

    html_path = output_path.with_suffix(".html")
    html_text = render_multi_html(
        summary=executive_summary,
        plan=plan,
        data=data,
        charts=charts,
        sections=sections_inline,
        inline_charts=True,
        unused_charts=unused,
        validation=validation,
    )
    html_path.write_text(html_text, encoding="utf-8")

    payload = build_multi_json_payload(
        plan=plan,
        data=data,
        charts=charts,
        sections=sections_inline,
        validation=validation,
        summary=executive_summary,
        output_markdown=str(output_path),
        output_json=str(json_path),
        output_html=str(html_path),
        chart_placement=placement,
        unused_charts=unused,
        chart_need=visual_meta.get("visual_need"),
    )
    return final_markdown, payload


def generate_multi_executive_summary(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any] | None = None,
) -> str:
    """基于各章节结论与核心指标，生成报告级执行摘要（1 段核心矛盾 + 数字）。"""
    from .multi_report import build_data_summary
    from .report_writing import local_multi_executive_summary, multi_executive_summary_prompt

    cleaned = {name: str(content).strip() for name, content in sections.items() if str(content).strip()}
    if not get_env("OPENAI_API_KEY"):
        return normalize_section_text(local_multi_executive_summary(data, cleaned), "执行摘要")
    try:
        section_excerpt = {name: content[:900] for name, content in cleaned.items()}
        summary = llm_text(
            multi_executive_summary_prompt(),
            json.dumps(
                {
                    "order_book_id": data.get("order_book_id"),
                    "stock_code": data.get("stock_code"),
                    "sec_name": data.get("sec_name"),
                    "narrative_thesis": (plan or {}).get("narrative_thesis"),
                    "date_range": [data.get("start_date"), data.get("end_date")],
                    "technical": data.get("technical"),
                    "factor": data.get("factor"),
                    "industry": data.get("industry"),
                    "data_summary": build_data_summary(data),
                    "annual_report_context": data.get("annual_report_context"),
                    "section_excerpt": section_excerpt,
                },
                ensure_ascii=False,
            )[:20000],
        )
        return normalize_section_text(summary, "执行摘要")
    except Exception:
        return normalize_section_text(local_multi_executive_summary(data, cleaned), "执行摘要")


def final_synthesis_agent(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    validation: dict[str, Any] | None = None,
) -> str:
    chart_lines = [f"![{name}]({path})" for name, path in charts.items()]
    cleaned_sections = {}
    for name, content in sections.items():
        cleaned = _extract_section_content(content, section_name=name)
        if cleaned.strip() in ("", f"## {name}", name):
            continue
        cleaned_sections[name] = cleaned
    body = "\n\n".join(f"## {name}\n{cleaned_sections[name]}" for name in cleaned_sections)

    if not get_env("OPENAI_API_KEY"):
        summary = "本报告由本地多智能体流程生成：计划、数据执行、分段写作、图表生成和汇总均已完成。"
    else:
        try:
            summary = llm_text(
                "你是最终汇总 Agent。只能基于输入 JSON 和各分段结论写执行摘要，不给买卖建议。"
                "禁止添加宏观、行业、新闻、Wind、券商预测、管理层指引等输入中不存在的信息。"
                "如果某类信息没有采集，就明确写为数据局限。",
                json.dumps(
                    {
                        "plan": plan,
                        "technical": data.get("technical"),
                        "factor": data.get("factor"),
                        "industry": data.get("industry"),
                        "validation": validation,
                        "sections": cleaned_sections,
                    },
                    ensure_ascii=False,
                )[:18000],
            )
        except Exception:
            summary = "多维数据已汇总，详见各分段分析。"
    validation_lines = _validation_markdown(validation)

    include_visualization = get_env("ENABLE_LAYOUT_OPTIMIZER", "true").lower() != "true"
    viz_section = []
    if include_visualization and chart_lines:
        viz_section = ["## 可视化", *(chart_lines or ["本次未生成图表。"])]

    return "\n".join(
        [
            f"# {multi_report_display_title(stock_code=str(data.get('stock_code') or str(data.get('order_book_id', '')).split('.')[0]), sec_name=str(data.get('sec_name') or ''), suffix='多智能体研究报告')}",
            "",
            "## 执行摘要",
            summary,
            "",
            *viz_section,
            "",
            body,
            "",
            "## 验证 Agent 复核",
            *validation_lines,
            "",
            "## 数据与工具说明",
            f"- 数据区间：{data['start_date']} 至 {data['end_date']}",
            f"- 计划使用的米筐函数：{', '.join(plan.get('tools') or list(TOOL_REGISTRY))}",
            "- 本报告仅供课程研究与信息展示，不构成投资建议。",
            "",
        ]
    )

def layout_optimizer(markdown_text: str, charts: dict[str, str]) -> str:
    import re
    from pathlib import Path

    lines = markdown_text.splitlines(keepends=True)

    viz_start = None
    viz_end = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## 可视化"):
            viz_start = i
        elif viz_start is not None and line.strip().startswith("## ") and i > viz_start:
            viz_end = i
            break
    if viz_start is None:
        return markdown_text
    if viz_end is None:
        viz_end = len(lines)

    new_lines = lines[:viz_start] + lines[viz_end:]

    viz_chunk = lines[viz_start:viz_end]
    chart_refs = []
    for idx, cline in enumerate(viz_chunk):
        stripped = cline.strip()
        if stripped.startswith("![") and "](" in stripped:
            match = re.search(r'!\[.*?\]\((.*?)\)', stripped)
            if match:
                full_path = match.group(1)
                filename = Path(full_path).name
                chart_refs.append((filename, cline, idx))

    if not chart_refs:
        return "".join(new_lines)

    section_keywords = {
        "量价与趋势": ["price_volume", "moving_averages", "cumulative_return", "drawdown", "turnover_rate"],
        "技术因素": ["technical_indicators"],
        "资金与交易结构": ["capital_flow", "cumulative_capital_flow", "buy_sell_value", "margin_enhanced"],
        OPERATING_QUALITY_SECTION: [
            "industry_profitability_compare",
            "industry_growth_leverage_compare",
            "industry_dbscan_anomaly",
            "latest_quality_snapshot",
            "profitability_factors",
            "growth_factors",
            "liquidity_factors",
            "debt_ratio_trend",
        ],
        "宏观利率背景": ["shibor_rates", "gov_yield_trend", "yield_curve_snapshot"],
    }

    chart_target = {}
    for filename, cline, _ in chart_refs:
        target = None
        for section, keywords in section_keywords.items():
            if any(kw in filename for kw in keywords):
                target = section
                break
        chart_target[filename] = target

    section_ranges = {}
    current_section = None
    start_idx = None
    for i, line in enumerate(new_lines):
        if line.strip().startswith("## "):
            if current_section is not None:
                section_ranges[current_section] = (start_idx, i)
            current_section = line.strip().lstrip("#").strip()
            start_idx = i
    if current_section is not None:
        section_ranges[current_section] = (start_idx, len(new_lines))

    insert_plan = {section: [] for section in section_keywords}
    for filename, cline, _ in chart_refs:
        target = chart_target[filename]
        if target and target in insert_plan:
            if cline not in insert_plan[target]:
                insert_plan[target].append(cline)

    output_parts = []
    first_section_start = min((start for start, _ in section_ranges.values()), default=0)
    output_parts.extend(new_lines[:first_section_start])

    for section_name, (start, end) in sorted(section_ranges.items(), key=lambda x: x[1][0]):
        output_parts.extend(new_lines[start:end])
        if section_name in insert_plan and insert_plan[section_name]:
            output_parts.append("\n")
            output_parts.extend(insert_plan[section_name])
            output_parts.append("\n")

    return "".join(output_parts)

def _write_section(*, agent: str, section_name: str, data: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    if not get_env("OPENAI_API_KEY"):
        return f"{agent} 本地摘要：{section_name} 已基于可用数据完成。"
    style_hint = section_writing_style_hint(section_name)

    director_guidance = _operating_quality_writer_guidance() if is_operating_quality_section(section_name, plan) else ""
    industry_guidance = _industry_comparison_writer_guidance(section_name, data, plan=plan)

    try:
        role_prompt = (
            fundamental_narrative_system_prompt()
            if is_operating_quality_section(section_name, plan)
            else f"你是 {agent}。请写研报中的《{section_name}》章节。"
        )
        max_chars = 36000 if is_operating_quality_section(section_name, plan) else 24000
        return normalize_section_text(
            llm_text(
                role_prompt
                + " "
                "只能使用用户提供的 JSON 数据，不得补充外部来源、宏观、行业、新闻、Wind、券商预测或未采集信息。"
                "所有数值结论必须能从 JSON 中追溯；没有数据就写数据局限。不要给买卖建议。"
                "正文和表格展示层不要输出 raw JSON 字段路径或嵌套键名，例如 factor_trend.latest.xxx、data.xxx、margin_trajectory.xxx；"
                "需要说明来源时用自然语言口径描述，例如“最新估值因子”“两融轨迹”“同比增长因子”。"
                f"{analytical_writing_core()} "
                f"{section_opening_conclusion_rule()} "
                f"{style_hint} "
                f"{director_guidance}"
                f"{industry_guidance}"
                "优先使用 annual_financial_analysis 中的完整财务画像（全部 reviewed_signals、metrics、articulation_checks），"
                "以及 analytical_evidence 中的日期、窗口统计与多年表；"
                "若有 mda_crosswalk 或 mda_full_text，在盈利/现金流/风险相关段落中做「报表数据 + MD&A 管理层解释 + 独立判断」三者对照，"
                "勿设独立勾稽章节；数值结论必须可从 JSON 追溯；"
                "有 pit_financials_table / financial_years 时必须输出 Markdown 对比表。"
                "直接输出 Markdown 正文，不要写「好的」「根据您提供的」等开场白，不要重复章节标题。",
                json.dumps(data, ensure_ascii=False)[:max_chars],
            ),
            section_name,
        )
    except Exception as exc:
        return f"{agent} 章节生成失败，已保留数据摘要。错误：{exc}"


def _previous_trading_date(rqdatac: Any, value: date) -> date:
    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted
    from .stock_utils import calendar_trading_as_of

    if rqdatac is None or rqdata_quota_exhausted():
        return calendar_trading_as_of(value)
    try:
        if rqdatac.is_trading_date(value):
            return value
        return rqdatac.get_previous_trading_date(value)
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="previous_trading_date")
        return calendar_trading_as_of(value)


def _safe_rq_call(name: str, fn: Any) -> Any:
    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted

    if rqdata_quota_exhausted():
        return pd.DataFrame()
    try:
        return fn()
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where=name)
            return pd.DataFrame()
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
    from .price_technical import technical_summary_from_dataframe

    return technical_summary_from_dataframe(df)


def _ensure_technical_from_price_rows(payload: dict[str, Any]) -> None:
    from .price_technical import ensure_technical_from_price_rows

    ensure_technical_from_price_rows(payload)


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
    section_feedback: dict[str, list[str]] = {}
    chart_review = _chart_quality_review(data=data, charts=charts)
    relevance_review = _stock_relevance_review(data=data, sections=sections)
    narrative_review = _section_narrative_review(sections=sections)
    if len(charts) < 8:
        action_items.append(f"图表数量只有 {len(charts)} 张，建议补充到至少 8 张。")
    for name, reason in chart_review.get("delete", {}).items():
        action_items.append(f"图表 {name} 信息含量不足或量纲不合适，建议删除或重画：{reason}")
    for name, review in relevance_review.items():
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 与目标股票关联不足，需要改写：{review.get('reason')}")
    for name, review in narrative_review.items():
        if review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 叙事结构需优化：{review.get('reason')}")
    for key in ("price", "factor_history", "capital_flow", "securities_margin", "dividend", "shares", "interbank_rate", "yield_curve"):
        value = data.get(key)
        if isinstance(value, dict) and int(value.get("row_count") or 0) == 0:
            action_items.append(f"{key} 没有返回可用行，需要在报告中说明数据局限。")
    industry_feedback = _industry_comparison_section_feedback(data, sections)
    for section_name, notes in industry_feedback.items():
        section_feedback.setdefault(section_name, []).extend(notes)
        action_items.extend(f"章节 {section_name} 缺少同行横向比较：{note}" for note in notes)
    unsupported = []
    for token in ("Wind", "券商预测", "新闻", "管理层指引"):
        if token in draft_markdown:
            unsupported.append(token)
    return {
        "score": 80 if not unsupported and len(charts) >= 8 else 65,
        "action_items": action_items,
        "section_feedback": section_feedback,
        "unsupported_claims": unsupported,
        "missing_data_notes": action_items,
        "chart_quality_review": chart_review,
        "stock_relevance_review": relevance_review,
        "section_narrative_review": narrative_review,
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
    result["action_items"] = _dedupe([*_string_list(fallback.get("action_items")), *_string_list(result.get("action_items"))])
    result["unsupported_claims"] = _string_list(result.get("unsupported_claims"))
    result["missing_data_notes"] = _dedupe([*_string_list(fallback.get("missing_data_notes")), *_string_list(result.get("missing_data_notes"))])
    chart_review = result.get("chart_quality_review")
    result["chart_quality_review"] = chart_review if isinstance(chart_review, dict) else fallback.get("chart_quality_review", {})
    relevance_review = result.get("stock_relevance_review")
    result["stock_relevance_review"] = relevance_review if isinstance(relevance_review, dict) else fallback.get("stock_relevance_review", {})
    feedback = result.get("section_feedback")
    result["section_feedback"] = _merge_section_feedback(
        fallback.get("section_feedback") if isinstance(fallback.get("section_feedback"), dict) else {},
        feedback if isinstance(feedback, dict) else {},
    )
    decision = str(result.get("final_decision") or fallback["final_decision"]).lower()
    result["final_decision"] = decision if decision in {"pass", "revise", "block"} else "revise"
    if fallback.get("final_decision") == "revise" and result["section_feedback"]:
        result["final_decision"] = "revise"
    requests = result.get("refinement_requests")
    result["refinement_requests"] = requests if isinstance(requests, dict) else fallback.get("refinement_requests", {})
    structural = result.get("structural_feedback")
    result["structural_feedback"] = structural if isinstance(structural, list) else []
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
        delete["latest_quality_snapshot"] = "盈利质量指标量纲不同，改以表格展示。"
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


_NARRATIVE_THESIS_HEADING = re.compile(r"^###\s+[^:\n：]+[：:]\S+", re.MULTILINE)
_NARRATIVE_SYNTHESIS = re.compile(r"(综合判断|的影响|格局|显示|表明|结论|动能|压力|支撑|反转|修复)")
_NARRATIVE_DATE_BULLET = re.compile(r"^[-*]\s.*?\d+月\d+日", re.MULTILINE)


def _narrative_structure_ok(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    if text.startswith("**核心结论**"):
        return True
    if _NARRATIVE_THESIS_HEADING.search(text):
        return True
    if _NARRATIVE_SYNTHESIS.search(text):
        prose_lines = [
            line
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith(("#", "-", "*", "|"))
        ]
        if len(prose_lines) >= 2:
            return True
    heading = re.search(r"^###\s+(.+)$", text, re.MULTILINE)
    if not heading:
        return bool(_NARRATIVE_SYNTHESIS.search(text))
    rest = text[heading.end() :].lstrip("\n")
    first_lines = [line.strip() for line in rest.splitlines() if line.strip()][:3]
    if first_lines and all(line.startswith(("-", "*")) for line in first_lines):
        dated_bullets = len(_NARRATIVE_DATE_BULLET.findall(text))
        if dated_bullets >= 2 and not _NARRATIVE_SYNTHESIS.search(text):
            return False
        return False
    return True


def _review_section_narrative(content: str) -> tuple[str, str]:
    text = str(content or "").strip()
    if not text:
        return "rewrite", "章节为空，无法评估叙事结构。"
    if _narrative_structure_ok(text):
        return "pass", "章节首段或首个小节标题已给出结论，并包含分析性表述。"
    return "rewrite", "章节以数据罗列为主，缺少结论先行的小结或影响判断。"


def _section_narrative_review(*, sections: dict[str, str]) -> dict[str, dict[str, str]]:
    review: dict[str, dict[str, str]] = {}
    for name, content in sections.items():
        decision, reason = _review_section_narrative(content)
        review[name] = {"decision": decision, "reason": reason}
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


_INDUSTRY_METRIC_PRIORITY = (
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "operating_revenue_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
)

_VALUATION_METRICS = {"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "dividend_yield_ttm"}
_VALUATION_KEY_PARTS = ("pe_ratio", "pb_ratio", "ps_ratio", "dividend_yield")

_DECIMAL_PERCENT_METRICS = {
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "operating_revenue_growth_ratio_ttm",
    "dividend_yield_ttm",
}

_POINT_PERCENT_METRICS = {"debt_to_asset_ratio"}
_MULTIPLE_METRICS = {"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "current_ratio", "quick_ratio"}


def _industry_comparison_prompt_summary(industry_comparison: Any) -> dict[str, Any] | None:
    if not isinstance(industry_comparison, dict):
        return None
    metrics = industry_comparison.get("metrics") if isinstance(industry_comparison.get("metrics"), dict) else {}
    rows = []
    for key in _ordered_industry_metric_keys(metrics):
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "metric": key,
                "label": _industry_metric_label(key, item),
                "target": item.get("target"),
                "mean": item.get("mean"),
                "median": item.get("median"),
                "p25": item.get("p25"),
                "p75": item.get("p75"),
                "percentile": item.get("percentile"),
                "relative_label": item.get("relative_label"),
                "valid_count": item.get("valid_count"),
            }
        )
    cluster = industry_comparison.get("cluster_anomalies")
    cluster_summary = cluster if isinstance(cluster, dict) else {}
    if "points" in cluster_summary:
        cluster_summary = {k: v for k, v in cluster_summary.items() if k != "points"}
    return {
        "industry": industry_comparison.get("industry"),
        "peers": industry_comparison.get("peers"),
        "metric_rows": rows,
        "relative_signals": _string_list_or_dicts(industry_comparison.get("relative_signals"))[:8],
        "cluster_anomalies": cluster_summary,
        "data_notes": _string_list(industry_comparison.get("data_notes"))[:8],
    }


def _operating_quality_industry_summary(industry_comparison: Any) -> dict[str, Any] | None:
    summary = _industry_comparison_prompt_summary(industry_comparison)
    if not isinstance(summary, dict):
        return None
    rows = summary.get("metric_rows") if isinstance(summary.get("metric_rows"), list) else []
    summary["metric_rows"] = [row for row in rows if isinstance(row, dict) and row.get("metric") not in _VALUATION_METRICS]
    cluster = summary.get("cluster_anomalies") if isinstance(summary.get("cluster_anomalies"), dict) else {}
    if cluster:
        for key in ("top_contributors", "single_metric_anomalies"):
            items = cluster.get(key)
            if isinstance(items, list):
                valuation_items = [item for item in items if isinstance(item, dict) and item.get("metric") in _VALUATION_METRICS]
                cluster[key] = [item for item in items if isinstance(item, dict) and item.get("metric") not in _VALUATION_METRICS]
                if valuation_items:
                    cluster["valuation_contributors_excluded"] = True
        features = cluster.get("features")
        if isinstance(features, list):
            cluster["operating_quality_features"] = [item for item in features if item not in _VALUATION_METRICS]
    return summary


def _industry_comparison_prompt_brief(industry_comparison: Any) -> str:
    summary = _industry_comparison_prompt_summary(industry_comparison) if not _is_industry_summary(industry_comparison) else industry_comparison
    if not isinstance(summary, dict):
        return ""
    industry = summary.get("industry") if isinstance(summary.get("industry"), dict) else {}
    peers = summary.get("peers") if isinstance(summary.get("peers"), dict) else {}
    level = industry.get("selected_level")
    selected_name = industry.get("selected_industry_name") or industry.get(f"level{level}_name") if level else None
    metric_rows = summary.get("metric_rows") if isinstance(summary.get("metric_rows"), list) else []
    notes = _string_list(summary.get("data_notes"))

    if not metric_rows:
        reason = "；".join(notes[:3]) or "未形成有效同行池。"
        return f"同行对比状态：未形成有效同行池；原因：{reason}写作时只说明数据局限，不得编造行业均值、中位数或聚类结论。"

    peer_count = peers.get("effective_count")
    level_text = f"中信 2019 {level}级行业" if level else "中信 2019 行业"
    heading = selected_name or "所选同行池"
    lines = [
        f"同行池口径：{level_text}「{heading}」，有效同行 {peer_count} 家。",
        "可直接用于写作的横向对比要点：",
    ]
    for row in metric_rows[:8]:
        key = str(row.get("metric") or "")
        percentile = _float(row.get("percentile"))
        lines.append(
            "- "
            f"{_industry_metric_label(key, row)}：目标公司 {_format_industry_metric_value(key, row.get('target'))}，"
            f"行业中位数 {_format_industry_metric_value(key, row.get('median'))}，"
            f"行业均值 {_format_industry_metric_value(key, row.get('mean'))}，"
            f"行业分位 {_format_percentile(percentile)}，{row.get('relative_label') or '接近行业中位区间'}。"
        )

    cluster = summary.get("cluster_anomalies") if isinstance(summary.get("cluster_anomalies"), dict) else {}
    if cluster.get("status") == "ok":
        contributors = cluster.get("top_contributors") if isinstance(cluster.get("top_contributors"), list) else []
        contributor_text = "、".join(_industry_metric_label(str(item.get("metric") or ""), item) for item in contributors[:3] if isinstance(item, dict))
        noise_text = "被 DBSCAN 标记为噪声点" if cluster.get("is_noise") else f"未被 DBSCAN 标记为噪声点，所属簇规模 {cluster.get('cluster_size')} 家"
        lines.extend(
            [
                f"DBSCAN 异常识别显示目标公司{noise_text}；异常分数约 {_format_plain_number(cluster.get('anomaly_score'))}。"
                + (f"主要贡献指标为{contributor_text}。" if contributor_text else ""),
            ]
        )
        single_metric = cluster.get("single_metric_anomalies") if isinstance(cluster.get("single_metric_anomalies"), list) else []
        if single_metric:
            single_text = "、".join(_industry_metric_label(str(item.get("metric") or ""), item) for item in single_metric[:3] if isinstance(item, dict))
            lines.append(f"同时存在单指标 robust z-score 超过阈值的异常项：{single_text}。")
        if cluster.get("valuation_contributors_excluded"):
            lines.append("DBSCAN 原始贡献指标包含估值因子；经营质量章节只使用非估值贡献项，估值驱动的聚类证据不用于经营质量结论。")
    else:
        reason = cluster.get("reason") or "样本数或有效特征不足"
        lines.append(f"DBSCAN 本次未执行：{reason}；行业判断主要依据分位数和四分位区间。")
    if notes:
        lines.append(f"数据局限：{'；'.join(notes[:3])}")
    return "\n".join(lines)


def _industry_comparison_writer_guidance(
    section_name: str,
    data: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    if not _section_uses_industry_comparison(section_name, plan) or not data.get("industry_comparison"):
        return ""
    brief = str(data.get("industry_comparison_brief") or "").strip()
    if is_operating_quality_section(section_name, plan):
        return (
            "本章节必须把同行对比作为经营质量分析坐标，而不是附录。写作时按以下要求处理："
            "1) 在「同行横向坐标」中说明实际采用的同行池层级和有效同行数量；"
            "2) 只使用经营质量指标做横向比较，如毛利率、净利率、ROE、收入/利润增长、资产负债率、流动比率、速动比率；"
            "3) 至少选择 2-3 个经营类关键指标说明目标公司相对行业均值、中位数和分位；"
            "4) DBSCAN 可用时只解释经营质量相关贡献指标；若主要异常来自估值因子，则说明聚类证据不用于经营质量结论；"
            "5) 禁止写 PE/PB/PS、股息率、估值分位、估值吸引力或估值匹配判断。"
            "行业口径必须以 industry_comparison_summary.industry.selected_level 和 selected_industry_name 为准，不要把一级行业误写成同行池。"
            + (f"同行对比写作简报：{brief}" if brief else "")
        )
    if "基本面" in section_name or "估值" in section_name:
        return (
            "本章节必须把同行对比作为分析坐标，而不是附录。写作时按以下顺序组织判断："
            "1) 先说明实际采用的同行池层级和有效同行数量；"
            "2) 估值必须说明 PE/PB/PS 至少一个指标相对行业的分位、均值和中位数；"
            "3) 盈利、成长、杠杆/偿债中至少选择 2-3 个关键指标做同行比较；"
            "4) DBSCAN 可用时说明是否为噪声点和主要贡献指标，不可用时说明样本或特征局限。"
            "行业口径必须以 industry_comparison_summary.industry.selected_level 和 selected_industry_name 为准，不要把一级行业误写成同行池。"
            "可以设置「行业横向坐标」这类小标题，但内容必须由你自然写成，不要机械复述字段名。"
            + (f"同行对比写作简报：{brief}" if brief else "")
        )
    return (
        "本章节可引用 industry_comparison_summary 的异常识别和数据局限作为风险证据；"
        "若同行池无效或 DBSCAN 跳过，只说明局限，不得编造行业结论。"
        + (f"同行对比写作简报：{brief}" if brief else "")
    )


def _operating_quality_writer_guidance() -> str:
    return (
        "本章节写经营与基本面：优先 annual_financial_analysis、pit、MD&A 与同行经营类对比；"
        "正文结构自由，不必固定八段模板；多年数据须用表格。"
        "禁止写 PE/PB/PS、股息率、估值分位或估值匹配判断。"
    )


def _ordered_industry_metric_keys(metrics: dict[str, Any]) -> list[str]:
    ordered = [key for key in _INDUSTRY_METRIC_PRIORITY if key in metrics]
    ordered.extend(key for key in metrics if key not in ordered)
    return ordered


def _industry_metric_label(key: str, item: Any | None = None) -> str:
    if isinstance(item, dict) and item.get("label"):
        return str(item["label"])
    return FACTOR_LABELS.get(key, key)


def _format_industry_metric_value(key: str, value: Any) -> str:
    number = _float(value)
    if number is None:
        return "N/A"
    if key in _DECIMAL_PERCENT_METRICS:
        return f"{number * 100:.2f}%"
    if key in _POINT_PERCENT_METRICS:
        return f"{number:.2f}%"
    if key in _MULTIPLE_METRICS:
        return f"{number:.2f}x"
    return _format_plain_number(number)


def _format_percentile(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.0f}%"


def _format_plain_number(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "N/A"
    return f"{number:.2f}"


def _is_industry_summary(value: Any) -> bool:
    return isinstance(value, dict) and "metric_rows" in value


def _string_list_or_dicts(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item]


def _merge_section_feedback(*sources: dict[str, Any]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for source in sources:
        for section_name, value in source.items():
            notes = _string_list(value)
            if notes:
                merged.setdefault(str(section_name), [])
                merged[str(section_name)] = _dedupe([*merged[str(section_name)], *notes])
    return merged


def _industry_comparison_section_feedback(data: dict[str, Any], sections: dict[str, str]) -> dict[str, list[str]]:
    comparison = data.get("industry_comparison") if isinstance(data.get("industry_comparison"), dict) else {}
    metrics = comparison.get("metrics") if isinstance(comparison.get("metrics"), dict) else {}
    if not metrics:
        return {}
    feedback: dict[str, list[str]] = {}
    for section_name, content in sections.items():
        is_operating = is_operating_quality_section(section_name)
        if not is_operating and "基本面" not in section_name and "估值" not in section_name:
            continue
        text = str(content or "")
        if is_operating and _section_mentions_valuation(text):
            feedback.setdefault(section_name, []).append("经营质量分析不应出现 PE/PB/PS、股息率、估值分位或估值吸引力判断。")
        if not _section_mentions_peer_comparison(text):
            feedback[section_name] = [
                *feedback.get(section_name, []),
                "已有经营类 industry_comparison 数据，但正文没有明确使用同行池、经营类指标的行业均值/中位数、行业分位或 DBSCAN/样本局限；请重写为主动横向比较。",
            ]
    return feedback


def _section_mentions_peer_comparison(content: str) -> bool:
    text = str(content or "")
    peer_terms = ("同行", "横向", "同业")
    statistic_terms = ("分位", "中位数", "均值", "P25", "P75", "四分位")
    anomaly_terms = ("DBSCAN", "聚类", "噪声点", "样本不足", "有效同行")
    has_peer = any(term in text for term in peer_terms)
    has_statistic = any(term in text for term in statistic_terms)
    has_anomaly_or_count = any(term in text for term in anomaly_terms)
    return has_peer and has_statistic and has_anomaly_or_count


def _section_mentions_valuation(content: str) -> bool:
    text = str(content or "")
    forbidden = ("PE", "PB", "PS", "市盈率", "市净率", "市销率", "股息率", "估值分位", "估值吸引力", "估值匹配")
    return any(term in text for term in forbidden)



def _strip_valuation_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_valuation_fields(item) for key, item in value.items() if not _is_valuation_key(key)}
    if isinstance(value, list):
        return [_strip_valuation_fields(item) for item in value]
    return value


def _is_valuation_key(key: Any) -> bool:
    text = str(key or "").lower()
    return any(part in text for part in _VALUATION_KEY_PARTS)


def _filter_operating_quality_charts(charts: dict[str, str]) -> dict[str, str]:
    blocked = {"industry_valuation_compare", "valuation_percentile", "valuation_factors", "latest_valuation_snapshot", "dividend_spread"}
    return {name: path for name, path in charts.items() if name not in blocked}


def _compact_data_for_prompt(
    data: dict[str, Any],
    charts: dict[str, str],
    section_name: str,
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tail = 20 if "量价" in section_name or "技术" in section_name else 12
    payload = {
        "section_name": section_name,
        "order_book_id": data.get("order_book_id"),
        "sec_name": data.get("sec_name"),
        "date_range": [data.get("start_date"), data.get("end_date")],
        "technical": data.get("technical"),
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "analytical_evidence": build_analytical_evidence(data, section_name),
        "capital_flow": {k: v for k, v in data.get("capital_flow", {}).items() if k != "rows"}
        | {"recent_rows": data.get("capital_flow", {}).get("rows", [])[-tail:]},
        "price_recent": data.get("price", {}).get("rows", [])[-tail:],
        "price_change_rate_recent": data.get("price_change_rate", {}).get("rows", [])[-tail:],
        "turnover_recent": data.get("turnover", {}).get("rows", [])[-tail:],
        "securities_margin_recent": data.get("securities_margin", {}).get("rows", [])[-tail:],
        "dividend_recent": data.get("dividend", {}).get("rows", [])[-8:],
        "shares_recent": data.get("shares", {}).get("rows", [])[-8:],
        "factor_history_recent": data.get("factor_history", {}).get("rows", [])[-12:],
        "macro_rate_recent": {
            "interbank_rate": data.get("interbank_rate", {}).get("rows", [])[-12:],
            "yield_curve": data.get("yield_curve", {}).get("rows", [])[-12:],
        },
        "status_checks": {
            "suspended_recent": data.get("suspended", {}).get("rows", [])[-8:],
            "st_recent": data.get("st_stock", {}).get("rows", [])[-8:],
        },
        "charts": charts,
    }
    if _section_uses_industry_comparison(section_name, plan):
        industry_summary = (
            _operating_quality_industry_summary(data.get("industry_comparison"))
            if is_operating_quality_section(section_name, plan)
            else _industry_comparison_prompt_summary(data.get("industry_comparison"))
        )
        payload["industry_comparison_summary"] = industry_summary
        payload["industry_comparison"] = industry_summary
        payload["industry_comparison_brief"] = _industry_comparison_prompt_brief(industry_summary)
    if is_operating_quality_section(section_name, plan):
        payload["factor"] = _strip_valuation_fields(payload.get("factor"))
        payload["factor_history_recent"] = _strip_valuation_fields(payload.get("factor_history_recent"))
        payload["dividend_recent"] = []
        payload["charts"] = _filter_operating_quality_charts(payload.get("charts", {}))
    if is_operating_quality_section(section_name, plan) or "基本面" in section_name or "风险" in section_name:
        payload["pit_financials"] = data.get("pit_financials")
        ctx = data.get("annual_report_context")
        payload["annual_report_context"] = ctx
        if isinstance(ctx, dict):
            payload["mda_crosswalk"] = ctx.get("mda_crosswalk")
            payload["articulation_checks"] = ctx.get("articulation_checks")
        # ── 完整年报财务分析（经营质量与风险章节使用，无截断） ──
        annual = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
        if annual.get("financial_analysis") and isinstance(annual["financial_analysis"], dict):
            payload["annual_financial_analysis"] = annual["financial_analysis"]
    return payload


def _section_uses_industry_comparison(section_name: str, plan: dict[str, Any] | None = None) -> bool:
    return is_operating_quality_section(section_name, plan) or any(
        token in section_name for token in ("基本面", "估值", "风险")
    )


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

def _extract_section_content(content: str, section_name: str = "") -> str:
    if not isinstance(content, str):
        return str(content)
    stripped = content.strip()
    if stripped.startswith('{') and stripped.endswith('}'):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                if "revised_section" in data and isinstance(data["revised_section"], str):
                    content = data["revised_section"]
                elif "content" in data and isinstance(data["content"], str):
                    content = data["content"]
                elif "section_name" in data and isinstance(data["section_name"], str):
                    content = data["section_name"]
        except json.JSONDecodeError:
            pass
    cleaned = re.sub(r'\\\{\}n', '', content)
    cleaned = re.sub(r'\\\{\}', '', cleaned)
    cleaned = re.sub(r'n\s*n', ' ', cleaned)
    if section_name:
        pattern = rf'^##\s*{re.escape(section_name)}\s*\n\s*{re.escape(section_name)}'
        cleaned = re.sub(pattern, f'## {section_name}', cleaned, flags=re.MULTILINE)
    lines = cleaned.splitlines()
    if len(lines) >= 2 and lines[0].strip() == f"## {section_name}" and lines[1].strip() == section_name:
        lines.pop(1)
        cleaned = "\n".join(lines)
    return cleaned.strip()
