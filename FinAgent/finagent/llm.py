from __future__ import annotations

import json
import re
from typing import Any

from .env import get_env
from .llm_settings import has_llm_api_key, llm_api_key, llm_base_url, llm_model
from .report_format import normalize_section_text
from .report_writing import (
    FUNDAMENTAL_NARRATIVE_SECTION,
    fundamental_narrative_system_prompt,
    fundamental_narrative_writing_guide,
)
from .signals import rule_engine_llm_guidance


def financial_llm_mode() -> str:
    """data_first：先读 metrics/rows 自行归纳；signal_review：沿用逐条审核规则信号。"""
    raw = (get_env("FINAGENT_FINANCIAL_LLM_MODE", "data_first") or "data_first").strip().lower()
    return "signal_review" if raw in {"signal_review", "signals", "legacy"} else "data_first"


_FINANCIAL_DATA_INTERPRETATION_SYSTEM = (
    "你是财务数据分析助手。请直接阅读逐年 metrics、field_snapshot 与 trend_snapshot，"
    "像分析师一样从数字中归纳趋势、矛盾与风险，而不是复述或逐条点评规则引擎标题。"
    "规则引擎 signals 仅作对照参考，可忽略与数据不符的条目。"
    "输出 JSON；叙述宜有具体年份与比率/增速；避免买卖建议；勿篡改原始数值。"
)

_FINANCIAL_SIGNAL_REVIEW_SYSTEM = (
    "你是财务信号审核智能体：在规则引擎候选信号与财务证据之间做筛选、合并与表述润色，"
    "输出可供报告引用的结构化 JSON。"
    "写作风格建议专业、克制、可追溯；优先解释证据充分且影响较大的信号。"
    "建议勿在无证据时扩展结论、勿改动原始财务数字、勿给出买卖建议；"
    "对规则标记为 high/critical 的负面项宜保留或等价转述（程序层也会做保底）。"
    "同主题重复信号可合并；证据缺口写入 data_notes。"
    "请仅返回 JSON。"
)


def _openai_client(*, timeout: float | None = None):
    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": llm_api_key(),
        "base_url": llm_base_url() or None,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def _financial_llm_completion(
    *,
    agent_name: str,
    system: str,
    user: str,
) -> dict[str, Any]:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for the LLM financial analysis path.")

    client = _openai_client()
    model = llm_model()
    info(f"调用 LLM ({agent_name}): model={model}, mode={financial_llm_mode()}")
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
    data = json.loads(_extract_json_object(content))
    return _normalize_financial_analysis_output(data)


def financial_data_interpretation_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    return _financial_llm_completion(
        agent_name="financial_data_interpretation_agent",
        system=_FINANCIAL_DATA_INTERPRETATION_SYSTEM,
        user=_build_financial_data_first_prompt(framework_text, evidence, company_context),
    )


def financial_signal_review_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    return _financial_llm_completion(
        agent_name="financial_signal_review_agent",
        system=_FINANCIAL_SIGNAL_REVIEW_SYSTEM,
        user=_build_financial_signal_review_prompt(framework_text, evidence, company_context),
    )


def financial_analysis_agent(
    *,
    evidence: dict[str, Any],
    framework_text: str,
    company_context: dict[str, Any],
) -> dict[str, Any]:
    if financial_llm_mode() == "signal_review":
        return financial_signal_review_agent(
            evidence=evidence,
            framework_text=framework_text,
            company_context=company_context,
        )
    return financial_data_interpretation_agent(
        evidence=evidence,
        framework_text=framework_text,
        company_context=company_context,
    )


def fundamental_narrative_analysis(
    mda_text: str,
    financial_analysis: dict[str, Any],
    company_context: dict[str, Any],
) -> str:
    from .progress import info

    section = FUNDAMENTAL_NARRATIVE_SECTION
    if not has_llm_api_key():
        info(f"{section}：未配置 API Key，使用本地规则摘要模式")
        return normalize_section_text(_local_summary(mda_text, financial_analysis, company_context), section)

    client = _openai_client()
    model = llm_model()
    info(f"调用 LLM (fundamental_narrative_analysis): model={model}")
    prompt = _build_fundamental_narrative_prompt(mda_text, financial_analysis, company_context)
    response = client.chat.completions.create(
        **_chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": fundamental_narrative_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=int(get_env("OPENAI_DIRECTOR_MAX_TOKENS", "4096")),
        )
    )
    info(f"{section} LLM 调用完成")
    return normalize_section_text(_clean_model_text(response.choices[0].message.content or ""), section)


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
            "你是年报 MD&A 摘要 Agent。建议只基于给定 MD&A 原文提炼经营要点，避免买卖建议。"
            "输出建议为 Markdown：先 1 句总括，再约 4-6 条 bullet；每条宜精炼并保留关键数字；"
            "尽量避免大段照抄原文；无需输出 JSON 或代码块。",
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


