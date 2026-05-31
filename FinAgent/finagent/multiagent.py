from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .cninfo import default_as_of, normalize_stock_code, to_order_book_id
from .env import get_env, load_dotenv
from .llm import llm_json, llm_text
from .chart_catalog import MARKET_TECH_SECTION
from .multi_report import (
    apply_chart_placements,
    build_multi_json_payload,
    multi_report_display_title,
    render_multi_html,
    render_multi_markdown,
)
from .visual_placement import resolve_section_visuals
from .report_format import normalize_section_text, normalize_sections, section_writing_style_hint
from .report_writing import analytical_writing_core, build_analytical_evidence, section_opening_conclusion_rule, summarize_annual_financial_data
from .rqdata_client import _init_rqdata
from .chart_plots import chart_agent
from .latex_exporter import export_latex
import re

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
    {"name": "基本面与估值", "agent": "fundamental_writer", "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares"]},
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


def run_multi_agent(options: MultiAgentOptions) -> dict[str, Any]:
    load_dotenv()
    root = Path(options.workdir)
    output_path = Path(options.output) if options.output else root / "outputs" / f"{normalize_stock_code(options.stock)}_multi_agent_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    as_of_date = default_as_of(options.as_of)
    stock_code = normalize_stock_code(options.stock)
    order_book_id = to_order_book_id(stock_code)

    plan = planner_agent(stock_code=stock_code, order_book_id=order_book_id, as_of=as_of_date, lookback_days=options.lookback_days)
    data = data_executor_agent(order_book_id=order_book_id, as_of=as_of_date, lookback_days=options.lookback_days, output_dir=output_path.parent)
    chart_output_dir = output_path.parent / "charts" / output_path.stem
    chart_files = chart_agent(data=data, output_dir=chart_output_dir)
    charts = {name: _markdown_path(path, output_path.parent) for name, path in chart_files.items()}
    sections = section_writer_agents(plan=plan, data=data, charts=charts)
    draft_markdown = _render_draft_markdown(plan=plan, data=data, charts=charts, sections=sections)
    validation = validation_agent(plan=plan, data=data, charts=charts, sections=sections, draft_markdown=draft_markdown)
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
    )
    sections = revise_sections_with_validation(plan=plan, data=data, charts=charts, sections=sections, validation=validation)
    final_markdown, payload = _assemble_multi_report(
        plan=plan,
        data=data,
        charts=charts,
        sections=sections,
        validation=validation,
        output_path=output_path,
        json_path=output_path.with_suffix(".json"),
    )
    output_path.write_text(final_markdown, encoding="utf-8")
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_markdown"] = str(output_path)
    payload["output_json"] = str(json_path)
    payload["output_html"] = payload.get("meta", {}).get("output_html") or str(output_path.with_suffix(".html"))

    if get_env("EXPORT_LATEX", "true").lower() == "true":
        from .latex_exporter import export_latex
        try:
            tex_path = output_path.with_suffix(".tex")
            compile_pdf = get_env("COMPILE_PDF", "false").lower() == "true"
            export_latex(
                markdown_text=final_markdown,
                output_tex_path=tex_path,
                title=multi_report_display_title(
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
        except Exception as e:
            print(f"LaTeX 导出失败: {e}")

    return payload


def planner_agent(*, stock_code: str, order_book_id: str, as_of: date, lookback_days: int) -> dict[str, Any]:
    fallback = {
        "objective": "生成覆盖量价、基本面、资金流、技术因素的 A 股多智能体研究报告",
        "tools": list(TOOL_REGISTRY),
        "sections": DEFAULT_SECTIONS,
        "risk_controls": ["仅基于可取得数据写结论", "不输出买卖建议", "说明缺失数据"],
    }
    if not get_env("OPENAI_API_KEY"):
        return fallback
    try:
        plan = llm_json(
            "你是金融研究系统的计划 Agent。只返回 JSON，不要写 Markdown。",
            "请为 A 股研究报告制定多智能体执行计划。"
            f"\n股票: {stock_code} / {order_book_id}"
            f"\n截至日期: {as_of.isoformat()}，回看天数: {lookback_days}"
            f"\n可用米筐函数: {json.dumps(TOOL_REGISTRY, ensure_ascii=False)}"
            f"\n图表质量要求: {json.dumps(CHART_QUALITY_REQUIREMENTS, ensure_ascii=False)}"
            "\n必须返回 objective/tools/sections/risk_controls。sections 每项包含 name/agent/data。"
            "\n禁止规划宏观、行业、新闻、Wind、券商预测等未在可用函数中的数据。",
        )
        return _sanitize_plan(plan, fallback)
    except Exception:
        return fallback


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
    try:
        instrument = _safe_rq_call("instruments", lambda: rqdatac.instruments(order_book_id))
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


def data_executor_agent(*, order_book_id: str, as_of: date, lookback_days: int, output_dir: Path) -> dict[str, Any]:
    import rqdatac

    _init_rqdata(rqdatac)
    stock_code = order_book_id.split(".")[0]
    sec_name = _fetch_sec_name(rqdatac, order_book_id, stock_code)
    end_date = _previous_trading_date(rqdatac, as_of)
    start_date = end_date - timedelta(days=max(30, lookback_days))
    fundamentals_start = end_date - timedelta(days=730)
    macro_start = end_date - timedelta(days=120)
    available_factors = set(rqdatac.get_all_factor_names())
    factors = [name for name in FACTOR_CANDIDATES if name in available_factors]

    price = rqdatac.get_price(
        order_book_id,
        start_date=start_date,
        end_date=end_date,
        frequency="1d",
        fields=["open", "high", "low", "close", "volume", "total_turnover"],
    )
    turnover = _safe_rq_call("get_turnover_rate", lambda: rqdatac.get_turnover_rate(order_book_id, start_date=start_date, end_date=end_date))
    capital = _safe_rq_call("get_capital_flow", lambda: rqdatac.get_capital_flow(order_book_id, start_date=start_date, end_date=end_date))
    price_change = _safe_rq_call("get_price_change_rate", lambda: rqdatac.get_price_change_rate(order_book_id, start_date=start_date, end_date=end_date))
    margin = _safe_rq_call("get_securities_margin", lambda: rqdatac.get_securities_margin(order_book_id, start_date=start_date, end_date=end_date))
    dividend = _safe_rq_call("get_dividend", lambda: rqdatac.get_dividend(order_book_id, start_date=fundamentals_start, end_date=end_date))
    shares = _safe_rq_call("get_shares", lambda: rqdatac.get_shares(order_book_id, start_date=fundamentals_start, end_date=end_date))
    suspended = _safe_rq_call("is_suspended", lambda: rqdatac.is_suspended(order_book_id, start_date=start_date, end_date=end_date))
    st_stock = _safe_rq_call("is_st_stock", lambda: rqdatac.is_st_stock(order_book_id, start_date=start_date, end_date=end_date))
    industry = _safe_rq_call("get_instrument_industry", lambda: rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=1, date=end_date))
    interbank_rate = _safe_rq_call("get_interbank_offered_rate", lambda: rqdatac.get_interbank_offered_rate(start_date=macro_start, end_date=end_date))
    yield_curve = _safe_rq_call("get_yield_curve", lambda: rqdatac.get_yield_curve(start_date=macro_start, end_date=end_date))
    factor = rqdatac.get_factor(order_book_id, factors, start_date=end_date, end_date=end_date) if factors else pd.DataFrame()
    factor_history = rqdatac.get_factor(order_book_id, factors, start_date=start_date, end_date=end_date) if factors else pd.DataFrame()

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
        "technical": _technical_summary(frames["price"]),
    }
    from .datastore import persist_market_snapshot

    snapshot_id = persist_market_snapshot(payload, lookback_days=lookback_days, source="data_executor")
    if snapshot_id is not None:
        payload["data_snapshot_id"] = snapshot_id
    _attach_stored_fundamentals(payload, stock_code)
    return payload


