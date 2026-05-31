"""线程池并发：入库、米筐拉取、多智能体章节写作。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

from .env import get_env

T = TypeVar("T")


def finagent_max_workers(*, default: int = 4, cap: int = 12) -> int:
    raw = str(get_env("FINAGENT_MAX_WORKERS", str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(1, min(value, cap))


def env_flag(name: str, *, default: bool = True) -> bool:
    raw = str(get_env(name, "true" if default else "false") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return default


def parallel_map(
    tasks: dict[str, Callable[[], T]],
    *,
    max_workers: int | None = None,
    parallel: bool = True,
) -> dict[str, T | BaseException]:
    if not tasks:
        return {}
    if not parallel or len(tasks) == 1:
        return {key: _call_task(fn) for key, fn in tasks.items()}

    workers = min(len(tasks), max_workers or finagent_max_workers())
    out: dict[str, T | BaseException] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_call_task, fn): key for key, fn in tasks.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                out[key] = future.result()
            except BaseException as exc:
                out[key] = exc
    return out


def _call_task(fn: Callable[[], T]) -> T:
    return fn()
