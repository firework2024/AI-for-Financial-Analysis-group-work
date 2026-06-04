"""多智能体报告：各 Agent 的 system / user prompt 构建（单一来源）。"""

from __future__ import annotations

import json
from typing import Any

from .multiagent_config import TOOL_REGISTRY
from .narrative_plan import (
    build_plan_data_briefing,
    data_briefing_planner_preamble,
    is_operating_quality_section,
)
from .report_format import section_writing_style_hint
from .report_writing import (
    analytical_writing_core,
    fundamental_narrative_system_prompt,
    llm_table_writing_rule,
    section_opening_conclusion_rule,
)
from .section_prompts import (
    industry_comparison_writer_guidance,
    macro_rate_writer_guidance,
    mda_business_writer_guidance,
    operating_quality_writer_guidance,
)
from .section_validation import (
    CHART_QUALITY_REQUIREMENTS,
    coerce_string_list,
    rewrite_constraints_for_section,
    revise_section_guidance,
    section_scope_writer_guidance,
    structural_notes_for_section,
)

_DATA_INTEGRITY_RULES = (
    "只能使用用户提供的 JSON 数据，不得补充外部来源、宏观、行业、新闻、Wind、券商预测或未采集信息。"
    "所有数值结论必须能从 JSON 中追溯；没有数据就写数据局限。不要给买卖建议。"
    "正文和表格展示层不要输出 raw JSON 字段路径或嵌套键名，例如 factor_trend.latest.xxx、data.xxx、margin_trajectory.xxx；"
    "需要说明来源时用自然语言口径描述，例如“最新估值因子”“两融轨迹”“同比增长因子”。"
)

_MDA_WRITING_RULES = (
    "若有 mda_business_brief、mda_crosswalk 或 mda_full_text，在相关段落做「量化数据 + MD&A 基本业务/业务发展/风险披露 + 独立判断」三者对照，"
    "作为本节论述支撑，勿设独立勾稽章节；数值结论必须可从 JSON 追溯；"
    + llm_table_writing_rule()
    + "pit_financials_table / financial_years 等多指标对比可用 Markdown 表格或句子/列表表述。"
)

_OUTPUT_FORMAT_RULES = (
    "直接输出 Markdown 正文，不要写「好的」「根据您提供的」「根据您的反馈」「遵照您的指示」等开场白，不要重复章节标题。"
)


def section_writer_max_chars(section_name: str, plan: dict[str, Any] | None) -> int:
    return 36000 if is_operating_quality_section(section_name, plan) else 24000


def section_writer_role_prompt(agent: str, section_name: str, plan: dict[str, Any] | None) -> str:
    if is_operating_quality_section(section_name, plan):
        return fundamental_narrative_system_prompt()
    return f"你是 {agent}。请写研报中的《{section_name}》章节。"


def section_guidance_bundle(section_name: str, data: dict[str, Any], plan: dict[str, Any] | None) -> str:
    parts = [
        operating_quality_writer_guidance() if is_operating_quality_section(section_name, plan) else "",
        industry_comparison_writer_guidance(section_name, data, plan=plan),
        macro_rate_writer_guidance(section_name, data, plan=plan),
        mda_business_writer_guidance(section_name, data, plan=plan),
        section_scope_writer_guidance(section_name, plan=plan),
    ]
    return "".join(parts)


def section_writer_system_prompt(*, agent: str, section_name: str, data: dict[str, Any], plan: dict[str, Any] | None) -> str:
    style_hint = section_writing_style_hint(section_name)
    guidance = section_guidance_bundle(section_name, data, plan)
    return (
        section_writer_role_prompt(agent, section_name, plan)
        + " "
        + _DATA_INTEGRITY_RULES
        + f"{analytical_writing_core()} "
        + f"{section_opening_conclusion_rule()} "
        + f"{style_hint} "
        + f"{guidance}"
        + "优先使用 annual_financial_analysis 中的完整财务画像（全部 reviewed_signals、metrics、articulation_checks），"
        + "以及 analytical_evidence 中的日期、窗口统计与多年表；"
        + _MDA_WRITING_RULES
        + _OUTPUT_FORMAT_RULES
    )


