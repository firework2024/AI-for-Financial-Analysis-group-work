import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent.auth.password import hash_password, verify_password
from finagent.auth.tokens import create_access_token, decode_access_token
from finagent.auth.users import UserStore
from finagent.web.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    chat_dir = tmp_path / "chat_data"
    monkeypatch.setenv("FINAGENT_AUTH_SECRET", "test-secret-key")
    monkeypatch.setattr("finagent.web.server.CHAT_DIR", chat_dir)
    monkeypatch.setattr("finagent.web.server.CHAT_UPLOADS_DIR", chat_dir / "uploads")
    monkeypatch.setattr("finagent.web.server.CHAT_SESSIONS_DIR", chat_dir / "sessions")
    monkeypatch.setattr("finagent.web.server.USER_SETTINGS_DIR", chat_dir / "user_settings")
    return TestClient(create_app())


def test_password_hash_roundtrip():
    encoded = hash_password("secret123")
    assert verify_password("secret123", encoded)
    assert not verify_password("wrong", encoded)


def test_access_token_roundtrip():
    token = create_access_token(user_id="u1", username="alice")
    payload = decode_access_token(token)
    assert payload["sub"] == "u1"
    assert payload["usr"] == "alice"


def test_register_login_and_me(client):
    register = client.post("/api/auth/register", json={"username": "alice", "password": "secret12"})
    assert register.status_code == 200
    token = register.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"

    login = client.post("/api/auth/login", json={"username": "alice", "password": "secret12"})
    assert login.status_code == 200
    assert "finagent_token" in login.cookies


def test_chat_sessions_are_user_scoped(client):
    user_a = client.post("/api/auth/register", json={"username": "user_a", "password": "secret12"}).json()
    user_b = client.post("/api/auth/register", json={"username": "user_b", "password": "secret12"}).json()
    token_a = user_a["token"]
    token_b = user_b["token"]

    created = client.post(
        "/api/chat/sessions",
        json={"title": "私有对话"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    session_id = created.json()["id"]

    own = client.get(f"/api/chat/sessions/{session_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert own.status_code == 200

    foreign = client.get(f"/api/chat/sessions/{session_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert foreign.status_code == 404

    listed = client.get("/api/chat/sessions", headers={"Authorization": f"Bearer {token_b}"})
    assert listed.json()["sessions"] == []


def test_user_settings_update(client):
    auth = client.post("/api/auth/register", json={"username": "settings_user", "password": "secret12"})
    token = auth.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    updated = client.put(
        "/api/settings",
        json={
            "openai_api_key": "sk-test-user-key",
            "openai_base_url": "https://api.example.com/v1",
            "openai_model": "test-model",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    body = updated.json()["settings"]
    assert body["has_user_api_key"] is True
    assert body["api_key_source"] == "user"
    assert body["openai_base_url"] == "https://api.example.com/v1"
    assert body["openai_model"] == "test-model"

    cleared = client.put("/api/settings", json={"clear_api_key": True}, headers=headers)
    assert cleared.json()["settings"]["has_user_api_key"] is False

    got = client.get("/api/settings", headers=headers)
    assert got.status_code == 200
    assert "performance" in got.json()["settings"]
    assert got.json()["settings"]["chat_agent_mode"] in {"loop", "single"}


def test_report_owner_filter(tmp_path):
    from finagent.auth.owners import ReportOwnerStore

    owners = ReportOwnerStore(tmp_path / "owners.json")
    owners.set_owner("600519_multi_agent_report.json", "owner-a")
    reports = [
        {"id": "600519_multi_agent_report.json", "title": "A"},
        {"id": "000002_2025_report.json", "title": "B"},
    ]
    visible = owners.filter_reports("owner-a", reports)
    assert len(visible) == 2
    visible_b = owners.filter_reports("owner-b", reports)
    assert len(visible_b) == 1
    assert visible_b[0]["id"] == "000002_2025_report.json"
