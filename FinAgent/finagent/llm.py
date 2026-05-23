from __future__ import annotations

import json
import os
from typing import Any

from .env import get_env


def financial_analysis_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    if not get_env("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the LLM financial analysis path.")

    from openai import OpenAI

    client = OpenAI(
        api_key=get_env("OPENAI_API_KEY"),
        base_url=get_env("OPENAI_BASE_URL") or None,
    )
    model = get_env("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = _build_financial_prompt(framework_text, evidence, company_context)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是财务分析智能体。你的任务是严格依据给定的知识框架与证据，"
                    "只输出对财务数据的分析结论，不做买卖建议，不做经营归因，不使用框架之外的判断。"
                    "请仅返回 JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    return _normalize_financial_analysis_output(data)


def investment_director_analysis(mda_text: str, financial_analysis: dict[str, Any], company_context: dict[str, Any]) -> str:
    if not get_env("OPENAI_API_KEY"):
        return _local_summary(mda_text, financial_analysis, company_context)

    from openai import OpenAI

    client = OpenAI(
        api_key=get_env("OPENAI_API_KEY"),
        base_url=get_env("OPENAI_BASE_URL") or None,
    )
    model = get_env("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = _build_prompt(mda_text, financial_analysis, company_context)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是投资总监。请基于 MD&A 与财务数据解释经营表现，给出克制、可追溯的总结分析，不给买卖建议。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def _build_prompt(mda_text: str, financial_analysis: dict[str, Any], company_context: dict[str, Any]) -> str:
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        "财务数据分析智能体输出：\n"
        f"{json.dumps(financial_analysis, ensure_ascii=False, indent=2)}\n\n"
        "MD&A 文本：\n"
        f"{mda_text[:12000]}\n\n"
        "请融合财务数据分析智能体给出的数据信号与MD&A的信息进行全面的总结分析。"
    )


def _build_financial_prompt(framework_text: str, evidence: dict[str, Any], company_context: dict[str, Any]) -> str:
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        "财务证据：\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        "知识框架原文：\n"
        f"{framework_text}\n\n"
        "请按照知识框架对财务证据进行分析，输出 JSON，必须包含："
        "`positive_signals`、`negative_signals`、`data_notes`。"
        "每个字段都必须是数组。"
        "要求："
        "1. 只根据证据和框架下结论，不要添加买卖建议。"
        "2. 如果某项证据缺失，写入 data_notes，不要编造。"
        "3. 结论要围绕你收到的框架所强调的财务质量、勾稽关系、比率和风险信号。"
        "4. 尽量完整地覆盖知识框架里的所有要点，除非数据缺失或信号不显著"
    )


def _normalize_financial_analysis_output(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "positive_signals": _ensure_list_of_strings(data.get("positive_signals")),
        "negative_signals": _ensure_list_of_strings(data.get("negative_signals")),
        "data_notes": _ensure_list_of_strings(data.get("data_notes")),
    }


def _ensure_list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _local_summary(mda_text: str, financial_analysis: dict[str, Any], company_context: dict[str, Any]) -> str:
    positives = "；".join(financial_analysis.get("positive_signals", [])[:4])
    negatives = "；".join(financial_analysis.get("negative_signals", [])[:4])
    mda_preview = " ".join(mda_text.split())[:600]
    name = company_context.get("sec_name") or company_context.get("stock_code")
    return (
        f"本地摘要模式：{name} 的财务数据积极信号主要包括：{positives}。\n\n"
        f"消极或需要关注的数据信号主要包括：{negatives}。\n\n"
        f"MD&A 摘要片段：{mda_preview}\n\n"
        "由于未配置 OPENAI_API_KEY，本次未调用外部大模型；以上为基于规则输出的投资总监占位总结。"
    )
