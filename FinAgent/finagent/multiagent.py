from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .chart_plots import chart_agent
from .concurrency import env_flag, finagent_max_workers, parallel_map
from .env import get_env, load_dotenv
from .latex_exporter import export_latex
from .llm import llm_json, llm_text
from .llm_settings import has_llm_api_key
from .multi_report import (
    apply_chart_placements_agent,
    build_multi_json_payload,
    multi_report_display_title,
    render_multi_html,
    render_multi_markdown,
    resolve_multi_report_title,
)
from .multiagent_config import LEGACY_SECTION_TEMPLATES, MultiAgentOptions, OPERATING_QUALITY_SECTION, TOOL_REGISTRY
from .multiagent_data import data_executor_agent, json_ready
from .multiagent_prompts import (
    build_revise_section_notes,
    final_synthesis_system_prompt,
    planner_system_prompt,
    planner_user_payload,
    revise_section_system_prompt,
    revise_section_user_payload,
    section_writer_max_chars,
    section_writer_system_prompt,
)
from .narrative_plan import build_planner_fallback_sections, ensure_macro_section_in_plan
from .plan_execution import filter_prompt_payload, sanitize_plan_sections, section_tools_from_plan
from .report_format import normalize_section_text, normalize_sections
from .report_writing import local_multi_executive_summary, multi_executive_summary_prompt
from .section_prompts import compact_data_for_prompt
from .section_validation import (
    build_validation_llm_user_payload,
    chart_quality_review,
    finalize_validation_after_refinement,
    local_validation,
    prune_charts,
    refinement_requests,
    sanitize_validation,
    validation_agent_system_prompt,
    validation_markdown,
)
from .table_analysis import analyze_table_duplicates, apply_table_dedup
from .stock_utils import default_as_of, normalize_stock_code, resolve_as_of, to_order_book_id
from .visual_placement import resolve_section_visuals


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
    step("执行 table_dedup（保留 info_score 更高的表）")
    table_dup = analyze_table_duplicates(sections, plan=plan)
    sections = apply_table_dedup(sections, table_dup)
    if isinstance(validation, dict):
        validation["table_duplicate_analysis"] = table_dup
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
    json_path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"JSON 数据已写入 ({json_path.stat().st_size} 字节)")

    from .multi_report import normalize_output_relative_path

    payload["output_markdown"] = normalize_output_relative_path(str(output_path))
    payload["output_json"] = normalize_output_relative_path(str(json_path))
    payload["output_html"] = normalize_output_relative_path(
        payload.get("meta", {}).get("output_html") or str(output_path.with_suffix(".html"))
    )

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
    fallback_sections = build_planner_fallback_sections(data)
    fallback = {
        "report_title": "",
        "narrative_thesis": "",
        "objective": "基于已采集数据撰写定制化 A 股研究报告（章节由规划 Agent 据数据覆盖拟定，非固定模板）",
        "tools": list(TOOL_REGISTRY),
        "sections": fallback_sections,
        "risk_controls": ["仅基于可取得数据写结论", "不输出买卖建议", "说明缺失数据"],
    }
    if not has_llm_api_key():
        return _sanitize_plan(fallback, fallback, data=data)
    try:
        plan = llm_json(
            planner_system_prompt(),
            planner_user_payload(
                stock_code=stock_code,
                order_book_id=order_book_id,
                as_of_iso=as_of.isoformat(),
                lookback_days=lookback_days,
                data=data,
            ),
        )
        return _sanitize_plan(plan, fallback, data=data)
    except Exception:
        return _sanitize_plan(fallback, fallback, data=data)


