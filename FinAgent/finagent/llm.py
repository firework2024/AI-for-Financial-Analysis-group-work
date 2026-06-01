from __future__ import annotations

import json
import re
from typing import Any

from .env import get_env
from .llm_settings import has_llm_api_key, llm_api_key, llm_base_url, llm_model
from .report_format import normalize_section_text
from .report_writing import annual_director_structure_guide, annual_director_system_prompt


def _openai_client(*, timeout: float | None = None):
    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": llm_api_key(),
        "base_url": llm_base_url() or None,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def financial_signal_review_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for the LLM financial analysis path.")

    client = _openai_client()
    model = llm_model()
    info(f"调用 LLM (financial_signal_review_agent): model={model}")
    prompt = _build_financial_prompt(framework_text, evidence, company_context)
    response = client.chat.completions.create(
        **_chat_completion_kwargs(
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
            response_format={"type": "json_object"},
        )
    )
    content = _clean_model_text(response.choices[0].message.content or "{}")
    data = json.loads(_extract_json_object(content))
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
    from .progress import info

    if not has_llm_api_key():
        info("投资总监分析：未配置 API Key，使用本地规则摘要模式")
        return normalize_section_text(_local_summary(mda_text, financial_analysis, company_context), "投资总监分析")

    client = _openai_client()
    model = llm_model()
    info(f"调用 LLM (investment_director_analysis): model={model}")
    prompt = _build_prompt(mda_text, financial_analysis, company_context)
    response = client.chat.completions.create(
        **_chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": annual_director_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=int(get_env("OPENAI_DIRECTOR_MAX_TOKENS", "4096")),
        )
    )
    info("投资总监分析 LLM 调用完成")
    return normalize_section_text(_clean_model_text(response.choices[0].message.content or ""), "投资总监分析")


def mda_summary_agent(mda_text: str, company_context: dict[str, Any]) -> str:
    from .progress import info

    if not has_llm_api_key():
        info("MD&A 摘要：未配置 API Key，使用本地规则摘要模式")
        return normalize_section_text(_local_mda_summary(mda_text), "MD&A 摘要")
    try:
        name = company_context.get("sec_name") or company_context.get("stock_code") or "目标公司"
        year = company_context.get("report_year") or ""
        info("调用 LLM (mda_summary_agent)")
        result = llm_text(
            "你是年报 MD&A 摘要 Agent。只基于给定 MD&A 原文提炼经营要点，不给买卖建议。"
            "输出 Markdown：先 1 句总括，再 4-6 条 bullet；每条不超过 45 字，保留关键数字；"
            "不要复制大段原文，不要输出 JSON 或代码块。",
            f"公司：{name}（{year} 年报）\n\nMD&A 原文：\n{mda_text[:15000]}",
        )
        normalized = normalize_section_text(result, "MD&A 摘要")
        if _looks_like_raw_mda_dump(normalized):
            return normalize_section_text(_local_mda_summary(mda_text), "MD&A 摘要")
        return normalized
    except Exception:
        return normalize_section_text(_local_mda_summary(mda_text), "MD&A 摘要")


def llm_text(system: str, user: str) -> str:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for LLM text generation.")
    client = _openai_client(timeout=float(get_env("OPENAI_TIMEOUT", "1800")))
    model = llm_model()
    info(f"  → LLM 文本生成: model={model}, 系统={len(system)}B, 用户={len(user)}B")
    response = client.chat.completions.create(
        **_chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    )
    result = _clean_model_text(response.choices[0].message.content or "")
    info(f"  ← LLM 返回: {len(result)} 字符")
    return result


def llm_json(system: str, user: str) -> dict[str, Any]:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for LLM JSON generation.")
    client = _openai_client(timeout=float(get_env("OPENAI_TIMEOUT", "1800")))
    model = llm_model()
    info(f"  → LLM JSON: model={model}, 系统={len(system)}B, 用户={len(user)}B")
    response = client.chat.completions.create(
        **_chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
    )
    content = _clean_model_text(response.choices[0].message.content or "{}")
    info(f"  ← LLM 返回: {len(content)} 字符")
    return json.loads(_extract_json_object(content))


def _chat_completion_kwargs(
    *,
    model: str,
    messages: list[dict[str, str]],
    response_format: dict[str, str] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens if max_tokens is not None else int(get_env("OPENAI_MAX_TOKENS", "2600")),
    }
    base_url = (llm_base_url() or "").lower()
    if "moonshot" in base_url or "kimi" in model.lower():
        kwargs["temperature"] = 1
    if response_format is not None:
        kwargs["response_format"] = response_format
    return kwargs