def _attach_stored_fundamentals(payload: dict[str, Any], stock_code: str) -> None:
    """挂载本地 SQLite 中的 PIT 财务与年报 MD&A，供基本面章节深度分析。"""
    annual = None
    try:
        from .datastore.db import get_annual_report, get_pit_financials

        annual = get_annual_report(stock_code)
        pit = get_pit_financials(stock_code)
        if pit and pit.get("rows"):
            payload["pit_financials"] = {
                "rows": pit["rows"],
                "row_count": len(pit["rows"]),
                "report_year": pit.get("report_year"),
                "years": pit.get("years"),
            }
    except Exception as exc:
        print(f"[fundamentals] load cache skipped: {type(exc).__name__}: {exc}")

    if not payload.get("pit_financials"):
        try:
            from .cninfo import default_as_of
            from .rqdata_client import fetch_financials

            report_year = int((annual or {}).get("report_year") or default_as_of().year)
            fetched = fetch_financials(stock_code, report_year, years=3)
            payload["pit_financials"] = {
                "rows": fetched.rows,
                "row_count": len(fetched.rows),
                "report_year": report_year,
                "years": 3,
            }
        except Exception as exc:
            print(f"[fundamentals] pit_financials fetch skipped: {type(exc).__name__}: {exc}")

    if not annual:
        return
    from .mda_analysis import build_annual_context_from_store

    ctx = build_annual_context_from_store(annual)
    if ctx:
        payload["annual_report_context"] = ctx
        return

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
    sections = {}
    specs = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    for spec in specs:
        name = str(spec.get("name") or "分析章节")
        agent = str(spec.get("agent") or "section_writer")
        prompt_data = _compact_data_for_prompt(data, charts, name)
        sections[name] = _write_section(agent=agent, section_name=name, data=prompt_data)
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
                "2. **章节衔接**：相邻章节之间是否有过渡句或逻辑联系？例如「基本面与估值」之后是否自然引出「资金与交易结构」。\n"
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
    for name, content in sections.items():
        section_notes = _string_list(feedback.get(name))
        section_relevance = relevance.get(name) if isinstance(relevance.get(name), dict) else {}
        if section_relevance.get("decision") == "rewrite":
            section_notes.append(str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。"))
        if not section_notes and not action_items:
            continue
        prompt_data = _compact_data_for_prompt(data, charts, name)
        try:
            revised[name] = normalize_section_text(
                llm_text(
                    f"你是 revise_agent。请根据验证 Agent 的意见，重写《{name}》章节。"
                    "只能使用 JSON 中已有数据；不要新增未采集来源；不要给买卖建议。"
                    "需要补充图表解读、数据局限和更可追溯的数字表述。"
                    f"{analytical_writing_core()} "
                    f"{section_opening_conclusion_rule()} "
                    f"{section_writing_style_hint(name)} "
                    "优先引用 data.analytical_evidence；多年数据须用 Markdown 表格；"
                    "若有 mda_crosswalk，融入盈利/现金流段落对照 MD&A，勿设独立勾稽章节。"
                    "每一段都必须回到目标股票本身：引用目标股票代码、目标股票的米筐数据字段、目标股票图表或目标股票对应行业归属。"
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
        except Exception:
            revised[name] = normalize_section_text(content, name)
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
        data = data_executor_agent(order_book_id=order_book_id, as_of=as_of, lookback_days=next_lookback, output_dir=output_dir)
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
        blocked=blocked,
        validation=validation,
    )

    sections_inline, unused = apply_chart_placements(
        normalized,
        charts,
        placement,
        data=data,
    )

    executive_summary = generate_multi_executive_summary(data=data, sections=sections_inline)

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


def generate_multi_executive_summary(*, data: dict[str, Any], sections: dict[str, str]) -> str:
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
        "基本面与估值": ["valuation_percentile", "latest_quality_snapshot", "share_structure_pie", "dividend_spread"],
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

def _write_section(*, agent: str, section_name: str, data: dict[str, Any]) -> str:
    if not get_env("OPENAI_API_KEY"):
        return f"{agent} 本地摘要：{section_name} 已基于可用数据完成。"
    style_hint = section_writing_style_hint(section_name)
    try:
        return normalize_section_text(
            llm_text(
                f"你是 {agent}。请写研报中的《{section_name}》章节。"
                "只能使用用户提供的 JSON 数据，不得补充外部来源、宏观、行业、新闻、Wind、券商预测或未采集信息。"
                "所有数值结论必须能从 JSON 中追溯；没有数据就写数据局限。不要给买卖建议。"
                f"{analytical_writing_core()} "
                f"{section_opening_conclusion_rule()} "
                f"{style_hint} "
                "优先引用 analytical_evidence 中的日期、窗口统计与多年表；"
                "若有 mda_crosswalk，在盈利/现金流/风险相关段落中用「报表…，MD&A…」对照写法融入，勿设独立勾稽章节；"
                "有 pit_financials_table / financial_years 时必须输出 Markdown 对比表。"
                "直接输出 Markdown 正文，不要写「好的」「根据您提供的」等开场白，不要重复章节标题。",
                json.dumps(data, ensure_ascii=False)[:24000],
            ),
            section_name,
        )
    except Exception as exc:
        return f"{agent} 章节生成失败，已保留数据摘要。错误：{exc}"


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


def _compact_data_for_prompt(data: dict[str, Any], charts: dict[str, str], section_name: str) -> dict[str, Any]:
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
    if "基本面" in section_name or "风险" in section_name:
        payload["pit_financials"] = data.get("pit_financials")
        ctx = data.get("annual_report_context")
        payload["annual_report_context"] = ctx
        if isinstance(ctx, dict):
            payload["mda_crosswalk"] = ctx.get("mda_crosswalk")
            payload["articulation_checks"] = ctx.get("articulation_checks")
    return payload


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