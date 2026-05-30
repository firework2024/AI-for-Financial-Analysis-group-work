"""对话会话持久化（JSON 文件，按用户分目录）。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str
    created_at: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatSession:
    id: str
    title: str
    created_at: str
    updated_at: str
    user_id: str = ""
    stock_code: str | None = None
    report_id: str | None = None
    pdf_name: str | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    knowledge_graph: dict[str, Any] = field(default_factory=lambda: {"nodes": [], "edges": []})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "user_id": self.user_id,
            "stock_code": self.stock_code,
            "report_id": self.report_id,
            "pdf_name": self.pdf_name,
            "messages": [message.to_dict() for message in self.messages],
            "chunks": self.chunks,
            "knowledge_graph": self.knowledge_graph,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChatSession:
        messages = [
            ChatMessage(**{**item, "sources": item.get("sources") or [], "tool_calls": item.get("tool_calls") or []})
            for item in payload.get("messages") or []
            if isinstance(item, dict)
        ]
        return cls(
            id=str(payload.get("id") or uuid.uuid4().hex),
            title=str(payload.get("title") or "新对话"),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
            user_id=str(payload.get("user_id") or ""),
            stock_code=payload.get("stock_code"),
            report_id=payload.get("report_id"),
            pdf_name=payload.get("pdf_name"),
            messages=messages,
            chunks=list(payload.get("chunks") or []),
            knowledge_graph=payload.get("knowledge_graph") if isinstance(payload.get("knowledge_graph"), dict) else {"nodes": [], "edges": []},
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        safe = Path(user_id).name
        path = self.root / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, user_id: str, session_id: str) -> Path:
        safe_session = Path(session_id).name
        return self._user_dir(user_id) / f"{safe_session}.json"

    def create(self, *, user_id: str, title: str = "新对话", stock_code: str | None = None) -> ChatSession:
        session = ChatSession(
            id=uuid.uuid4().hex,
            title=title,
            created_at=_now(),
            updated_at=_now(),
            user_id=user_id,
            stock_code=stock_code,
        )
        self.save(session)
        return session

    def save(self, session: ChatSession) -> None:
        if not session.user_id:
            raise ValueError("session.user_id 不能为空")
        session.updated_at = _now()
        path = self._path(session.user_id, session.id)
        with self._lock:
            path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, user_id: str, session_id: str) -> ChatSession | None:
        path = self._path(user_id, session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        session = ChatSession.from_dict(payload)
        if session.user_id and session.user_id != user_id:
            return None
        if not session.user_id:
            session.user_id = user_id
        return session

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        user_dir = self._user_dir(user_id)
        for path in sorted(user_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("user_id") and payload.get("user_id") != user_id:
                continue
            sessions.append(
                {
                    "id": payload.get("id"),
                    "title": payload.get("title"),
                    "updated_at": payload.get("updated_at"),
                    "stock_code": payload.get("stock_code"),
                    "report_id": payload.get("report_id"),
                    "pdf_name": payload.get("pdf_name"),
                    "message_count": len(payload.get("messages") or []),
                }
            )
        return sessions

    def delete(self, user_id: str, session_id: str) -> bool:
        path = self._path(user_id, session_id)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True
