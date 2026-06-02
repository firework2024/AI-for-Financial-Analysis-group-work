from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..env import get_env
from ..llm_settings import LLMSettings
from ..runtime_prefs import resolve_runtime_prefs_map
from .crypto import decrypt_secret, encrypt_secret

PERFORMANCE_FIELD_MAP = {
    "max_workers": "FINAGENT_MAX_WORKERS",
    "auto_ingest_on_new_chat": "FINAGENT_AUTO_INGEST_ON_NEW_CHAT",
    "annual_max_age_days": "FINAGENT_ANNUAL_MAX_AGE_DAYS",
    "validation_max_rounds": "FINAGENT_VALIDATION_MAX_ROUNDS",
    "chart_placement_max_rounds": "FINAGENT_CHART_PLACEMENT_MAX_ROUNDS",
    "validation_skip_revise_min_score": "FINAGENT_VALIDATION_SKIP_REVISE_MIN_SCORE",
    "bootstrap_lookback_days": "FINAGENT_BOOTSTRAP_LOOKBACK_DAYS",
}


@dataclass
class UserAPISettings:
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    chat_agent_mode: str | None = None
    chat_max_steps: int | None = None
    updated_at: str | None = None


class UserSettingsStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user_id: str) -> Path:
        return self.root / f"{Path(user_id).name}.json"

    def load_raw(self, user_id: str) -> dict[str, Any]:
        path = self._path(user_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def load(self, user_id: str) -> UserAPISettings:
        payload = self.load_raw(user_id)
        encrypted = str(payload.get("openai_api_key_enc") or "")
        api_key = decrypt_secret(encrypted) if encrypted else None
        mode = str(payload.get("chat_agent_mode") or "").strip().lower()
        if mode not in {"loop", "single"}:
            mode = None
        raw_steps = payload.get("chat_max_steps")
        steps: int | None = None
        if raw_steps is not None and str(raw_steps).strip() != "":
            try:
                steps = max(1, min(8, int(raw_steps)))
            except (TypeError, ValueError):
                steps = None
        return UserAPISettings(
            openai_api_key=api_key or None,
            openai_base_url=payload.get("openai_base_url") or None,
            openai_model=payload.get("openai_model") or None,
            chat_agent_mode=mode,
            chat_max_steps=steps,
            updated_at=payload.get("updated_at"),
        )

    def save(self, user_id: str, settings: UserAPISettings) -> None:
        from datetime import datetime

        payload = {
            "openai_base_url": settings.openai_base_url or "",
            "openai_model": settings.openai_model or "",
            "chat_agent_mode": settings.chat_agent_mode or "",
            "chat_max_steps": settings.chat_max_steps if settings.chat_max_steps is not None else "",
            "updated_at": settings.updated_at or datetime.now().isoformat(timespec="seconds"),
        }
        if settings.openai_api_key is not None:
            payload["openai_api_key_enc"] = encrypt_secret(settings.openai_api_key) if settings.openai_api_key else ""
        else:
            existing = self.load_raw(user_id)
            if "openai_api_key_enc" in existing:
                payload["openai_api_key_enc"] = existing["openai_api_key_enc"]
        existing = self.load_raw(user_id)
        if isinstance(existing.get("performance"), dict):
            payload["performance"] = existing["performance"]
        path = self._path(user_id)
        with self._lock:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(
        self,
        user_id: str,
        *,
        openai_api_key: str | None = None,
        update_api_key: bool = False,
        clear_api_key: bool = False,
        openai_base_url: str | None = None,
        openai_model: str | None = None,
        chat_agent_mode: str | None = None,
        chat_max_steps: int | None = None,
        performance: dict[str, Any] | None = None,
    ) -> UserAPISettings:
        from datetime import datetime

        current = self.load(user_id)
        if clear_api_key:
            current.openai_api_key = ""
        elif update_api_key and openai_api_key is not None:
            current.openai_api_key = openai_api_key.strip()
        if openai_base_url is not None:
            current.openai_base_url = openai_base_url.strip() or None
        if openai_model is not None:
            current.openai_model = openai_model.strip() or None
        if chat_agent_mode is not None:
            mode = str(chat_agent_mode).strip().lower()
            current.chat_agent_mode = mode if mode in {"loop", "single"} else None
        if chat_max_steps is not None:
            current.chat_max_steps = max(1, min(8, int(chat_max_steps)))
        if performance is not None:
            self._merge_performance(user_id, performance)
        current.updated_at = datetime.now().isoformat(timespec="seconds")
        self.save(user_id, current)
        return current

    def _merge_performance(self, user_id: str, patch: dict[str, Any]) -> None:
        raw = self.load_raw(user_id)
        perf = dict(raw.get("performance") or {}) if isinstance(raw.get("performance"), dict) else {}
        for field, env_key in PERFORMANCE_FIELD_MAP.items():
            if field not in patch or patch[field] is None:
                continue
            value = patch[field]
            if field == "auto_ingest_on_new_chat":
                perf[env_key] = "true" if bool(value) else "false"
            else:
                perf[env_key] = str(value).strip()
        raw["performance"] = perf
        path = self._path(user_id)
        with self._lock:
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def runtime_prefs_map(self, user_id: str) -> dict[str, str]:
        return resolve_runtime_prefs_map(self.load_raw(user_id))

    def to_llm_settings(self, user_id: str) -> LLMSettings:
        settings = self.load(user_id)
        return LLMSettings(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )

    def to_public(self, user_id: str) -> dict[str, Any]:
        settings = self.load(user_id)
        env = LLMSettings.from_env()
        user_key = settings.openai_api_key
        env_key = env.api_key
        effective_key = user_key or env_key
        source = "user" if user_key else ("env" if env_key else "none")
        masked = _mask_api_key(user_key) if user_key else (_mask_api_key(env_key) if env_key else "")
        return {
            "has_api_key": bool(effective_key),
            "has_user_api_key": bool(user_key),
            "has_server_api_key": bool(env_key),
            "api_key_masked": masked,
            "api_key_source": source,
            "openai_base_url": settings.openai_base_url or env.base_url or "",
            "openai_model": settings.openai_model or env.model or "gpt-4.1-mini",
            "chat_agent_mode": settings.chat_agent_mode or _default_chat_agent_mode(),
            "chat_max_steps": settings.chat_max_steps if settings.chat_max_steps is not None else _default_chat_max_steps(),
            "updated_at": settings.updated_at,
            "performance": public_performance_settings(self.load_raw(user_id)),
        }


def public_performance_settings(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """前端展示用：合并 .env 与用户 performance 后的有效值。"""
    effective = resolve_runtime_prefs_map(raw or {})
    auto_raw = effective.get("FINAGENT_AUTO_INGEST_ON_NEW_CHAT", "true").lower()
    return {
        "max_workers": _safe_int(effective.get("FINAGENT_MAX_WORKERS"), 4, 1, 12),
        "auto_ingest_on_new_chat": auto_raw not in {"0", "false", "no", "off"},
        "annual_max_age_days": _safe_int(effective.get("FINAGENT_ANNUAL_MAX_AGE_DAYS"), 120, 0, 3650),
        "validation_max_rounds": _safe_int(effective.get("FINAGENT_VALIDATION_MAX_ROUNDS"), 2, 0, 5),
        "chart_placement_max_rounds": _safe_int(effective.get("FINAGENT_CHART_PLACEMENT_MAX_ROUNDS"), 2, 1, 5),
        "validation_skip_revise_min_score": _safe_int(
            effective.get("FINAGENT_VALIDATION_SKIP_REVISE_MIN_SCORE"), 88, 0, 100
        ),
        "bootstrap_lookback_days": _safe_int(effective.get("FINAGENT_BOOTSTRAP_LOOKBACK_DAYS"), 90, 30, 365),
    }


def _safe_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(float(str(raw or default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _default_chat_agent_mode() -> str:
    mode = (get_env("FINAGENT_CHAT_AGENT_MODE") or "loop").strip().lower()
    return mode if mode in {"loop", "single"} else "loop"


def _default_chat_max_steps() -> int:
    try:
        return max(1, min(8, int(get_env("FINAGENT_CHAT_MAX_STEPS", "4"))))
    except ValueError:
        return 4


def resolve_chat_agent_options(settings: UserAPISettings | None) -> dict[str, Any]:
    """合并用户设置与 .env 默认的对话 Agent 参数。"""
    current = settings or UserAPISettings()
    mode = current.chat_agent_mode or _default_chat_agent_mode()
    steps = current.chat_max_steps if current.chat_max_steps is not None else _default_chat_max_steps()
    return {"chat_agent_mode": mode, "chat_max_steps": steps}


def _mask_api_key(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:3]}…{text[-4:]}"
