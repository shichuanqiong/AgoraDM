"""client.files — direct upload to storage with multipart fallback (v0.22)."""

from __future__ import annotations

import json

import pytest
import responses

from agoradm import AgentClient, AgoraDigestError
from agoradm.files_api import FilesAPI

API = "https://api.test"
STORE = "https://acct.r2.cloudflarestorage.com/bucket/a2a/2026/09/f1?X-Amz-Signature=abc"
META = {"file_id": "f1", "name": "clip.mp4", "mime_type": "video/mp4", "size": 5,
        "uri": f"{API}/a2a/v1/files/f1", "owner_bot_id": "me", "expires_at": None}


def _client():
    return AgentClient(token="bt_test", api_base=API)


def _slot():
    return {"file_id": "f1", "upload": {"method": "PUT", "url": STORE, "headers": {"Content-Length": "5"},
                                        "expires_in": 900},
            "complete": {"method": "POST", "path": "/a2a/v1/files/f1/complete"}}


@responses.activate
def test_direct_upload_puts_to_storage_without_the_token():
    responses.add(responses.POST, f"{API}/a2a/v1/files/uploads", json=_slot())
    responses.add(responses.PUT, STORE, status=200)
    responses.add(responses.POST, f"{API}/a2a/v1/files/f1/complete", json=META)
    meta = _client().files.upload_bytes(b"12345", "clip.mp4", "video/mp4")
    assert meta["file_id"] == "f1"
    slot_req, put_req, done_req = (c.request for c in responses.calls)
    assert json.loads(slot_req.body) == {"name": "clip.mp4", "mime_type": "video/mp4", "size": 5}
    assert slot_req.headers["Authorization"] == "Bearer bt_test"
    assert put_req.body == b"12345" and put_req.headers["Content-Length"] == "5"
    assert "Authorization" not in put_req.headers
    assert done_req.headers["Authorization"] == "Bearer bt_test"
    assert not any(c.request.url == f"{API}/a2a/v1/files" for c in responses.calls)


@pytest.mark.parametrize("status", [405, 501])
@responses.activate
def test_falls_back_to_multipart_on_older_or_storage_less_platforms(status):
    responses.add(responses.POST, f"{API}/a2a/v1/files/uploads", status=status, json={"detail": "x"})
    responses.add(responses.POST, f"{API}/a2a/v1/files", json=META)
    meta = _client().files.upload_bytes(b"12345", "clip.mp4", "video/mp4")
    assert meta["file_id"] == "f1"
    assert b'filename="clip.mp4"' in responses.calls[1].request.body


@responses.activate
def test_fallback_refuses_files_over_the_multipart_limit_locally():
    responses.add(responses.POST, f"{API}/a2a/v1/files/uploads", status=405)
    with pytest.raises(AgoraDigestError) as e:
        _client().files.upload_bytes(b"\0" * (10 * 1024 * 1024 + 1), "big.bin")
    assert e.value.status_code == 413
    assert len(responses.calls) == 1


@responses.activate
def test_storage_refusal_surfaces():
    responses.add(responses.POST, f"{API}/a2a/v1/files/uploads", json=_slot())
    responses.add(responses.PUT, STORE, status=403, body="<Error><Code>SignatureDoesNotMatch</Code></Error>")
    with pytest.raises(AgoraDigestError) as e:
        _client().files.upload_bytes(b"12345", "clip.mp4")
    assert e.value.status_code == 403 and "SignatureDoesNotMatch" in str(e.value)


@responses.activate
def test_quota_error_is_not_swallowed_by_the_fallback():
    responses.add(responses.POST, f"{API}/a2a/v1/files/uploads", status=429,
                  json={"detail": {"error": "daily_upload_quota_exceeded"}})
    with pytest.raises(AgoraDigestError) as e:
        _client().files.upload_bytes(b"12345", "clip.mp4")
    assert e.value.status_code == 429 and len(responses.calls) == 1


@responses.activate
def test_url_endpoint():
    responses.add(responses.GET, f"{API}/a2a/v1/files/f1/url", json={**META, "url": STORE, "auth": "none", "expires_in": 300})
    assert _client().files.url("f1")["auth"] == "none"


@pytest.mark.parametrize("header,name", [
    ("attachment; filename=\"__ final.mp4\"; filename*=UTF-8''%E6%8A%A5%E5%91%8A%20final.mp4", "报告 final.mp4"),
    ('attachment; filename="report.pdf"', "report.pdf"),
    ("attachment; filename*=UTF-8''..%2F..%2Fetc%2Fpasswd", "passwd"),
    ('attachment; filename=".."', None),
    ("", None),
])
def test_filename_from_content_disposition(header, name):
    assert FilesAPI._filename_from(header) == name
