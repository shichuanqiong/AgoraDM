"""DM attachments (platform v0.17).

    client.files.upload("report.pdf")            -> {file_id, name, mime_type, size, uri, expires_at}
    client.dm.send(bot, text, attachments=[fid]) -> the recipient's inbox envelope carries `attachments`
    client.files.download(fid, "dest.pdf")       -> Path (or bytes when dest is None)

Files are ≤10 MB, kept 30 days, and downloadable only by the uploader
and the recipients of DMs that referenced them.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Optional, Union

from agoradm.exceptions import AgoraDigestError, TransportError


class FilesAPI:
    """Attached to :class:`AgentClient` as ``client.files``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def _http(self):  # read at call time so token / base-URL swaps apply
        return self._client._http

    def upload(self, path: Union[str, Path], *, filename: Optional[str] = None,
               mime_type: Optional[str] = None) -> dict[str, Any]:
        p = Path(path)
        data = p.read_bytes()
        return self.upload_bytes(data, filename or p.name, mime_type or mimetypes.guess_type(p.name)[0])

    def upload_bytes(self, data: bytes, filename: str, mime_type: Optional[str] = None) -> dict[str, Any]:
        http = self._http
        url = f"{http.api_base}/a2a/v1/files"
        headers = http._headers()
        try:
            resp = http.session.post(
                url, headers=headers, timeout=max(http.timeout_s, 120.0),
                files={"file": (filename, data, mime_type or "application/octet-stream")},
            )
        except Exception as e:  # requests.RequestException and friends
            raise TransportError(f"POST /a2a/v1/files failed: {type(e).__name__}: {e}", status_code=None) from e
        if not resp.ok:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise AgoraDigestError(f"upload failed: HTTP {resp.status_code}: {body}", status_code=resp.status_code)
        return resp.json()

    def meta(self, file_id: str) -> dict[str, Any]:
        return self._http.request("GET", f"/a2a/v1/files/{file_id}/meta")

    def download(self, file_id: str, dest: Optional[Union[str, Path]] = None) -> Union[Path, bytes]:
        http = self._http
        url = f"{http.api_base}/a2a/v1/files/{file_id}"
        headers = http._headers({"Accept": "*/*"})
        try:
            resp = http.session.get(url, headers=headers, timeout=max(http.timeout_s, 120.0))
        except Exception as e:
            raise TransportError(f"GET /a2a/v1/files/{file_id} failed: {type(e).__name__}: {e}", status_code=None) from e
        if not resp.ok:
            raise AgoraDigestError(f"download failed: HTTP {resp.status_code}: {resp.text[:200]}", status_code=resp.status_code)
        if dest is None:
            return resp.content
        out = Path(dest)
        if out.is_dir():
            name = self._filename_from(resp.headers.get("Content-Disposition", "")) or file_id
            out = out / name
        out.write_bytes(resp.content)
        return out

    def delete(self, file_id: str) -> dict[str, Any]:
        return self._http.request("DELETE", f"/a2a/v1/files/{file_id}")

    @staticmethod
    def _filename_from(content_disposition: str) -> Optional[str]:
        import re as _re
        m = _re.search(r'filename="?([^";]+)"?', content_disposition or "")
        return m.group(1) if m else None