def _build_fundamental_narrative_prompt(
    mda_text: str,
    financial_analysis: dict[str, Any],
    company_context: dict[str, Any],
) -> str:
    metrics = financial_analysis.get("metrics") or []
    crosswalk = financial_analysis.get("mda_crosswalk") or []
    articulation = financial_analysis.get("articulation_checks") or []
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        + (f"核心指标逐年表（{len(metrics)} 年，请以此为主论据）：\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n" if metrics else "")
        + (
            "财务分析归纳（interpretation / key_findings，可优先采用）：\n"
            f"{json.dumps({k: financial_analysis.get(k) for k in ('interpretation', 'key_findings', 'key_risks', 'data_notes') if financial_analysis.get(k)}, ensure_ascii=False, indent=2)}\n\n"
            if any(financial_analysis.get(k) for k in ("interpretation", "key_findings"))
            else ""
        )
        + "其余结构化字段（reviewed_signals 等为辅助，勿逐条复述标题）：\n"
        f"{json.dumps({k: financial_analysis.get(k) for k in ('positive_signals', 'negative_signals', 'reviewed_signals', 'display_signals') if financial_analysis.get(k)}, ensure_ascii=False, indent=2)[:8000]}\n\n"
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
        + fundamental_narrative_writing_guide()
        + "\n\n请从指标表与 MD&A 出发写连贯分析，"
        "按公司实际情况组织正文，重点写清核心矛盾与数据依据；"
        "有 crosswalk 时可在相关段落自然对照；MD&A 未覆盖项可写入数据局限。"
        "以下为写作参考而非硬性模板，段落顺序与篇幅可按证据强弱灵活调整。"
    )


def _build_financial_data_first_prompt(
    framework_text: str, evidence: dict[str, Any], company_context: dict[str, Any]
) -> str:
    metrics = evidence.get("metrics") or []
    rows = evidence.get("rows") or []
    signals = evidence.get("signals") if isinstance(evidence.get("signals"), dict) else {}
    signal_appendix = {
        "signal_summary": signals.get("signal_summary"),
        "structured_signals": (signals.get("structured_signals") or [])[:12],
        "compound_signals": (signals.get("compound_signals") or [])[:8],
    }
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        f"逐年衍生指标 metrics（{len(metrics)} 行，请通读并自行发现模式）：\n"
        f"{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n"
        f"逐年原始字段与趋势快照 rows（{len(rows)} 行）：\n"
        f"{json.dumps(rows, ensure_ascii=False, indent=2)}\n\n"
        "数据质量说明：\n"
        f"{json.dumps(evidence.get('data_quality') or [], ensure_ascii=False, indent=2)}\n\n"
        "知识框架（分析时可参考，不必逐条对应）：\n"
        f"{framework_text[:6000]}\n\n"
        "规则引擎附录（可选对照，勿要求与下列标题一一对应）：\n"
        f"{json.dumps(signal_appendix, ensure_ascii=False, indent=2)}\n\n"
        "请基于 metrics 与 rows 返回 JSON，字段名保持一致：\n"
        "- `interpretation`：2–5 段连贯中文，写清趋势、矛盾、因果猜测（须有数字依据）。\n"
        "- `key_findings`：3–8 条要点，每条含年份/指标/数值，不要写成规则标题复读。\n"
        "- `positive_signals` / `negative_signals`：可选短句列表，从你自己读表得出的结论提炼，"
        "  不必覆盖规则引擎全部条目。\n"
        "- `key_risks`：短语列表；`data_notes`：证据缺口。\n"
        "- `reviewed_signals`：可留空 `[]`；仅当你认为需要结构化存档时再填少量条目。"
    )


def _build_financial_signal_review_prompt(
    framework_text: str, evidence: dict[str, Any], company_context: dict[str, Any]
) -> str:
    return (
        "公司上下文：\n"
        f"{json.dumps(company_context, ensure_ascii=False, indent=2)}\n\n"
        "财务证据：\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        "知识框架原文：\n"
        f"{framework_text}\n\n"
        f"{rule_engine_llm_guidance()}\n\n"
        "请审核规则引擎输出的结构化信号，并返回 JSON。"
        "输出格式（字段名需保持一致，便于程序解析）："
        "`reviewed_signals`、`positive_signals`、`negative_signals`、`key_risks`、`data_notes`。"
        "`reviewed_signals` 为对象数组，每项建议包含："
        "`category`、`polarity`、`severity`、`title`、`explanation`、`evidence`、`metrics`、`confidence`。"
        "其余四个顶层字段建议为字符串数组。"
        "审核参考（非硬性清单，可与证据权衡）："
        "1. 结论宜有证据或框架支撑，避免买卖建议。"
        "2. 避免无依据的推断；证据缺口可写入 data_notes。"
        "3. 对 high / critical 负面项建议保留或等价表述（勿无声略过）。"
        "4. key_risks 宜用短语而非长句。"
        "5. 可优先解释高强度负面与异常组合信号。"
        "6. 同 category 相近主题可合并，title/explanation 宜精炼。"
    )


def _normalize_financial_analysis_output(data: dict[str, Any]) -> dict[str, Any]:
    interpretation = str(data.get("interpretation") or "").strip()
    return {
        "interpretation": interpretation,
        "key_findings": _ensure_list_of_strings(data.get("key_findings")),
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
    interpretation = str(financial_analysis.get("interpretation") or "").strip()
    findings = financial_analysis.get("key_findings") or []
    positives = "；".join(financial_analysis.get("positive_signals", [])[:4])
    negatives = "；".join(financial_analysis.get("negative_signals", [])[:4])
    mda_preview = _local_mda_summary(mda_text)
    name = company_context.get("sec_name") or company_context.get("stock_code")
    body = ""
    if interpretation:
        body = f"{interpretation}\n\n"
    elif findings:
        body = "\n".join(f"- {item}" for item in findings[:6]) + "\n\n"
    else:
        body = (
            f"积极面：{positives or '（见指标表）'}。\n\n"
            f"需关注：{negatives or '（见指标表）'}。\n\n"
        )
    return (
        f"本地摘要模式：{name}\n\n{body}"
        f"MD&A 摘要：\n{mda_preview}\n\n"
        "由于未配置 OPENAI_API_KEY，本次未调用外部大模型；以上为基于规则/指标表的占位总结。"
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
