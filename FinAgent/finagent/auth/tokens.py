from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from ..env import get_env, project_root

TOKEN_TTL_SECONDS = 60 * 60 * 24 * 14


def _secret_path() -> str:
    return str(project_root() / "chat_data" / ".auth_secret")


def auth_secret() -> str:
    explicit = get_env("FINAGENT_AUTH_SECRET")
    if explicit:
        return explicit
    path = _secret_path()
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    secret = secrets.token_hex(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret


def create_access_token(*, user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "usr": username,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("utf-8").rstrip("=")
    sig = hmac.new(auth_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(auth_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    if not payload.get("sub"):
        return None
    return payload
