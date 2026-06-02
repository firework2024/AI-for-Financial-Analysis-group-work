"""用户 performance 设置：合并、公开字段与 API 往返。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from finagent.auth.user_settings import (
    UserSettingsStore,
    public_performance_settings,
    resolve_runtime_prefs_map,
)
from finagent.runtime_prefs import pref_int, use_runtime_prefs
from finagent.web.server import create_app


@pytest.fixture()
def settings_store(tmp_path):
    return UserSettingsStore(tmp_path / "user_settings")


def test_public_performance_settings_defaults(monkeypatch):
    monkeypatch.setenv("FINAGENT_MAX_WORKERS", "6")
    monkeypatch.setenv("FINAGENT_AUTO_INGEST_ON_NEW_CHAT", "false")
    monkeypatch.setenv("FINAGENT_ANNUAL_MAX_AGE_DAYS", "90")
    perf = public_performance_settings({})
    assert perf["max_workers"] == 6
    assert perf["auto_ingest_on_new_chat"] is False
    assert perf["annual_max_age_days"] == 90


def test_merge_performance_persists_env_keys(settings_store):
    user_id = "u-perf"
    settings_store.update(
        user_id,
        performance={
            "max_workers": 8,
            "auto_ingest_on_new_chat": False,
            "validation_max_rounds": 1,
            "chart_placement_max_rounds": 3,
            "validation_skip_revise_min_score": 92,
            "bootstrap_lookback_days": 120,
            "annual_max_age_days": 60,
        },
    )
    raw = settings_store.load_raw(user_id)
    perf_block = raw.get("performance") or {}
    assert perf_block["FINAGENT_MAX_WORKERS"] == "8"
    assert perf_block["FINAGENT_AUTO_INGEST_ON_NEW_CHAT"] == "false"
    assert perf_block["FINAGENT_VALIDATION_MAX_ROUNDS"] == "1"

    public = public_performance_settings(raw)
    assert public["max_workers"] == 8
    assert public["auto_ingest_on_new_chat"] is False
    assert public["validation_skip_revise_min_score"] == 92

    prefs = settings_store.runtime_prefs_map(user_id)
    with use_runtime_prefs(prefs):
        assert pref_int("FINAGENT_MAX_WORKERS", 4) == 8
        assert pref_int("FINAGENT_BOOTSTRAP_LOOKBACK_DAYS", 90) == 120


def test_resolve_runtime_prefs_map_user_over_env(settings_store, monkeypatch):
    monkeypatch.setenv("FINAGENT_MAX_WORKERS", "2")
    settings_store.update(user_id := "u2", performance={"max_workers": 5})
    merged = resolve_runtime_prefs_map(settings_store.load_raw(user_id))
    assert merged["FINAGENT_MAX_WORKERS"] == "5"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    chat_dir = tmp_path / "chat_data"
    monkeypatch.setenv("FINAGENT_AUTH_SECRET", "test-secret-key")
    monkeypatch.setattr("finagent.web.server.CHAT_DIR", chat_dir)
    monkeypatch.setattr("finagent.web.server.CHAT_UPLOADS_DIR", chat_dir / "uploads")
    monkeypatch.setattr("finagent.web.server.CHAT_SESSIONS_DIR", chat_dir / "sessions")
    monkeypatch.setattr("finagent.web.server.USER_SETTINGS_DIR", chat_dir / "user_settings")
    return TestClient(create_app())


def test_settings_api_performance_roundtrip(client, monkeypatch):
    monkeypatch.setenv("FINAGENT_MAX_WORKERS", "4")
    auth = client.post("/api/auth/register", json={"username": "perf_user", "password": "secret12"})
    headers = {"Authorization": f"Bearer {auth.json()['token']}"}

    initial = client.get("/api/settings", headers=headers)
    assert initial.status_code == 200
    perf0 = initial.json()["settings"]["performance"]
    assert perf0["max_workers"] == 4
    assert "validation_max_rounds" in perf0

    updated = client.put(
        "/api/settings",
        json={
            "performance": {
                "max_workers": 7,
                "auto_ingest_on_new_chat": False,
                "annual_max_age_days": 45,
                "validation_max_rounds": 3,
                "chart_placement_max_rounds": 2,
                "validation_skip_revise_min_score": 90,
                "bootstrap_lookback_days": 100,
            },
        },
        headers=headers,
    )
    assert updated.status_code == 200
    perf1 = updated.json()["settings"]["performance"]
    assert perf1["max_workers"] == 7
    assert perf1["auto_ingest_on_new_chat"] is False
    assert perf1["annual_max_age_days"] == 45
    assert perf1["validation_max_rounds"] == 3

    again = client.get("/api/settings", headers=headers)
    perf2 = again.json()["settings"]["performance"]
    assert perf2 == perf1


def test_settings_api_performance_validation(client):
    auth = client.post("/api/auth/register", json={"username": "perf_bad", "password": "secret12"})
    headers = {"Authorization": f"Bearer {auth.json()['token']}"}
    bad = client.put(
        "/api/settings",
        json={"performance": {"max_workers": 99}},
        headers=headers,
    )
    assert bad.status_code == 422
