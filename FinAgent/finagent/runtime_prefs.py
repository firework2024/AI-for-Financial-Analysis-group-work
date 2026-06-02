"""按用户设置覆盖 .env 运行时参数（ContextVar，供后台任务线程使用）。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from .env import get_env

_PREFS: ContextVar[dict[str, str] | None] = ContextVar("finagent_runtime_prefs", default=None)

RUNTIME_PREF_KEYS = (
    "FINAGENT_MAX_WORKERS",
    "FINAGENT_AUTO_INGEST_ON_NEW_CHAT",
    "FINAGENT_ANNUAL_MAX_AGE_DAYS",
    "FINAGENT_VALIDATION_MAX_ROUNDS",
    "FINAGENT_CHART_PLACEMENT_MAX_ROUNDS",
    "FINAGENT_VALIDATION_SKIP_REVISE_MIN_SCORE",
    "FINAGENT_BOOTSTRAP_LOOKBACK_DAYS",
    "FINAGENT_SECTION_PARALLEL",
    "FINAGENT_RQDATA_PARALLEL",
    "FINAGENT_INGEST_PARALLEL",
)


def pref_str(name: str, default: str = "") -> str:
    ctx = _PREFS.get()
    if ctx and name in ctx and ctx[name] is not None:
        return str(ctx[name]).strip()
    return str(get_env(name, default) or default).strip()


def pref_bool(name: str, *, default: bool = True) -> bool:
    raw = pref_str(name, "true" if default else "false").lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return default


def pref_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = pref_str(name, str(default))
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@contextmanager
def use_runtime_prefs(prefs: dict[str, str] | None) -> Iterator[None]:
    token = _PREFS.set(prefs)
    try:
        yield
    finally:
        _PREFS.reset(token)


def resolve_runtime_prefs_map(raw: dict[str, Any] | None) -> dict[str, str]:
    """合并 .env 默认值与用户 performance 字段。"""
    perf = raw.get("performance") if isinstance(raw, dict) else {}
    if not isinstance(perf, dict):
        perf = {}
    out: dict[str, str] = {}
    for key in RUNTIME_PREF_KEYS:
        env_default = get_env(key)
        if key in perf and perf[key] is not None and str(perf[key]).strip() != "":
            out[key] = str(perf[key]).strip()
        elif env_default is not None:
            out[key] = str(env_default).strip()
    return out