def revise_section_system_prompt(
    *,
    section_name: str,
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    guidance = section_guidance_bundle(section_name, data, plan)
    hard_constraints = revise_section_guidance(section_name, sections=sections, plan=plan, validation=validation)
    return (
        f"你是 revise_agent。请根据验证 Agent 的意见，重写《{section_name}》章节。"
        + _DATA_INTEGRITY_RULES
        + "若验证意见要求删去与其他章节重复的内容，必须删除重复段落与同表头 Markdown 表，不得只改措辞；"
        + "不要把其他章节已写过的两融/估值/盈利/量价/宏观利率段落或表格复制到本章。"
        + "需要补充图表解读、数据局限和更可追溯的数字表述。"
        + f"{analytical_writing_core()} "
        + f"{section_opening_conclusion_rule()} "
        + f"{section_writing_style_hint(section_name)} "
        + f"{guidance}"
        + f"{hard_constraints}"
        + f"{llm_table_writing_rule()} "
        + "优先引用 data.analytical_evidence；多年数据可用 Markdown 表格或句子/列表表述。"
        + "若有 mda_business_brief 或 mda_crosswalk，在相关段落融入基本业务/业务发展等 MD&A 表述作论述支撑，"
        + "形成「报表或行情数据 + 管理层解释 + 独立判断」，勿设独立勾稽章节。"
        + "每一段都必须回到目标股票本身：引用目标股票代码、具体指标、目标股票图表或目标股票对应行业归属。"
        + "如果原文有泛泛讲宏观、行业、市场或方法论但没有连接目标股票的句子，请删除或改写。"
        + _OUTPUT_FORMAT_RULES
    )


def revise_section_user_payload(
    *,
    section_name: str,
    content: str,
    section_notes: list[str],
    section_relevance: dict[str, Any],
    action_items: list[Any],
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "section_name": section_name,
            "original_section": content,
            "section_feedback": section_notes,
            "stock_relevance_feedback": section_relevance,
            "global_action_items": action_items,
            "rewrite_constraints": rewrite_constraints_for_section(
                section_name, sections=sections, plan=plan, validation=validation
            ),
            "data": data,
        },
        ensure_ascii=False,
    )[:18000]


def build_revise_section_notes(
    *,
    section_name: str,
    feedback: dict[str, Any],
    structural: list[Any],
    relevance: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    section_notes = coerce_string_list(feedback.get(section_name))
    section_notes.extend(structural_notes_for_section(structural, section_name))
    section_relevance = relevance.get(section_name) if isinstance(relevance.get(section_name), dict) else {}
    if section_relevance.get("decision") == "rewrite":
        section_notes.append(
            str(section_relevance.get("reason") or "本节需要改写为紧扣目标股票的数据、图表和结论。")
        )
    return section_notes, section_relevance


def planner_system_prompt() -> str:
    return "你是金融研究系统的计划 Agent。只返回 JSON，不要写 Markdown。"


def planner_user_payload(
    *,
    stock_code: str,
    order_book_id: str,
    as_of_iso: str,
    lookback_days: int,
    data: dict[str, Any] | None,
) -> str:
    briefing_block = ""
    if data:
        briefing = build_plan_data_briefing(data)
        briefing_block = (
            data_briefing_planner_preamble()
            + f"\n{json.dumps(briefing, ensure_ascii=False)[:8000]}"
        )
    return (
        "请为 A 股研究报告制定多智能体执行计划。"
        f"\n股票: {stock_code} / {order_book_id}"
        f"\n截至日期: {as_of_iso}，回看天数: {lookback_days}"
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
        "\n若 briefing 含 annual_report_context 或 MD&A，各 kind 章节均应在正文中引用基本业务/业务发展等管理层表述支撑论述"
        "（经营质量章深度勾稽，其他章 1–2 处点到，勿各章大段复制相同 MD&A）。"
        "\ndata 仅填可用米筐函数名；sections 须按本轮数据覆盖与研究重点自由规划（数量、名称、顺序均可变，勿默认五段式）。"
        "\n禁止规划宏观、行业、新闻、Wind、券商预测等未在可用函数中的数据。"
        + briefing_block
    )


def final_synthesis_system_prompt() -> str:
    return (
        "你是最终汇总 Agent。只能基于输入 JSON 和各分段结论写执行摘要，不给买卖建议。"
        "禁止添加宏观、行业、新闻、Wind、券商预测、管理层指引等输入中不存在的信息。"
        "如果某类信息没有采集，就明确写为数据局限。"
    )
