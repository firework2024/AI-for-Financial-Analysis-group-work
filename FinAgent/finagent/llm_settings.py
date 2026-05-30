"""运行时 LLM 配置：优先用户设置，回退到 .env。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from .env import get_env

_current_llm_settings: ContextVar["LLMSettings | None"] = ContextVar("current_llm_settings", default=None)


@dataclass
class LLMSettings:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None

    @classmethod
    def from_env(cls) -> LLMSettings:
        return cls(
            api_key=get_env("OPENAI_API_KEY"),
            base_url=get_env("OPENAI_BASE_URL"),
            model=get_env("OPENAI_MODEL", "gpt-4.1-mini"),
        )

    def merged(self) -> LLMSettings:
        env = LLMSettings.from_env()
        return LLMSettings(
            api_key=self.api_key or env.api_key,
            base_url=self.base_url or env.base_url,
            model=self.model or env.model or "gpt-4.1-mini",
        )


def get_llm_settings() -> LLMSettings:
    current = _current_llm_settings.get()
    if current is not None:
        return current.merged()
    return LLMSettings.from_env().merged()


def has_llm_api_key() -> bool:
    return bool(get_llm_settings().api_key)


def llm_api_key() -> str | None:
    return get_llm_settings().api_key


def llm_base_url() -> str | None:
    value = get_llm_settings().base_url
    return value or None


def llm_model(default: str = "gpt-4.1-mini") -> str:
    return get_llm_settings().model or default


@contextmanager
def use_llm_settings(settings: LLMSettings | None) -> Iterator[None]:
    token = _current_llm_settings.set(settings)
    try:
        yield
    finally:
        _current_llm_settings.reset(token)


def activate_llm_settings(settings: LLMSettings | None):
    return _current_llm_settings.set(settings)


def reset_llm_settings(token) -> None:
    _current_llm_settings.reset(token)
