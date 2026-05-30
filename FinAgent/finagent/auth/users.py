from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .password import hash_password, verify_password

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fff]{2,32}$")


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    created_at: str

    def to_public(self) -> dict[str, str]:
        return {"id": self.id, "username": self.username, "created_at": self.created_at}


class UserStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"users": []})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"users": []}

    def _write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_by_id(self, user_id: str) -> User | None:
        for item in self._read().get("users") or []:
            if item.get("id") == user_id:
                return User(**item)
        return None

    def get_by_username(self, username: str) -> User | None:
        target = username.strip().lower()
        for item in self._read().get("users") or []:
            if str(item.get("username", "")).lower() == target:
                return User(**item)
        return None

    def register(self, username: str, password: str) -> User:
        username = username.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("用户名需 2–32 位，仅含字母、数字、下划线或中文")
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        if self.get_by_username(username):
            raise ValueError("用户名已存在")
        user = User(
            id=uuid.uuid4().hex,
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        payload = self._read()
        users = list(payload.get("users") or [])
        users.append(
            {
                "id": user.id,
                "username": user.username,
                "password_hash": user.password_hash,
                "created_at": user.created_at,
            }
        )
        payload["users"] = users
        self._write(payload)
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user