def _clean_model_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^\s*```(?:json|markdown|md)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> str:
    cleaned = _clean_model_text(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM did not return a JSON object")
    return cleaned[start : end + 1]


def _build_prompt(mda_text: str, financial_analysis: dict[str, Any], company_context: dict[str, Any]) -> str:
    metrics = financial_analysis.get("metrics") or []
    crosswalk = financial_analysis.get("mda_crosswalk") or []
    articulation = financial_analysis.get("articulation_checks") or []
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        "财务数据分析智能体输出（含 signals / metrics / data_notes，请优先引用 metrics 与 reviewed_signals 中的数字）：\n"
        f"{json.dumps(financial_analysis, ensure_ascii=False, indent=2)[:14000]}\n\n"
        + (f"核心指标逐年表（{len(metrics)} 年）：\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n" if metrics else "")
        + (
            "报表勾稽对照素材（融入各段分析，勿单独成章）：\n"
            f"{json.dumps(crosswalk[:12], ensure_ascii=False, indent=2)}\n\n"
            if crosswalk
            else ""
        )
        + (
            f"结构化勾稽项摘要：\n{json.dumps(articulation, ensure_ascii=False, indent=2)}\n\n"
            if articulation
            else ""
        )
        + "MD&A 文本：\n"
        f"{mda_text[:12000]}\n\n"
        + annual_director_structure_guide()
        + "\n\n请融合财务信号、报表勾稽与 MD&A："
        "将 mda_crosswalk 中的对照信息写入「利润驱动」「现金流质量」「营运资本」等对应段落，"
        "用「报表显示…，MD&A 称…，因此…」的句式；禁止单独设「MD&A与报表勾稽」章节或小标题。"
        "MD&A 未覆盖项写入数据局限。按上述结构输出完整分析。"
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
        "7. 同一 category 的重复信号应合并为一条，title/explanation 保持精炼，避免同主题多条罗列。"
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
    mda_preview = _local_mda_summary(mda_text)
    name = company_context.get("sec_name") or company_context.get("stock_code")
    return (
        f"本地摘要模式：{name} 的财务数据积极信号主要包括：{positives}。\n\n"
        f"消极或需要关注的数据信号主要包括：{negatives}。\n\n"
        f"MD&A 摘要：\n{mda_preview}\n\n"
        "由于未配置 OPENAI_API_KEY，本次未调用外部大模型；以上为基于规则输出的投资总监占位总结。"
    )


_MDA_SUMMARY_KEYWORDS = (
    "收入",
    "营收",
    "利润",
    "现金流",
    "风险",
    "同比",
    "下降",
    "增长",
    "融资",
    "债务",
    "毛利率",
    "挑战",
    "举措",
    "交付",
    "销售",
    "展期",
    "流动性",
)


def _local_mda_summary(mda_text: str) -> str:
    cleaned = _normalize_mda_source_text(mda_text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", cleaned) if len(part.strip()) > 24]
    paragraphs = [part for part in paragraphs if not re.search(r"年度报告\s*\d+", part)]
    if not paragraphs and len(cleaned) > 24:
        paragraphs = [cleaned]
    sentences: list[str] = []
    for paragraph in paragraphs[:15]:
        for sentence in re.split(r"(?<=[。！？!?])", paragraph):
            text = sentence.strip()
            if len(text) < 12:
                continue
            if _is_mda_summary_sentence(text):
                normalized = re.sub(r"\s+", "", text)
                if normalized not in {re.sub(r"\s+", "", item) for item in sentences}:
                    sentences.append(text)
            if len(sentences) >= 6:
                break
        if len(sentences) >= 6:
            break
    if not sentences:
        fallback = paragraphs[0][:160].strip() if paragraphs else "未能从 MD&A 中提取有效摘要。"
        return fallback + ("…" if paragraphs and len(paragraphs[0]) > 160 else "")
    headline = sentences[0].rstrip("。！？!?")
    lines = [f"{headline}。", ""]
    for sentence in sentences[1:6]:
        lines.append(f"- {sentence.rstrip('。！？!?')}。")
    return "\n".join(lines)


def _normalize_mda_source_text(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n")
    cleaned = re.sub(r"[^\n]{0,40}年度报告\s*\d+", "\n", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"(?<=[。！？!?])\s*(?=[（(]?[一二三四五六七八九十]+[、）)])", "\n\n", cleaned)
    cleaned = re.sub(r"(?<=[。！？!?])\s*(?=\d+[、.])", "\n\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    return cleaned.strip()


def _looks_like_raw_mda_dump(text: str) -> bool:
    if len(text) < 250:
        return False
    if re.search(r"^[-*]\s", text, re.MULTILINE):
        return False
    if "董事会报告" in text and "经营情况讨论与分析" in text:
        return True
    if "年度报告" in text and re.search(r"\d+\s*/\s*\d+", text):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) <= 2 and len(text) > 400


def _is_mda_summary_sentence(text: str) -> bool:
    if re.search(r"\d", text) and any(keyword in text for keyword in _MDA_SUMMARY_KEYWORDS):
        return True
    return any(keyword in text for keyword in ("风险", "挑战", "压力", "改善", "下降", "增长", "展期"))
