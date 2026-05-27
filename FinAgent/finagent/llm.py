from __future__ import annotations

import json
import os
from typing import Any

from .env import get_env


def financial_signal_review_agent(
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
                    "你是财务信号审核智能体，而不是自由分析师。"
                    "你会收到公司上下文、财务证据、规则引擎识别出的结构化信号，以及财务分析知识框架。"
                    "你的任务是审核结构化信号、合并重复信号、按重要性排序，并用专业、克制、可追溯的语言解释信号。"
                    "不得新增没有证据支持的结论，不得修改原始财务数据，不得删除 high 或 critical 的负面信号，不得给出买卖建议。"
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


def financial_analysis_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    return financial_signal_review_agent(
        evidence=evidence,
        framework_text=framework_text,
        company_context=company_context,
    )


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
        "请审核规则引擎输出的结构化信号，输出 JSON，必须包含："
        "`reviewed_signals`、`positive_signals`、`negative_signals`、`key_risks`、`data_notes`。"
        "`reviewed_signals` 必须是数组，每个元素至少包含："
        "`category`、`polarity`、`severity`、`title`、`explanation`、`evidence`、`metrics`、`confidence`。"
        "其余字段都必须是数组。"
        "要求："
        "1. 只根据证据和框架下结论，不要添加买卖建议。"
        "2. 不要新增没有证据支持的结论。"
        "3. high 或 critical 的负面信号必须保留。"
        "4. 如果某项证据缺失，写入 data_notes，不要编造。"
        "5. key_risks 请输出短语，不要输出句子。"
        "6. 尽量优先解释高强度负面信号和异常组合信号。"
    )


def _normalize_financial_analysis_output(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reviewed_signals": _ensure_reviewed_signals(data.get("reviewed_signals")),
        "positive_signals": _ensure_list_of_strings(data.get("positive_signals")),
        "negative_signals": _ensure_list_of_strings(data.get("negative_signals")),
        "key_risks": _ensure_list_of_strings(data.get("key_risks")),
        "data_notes": _ensure_list_of_strings(data.get("data_notes")),
    }


def _ensure_list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _ensure_reviewed_signals(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(
                {
                    "category": str(item.get("category", "")),
                    "category_cn": str(item.get("category_cn", "")) if item.get("category_cn") is not None else "",
                    "polarity": str(item.get("polarity", "")),
                    "severity": str(item.get("severity", "")),
                    "title": str(item.get("title", "")),
                    "explanation": str(item.get("explanation", "")),
                    "evidence": str(item.get("evidence", "")),
                    "metrics": _ensure_list_of_strings(item.get("metrics")),
                    "confidence": str(item.get("confidence", "")) if item.get("confidence") is not None else "",
                    "source_signal_id": str(item.get("source_signal_id", "")) if item.get("source_signal_id") is not None else "",
                    "type": str(item.get("type", "")) if item.get("type") is not None else "",
                }
            )
            continue
        text = str(item).strip()
        if text:
            items.append(
                {
                    "category": "",
                    "category_cn": "",
                    "polarity": "",
                    "severity": "",
                    "title": text,
                    "explanation": text,
                    "evidence": "",
                    "metrics": [],
                    "confidence": "",
                    "source_signal_id": "",
                    "type": "",
                }
            )
    return items


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
