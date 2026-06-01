from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class ReportOwnerStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def _write(self, payload: dict[str, str]) -> None:
        with self._lock:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_owner(self, report_id: str, user_id: str) -> None:
        safe_id = Path(report_id).name
        payload = self._read()
        payload[safe_id] = user_id
        self._write(payload)

    def get_owner(self, report_id: str) -> str | None:
        safe_id = Path(report_id).name
        return self._read().get(safe_id)

    def user_can_access(self, user_id: str, report_id: str) -> bool:
        owner = self.get_owner(report_id)
        return owner is None or owner == user_id

    def filter_reports(self, user_id: str, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [report for report in reports if self.user_can_access(user_id, str(report.get("id") or report.get("filename") or ""))]
