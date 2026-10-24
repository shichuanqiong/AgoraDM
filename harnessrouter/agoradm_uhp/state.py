"""Bridge state on disk: one UHP session per contact, and a daily task
count per contact. A small JSON file — the bridge is one process."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class BridgeState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"contacts": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict) and isinstance(loaded.get("contacts"), dict):
                    self._data = loaded
            except (OSError, ValueError):
                pass  # a corrupt file starts fresh rather than crashing the bridge

    def _contact(self, bot_id: str) -> dict[str, Any]:
        return self._data["contacts"].setdefault(bot_id, {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    # ── sessions ────────────────────────────────────────────────────

    def last_response(self, bot_id: str) -> Optional[str]:
        with self._lock:
            return self._contact(bot_id).get("last_response_id")

    def seen_files(self, bot_id: str) -> set[str]:
        with self._lock:
            return set(self._contact(bot_id).get("seen_files") or [])

    def record_turn(self, bot_id: str, response_id: str, session_id: Optional[str],
                    file_ids: list[str]) -> None:
        with self._lock:
            c = self._contact(bot_id)
            if session_id and c.get("session_id") not in (None, session_id):
                c["seen_files"] = []  # a new session has its own container
            c["last_response_id"] = response_id
            c["session_id"] = session_id
            c["seen_files"] = sorted(set(c.get("seen_files") or []) | set(file_ids))
            self._save()

    def forget(self, bot_id: str) -> None:
        """Start the next task for this contact in a fresh session."""
        with self._lock:
            c = self._contact(bot_id)
            for k in ("last_response_id", "session_id", "seen_files"):
                c.pop(k, None)
            self._save()

    # ── daily cap ───────────────────────────────────────────────────

    def take_slot(self, bot_id: str, per_day: int) -> bool:
        """Count one task for today; False once the contact is over the cap."""
        with self._lock:
            c = self._contact(bot_id)
            day = _today()
            if c.get("day") != day:
                c["day"], c["count"] = day, 0
            if c["count"] >= per_day:
                return False
            c["count"] += 1
            self._save()
            return True
