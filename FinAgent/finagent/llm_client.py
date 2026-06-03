"""OpenAI 兼容 LLM 传输层：文本 / JSON 调用与响应清洗。"""

from __future__ import annotations

import json
import re
from typing import Any

from .env import get_env
from .llm_settings import has_llm_api_key, llm_api_key, llm_base_url, llm_model


def openai_client(*, timeout: float | None = None):
    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": llm_api_key(),
        "base_url": llm_base_url() or None,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def chat_completion_kwargs(
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


def clean_model_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^\s*```(?:json|markdown|md)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> str:
    cleaned = clean_model_text(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM did not return a JSON object")
    return cleaned[start : end + 1]


def llm_text(system: str, user: str) -> str:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for LLM text generation.")
    client = openai_client(timeout=float(get_env("OPENAI_TIMEOUT", "1800")))
    model = llm_model()
    info(f"  → LLM 文本生成: model={model}, 系统={len(system)}B, 用户={len(user)}B")
    response = client.chat.completions.create(
        **chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    )
    result = clean_model_text(response.choices[0].message.content or "")
    info(f"  ← LLM 返回: {len(result)} 字符")
    return result


def llm_json(system: str, user: str) -> dict[str, Any]:
    from .progress import info

    if not has_llm_api_key():
        raise RuntimeError("OPENAI_API_KEY is required for LLM JSON generation.")
    client = openai_client(timeout=float(get_env("OPENAI_TIMEOUT", "1800")))
    model = llm_model()
    info(f"  → LLM JSON: model={model}, 系统={len(system)}B, 用户={len(user)}B")
    response = client.chat.completions.create(
        **chat_completion_kwargs(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
    )
    content = clean_model_text(response.choices[0].message.content or "{}")
    info(f"  ← LLM 返回: {len(content)} 字符")
    return json.loads(extract_json_object(content))
