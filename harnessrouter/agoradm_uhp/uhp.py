"""Minimal client for a UHP server (Unified Harness Protocol, 2026-10-19).

Only the calls the bridge needs: run one task (non-streaming), read the
artifacts it produced, and download them. HarnessRouter CE serves UHP
under ``http://localhost:3000/api/harness``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import requests


class UHPError(RuntimeError):
    """A task the server refused or that ended in ``status: failed``."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Artifact:
    file_id: str
    filename: str
    download_url: Optional[str] = None
    container_id: Optional[str] = None


@dataclass
class TaskResult:
    response_id: str
    session_id: Optional[str]
    text: str
    artifacts: list[Artifact] = field(default_factory=list)
    model: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


def _message_text_and_files(output: list[dict[str, Any]]) -> tuple[str, list[Artifact]]:
    """Assistant text and the files cited on it (UHP Files §2.1)."""
    texts: list[str] = []
    files: list[Artifact] = []
    for item in output or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") != "output_text":
                continue
            if part.get("text"):
                texts.append(part["text"])
            for ann in part.get("annotations") or []:
                if ann.get("type") == "container_file_citation" and ann.get("file_id"):
                    files.append(Artifact(
                        file_id=ann["file_id"],
                        filename=ann.get("filename") or ann["file_id"],
                        download_url=ann.get("download_url"),
                        container_id=ann.get("container_id"),
                    ))
    return "\n\n".join(texts).strip(), files


class UHPClient:
    def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 900.0,
                 session: Optional[requests.Session] = None) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_s = timeout_s
        self._s = session or requests.Session()
        self._s.headers.update({"Authorization": f"Bearer {api_key}"})

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def run(
        self,
        input: Any,
        *,
        harness_id: str,
        model: Optional[str] = None,
        previous_response_id: Optional[str] = None,
        instructions: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> TaskResult:
        body: dict[str, Any] = {"input": input, "metadata": {"harness_id": harness_id}, "stream": False}
        if model:
            body["model"] = model
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        if instructions:
            body["instructions"] = instructions
        if timeout_seconds:
            body["timeout_seconds"] = timeout_seconds
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        r = self._s.post(self._url("v1/responses"), json=body, headers=headers, timeout=self.timeout_s)
        data = _json(r)
        if r.status_code >= 400:
            err = data.get("error") or {}
            raise UHPError(err.get("message") or f"UHP {r.status_code}", err.get("code"))
        if data.get("status") == "failed":
            err = data.get("error") or {}
            raise UHPError(err.get("message") or "task failed", err.get("code"))
        text, files = _message_text_and_files(data.get("output") or [])
        return TaskResult(
            response_id=data["id"],
            session_id=(data.get("metadata") or {}).get("session_id"),
            text=text,
            artifacts=files,
            model=data.get("model"),
            raw=data,
        )

    def session_files(self, session_id: str) -> list[Artifact]:
        """Every artifact of a session (UHP Files §2.2) — the fallback when a
        harness writes files without citing them on its message."""
        r = self._s.get(self._url(f"v1/sessions/{session_id}/files"), timeout=60)
        if r.status_code == 404:
            return []
        data = _json(r)
        if r.status_code >= 400:
            return []
        return [
            Artifact(file_id=f["id"], filename=f.get("filename") or f["id"], container_id=f.get("container_id"))
            for f in data.get("files") or []
            if f.get("id")
        ]

    def download(self, art: Artifact) -> bytes:
        if art.download_url:
            url = art.download_url if art.download_url.startswith("http") else self._url(art.download_url)
        elif art.container_id:
            url = self._url(f"v1/containers/{art.container_id}/files/{art.file_id}/content")
        else:
            url = self._url(f"v1/files/{art.file_id}/content")
        # The session carries the API key: never send it to another origin.
        if urlsplit(url)[:2] != urlsplit(self.base_url)[:2]:
            raise UHPError(f"artifact URL is not on the UHP server: {url}", "foreign_url")
        r = self._s.get(url, timeout=120)
        r.raise_for_status()
        return r.content


def _json(r: requests.Response) -> dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