def _sanitize_plan(
    plan: dict[str, Any],
    fallback: dict[str, Any],
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(plan) if isinstance(plan, dict) else {}
    allowed_tools = set(TOOL_REGISTRY)
    result["tools"] = [name for name in result.get("tools", []) if name in allowed_tools] or list(TOOL_REGISTRY)
    result["sections"] = ensure_macro_section_in_plan(
        sanitize_plan_sections(
            result,
            legacy_templates=LEGACY_SECTION_TEMPLATES,
            fallback_sections=build_planner_fallback_sections(data),
            allowed_tools=allowed_tools,
        ),
        data,
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


def section_writer_agents(*, plan: dict[str, Any], data: dict[str, Any], charts: dict[str, str]) -> dict[str, str]:
    specs = plan.get("sections") if isinstance(plan.get("sections"), list) else []
    if not specs:
        return {}

    def _write_spec(spec: dict[str, Any]) -> tuple[str, str]:
        name = str(spec.get("name") or "分析章节")
        agent = str(spec.get("agent") or "section_writer")
        prompt_data = compact_data_for_prompt(data, charts, name, plan=plan)
        section_tools = section_tools_from_plan(plan, name)
        prompt_data = filter_prompt_payload(prompt_data, section_tools)
        return name, _write_section(agent=agent, section_name=name, data=prompt_data, plan=plan)

    parallel = bool(has_llm_api_key()) and env_flag("FINAGENT_SECTION_PARALLEL", default=True)
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
    fallback = local_validation(data=data, charts=charts, sections=sections, draft_markdown=draft_markdown, plan=plan)
    if not has_llm_api_key():
        return fallback
    try:
        validation = llm_json(
            system=validation_agent_system_prompt(),
            user=build_validation_llm_user_payload(
                plan=plan,
                data=data,
                charts=charts,
                sections=sections,
                draft_markdown=draft_markdown,
                fallback=fallback,
            ),
        )
        return sanitize_validation(validation, fallback)
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
    structural = validation.get("structural_feedback") if isinstance(validation.get("structural_feedback"), list) else []
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    if not has_llm_api_key() or not (feedback or action_items or has_relevance_rewrite or structural):
        return sections
    revised = dict(sections)
    rewrite_jobs: dict[str, Callable[[], tuple[str, str]]] = {}

    def _revise_one(name: str, content: str) -> tuple[str, str]:
        section_notes, section_relevance = build_revise_section_notes(
            section_name=name,
            feedback=feedback,
            structural=structural,
            relevance=relevance,
        )
        prompt_data = compact_data_for_prompt(data, charts, name, plan=plan)
        section_tools = section_tools_from_plan(plan, name)
        prompt_data = filter_prompt_payload(prompt_data, section_tools)
        try:
            text = normalize_section_text(
                llm_text(
                    revise_section_system_prompt(
                        section_name=name,
                        data=prompt_data,
                        sections=sections,
                        plan=plan,
                        validation=validation,
                    ),
                    revise_section_user_payload(
                        section_name=name,
                        content=content,
                        section_notes=section_notes,
                        section_relevance=section_relevance,
                        action_items=action_items,
                        data=prompt_data,
                        sections=sections,
                        plan=plan,
                        validation=validation,
                    ),
                ),
                name,
            )
            return name, text
        except Exception:
            return name, normalize_section_text(content, name)

    for name, content in sections.items():
        section_notes, section_relevance = build_revise_section_notes(
            section_name=name,
            feedback=feedback,
            structural=structural,
            relevance=relevance,
        )
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
    requests = refinement_requests(validation)
    if not requests:
        chart_review = chart_quality_review(data=data, charts=charts)
        charts = prune_charts(charts, chart_review)
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
    chart_review = chart_quality_review(data=data, charts=charts)
    charts = prune_charts(charts, chart_review)
    validation["chart_quality_review"] = chart_review
    validation["refinement_performed"] = {
        "refresh_data": bool(requests.get("refresh_data")),
        "refresh_charts": bool(requests.get("refresh_charts")),
        "lookback_days": next_lookback,
        "reason": requests.get("reason"),
    }
    finalize_validation_after_refinement(validation, charts)
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
    if not has_llm_api_key():
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

    if not has_llm_api_key():
        summary = "本报告由本地多智能体流程生成：计划、数据执行、分段写作、图表生成和汇总均已完成。"
    else:
        try:
            summary = llm_text(
                final_synthesis_system_prompt(),
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
    validation_lines = validation_markdown(validation)

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
            "industry_dbscan_anomaly",
            "profitability_factors",
            "growth_factors",
            "liquidity_factors",
            "debt_ratio_trend",
            "revenue_profit_trend",
            "profit_vs_cashflow",
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
    if not has_llm_api_key():
        return f"{agent} 本地摘要：{section_name} 已基于可用数据完成。"
    try:
        return normalize_section_text(
            llm_text(
                section_writer_system_prompt(agent=agent, section_name=section_name, data=data, plan=plan),
                json.dumps(data, ensure_ascii=False)[: section_writer_max_chars(section_name, plan)],
            ),
            section_name,
        )
    except Exception as exc:
        return f"{agent} 章节生成失败，已保留数据摘要。错误：{exc}"


def _markdown_path(path: str, base_dir: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(base_dir.resolve())
    except Exception:
        rel = Path(path)
    return rel.as_posix()


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


