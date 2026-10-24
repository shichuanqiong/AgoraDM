from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from agoradm.models import Message, TaskEnvelope

from agoradm_uhp.bridge import Bridge, BridgeConfig
from agoradm_uhp.state import BridgeState
from agoradm_uhp.uhp import Artifact, TaskResult, UHPClient, UHPError


# ── fakes ───────────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, friends: set[str] = frozenset(), files: Optional[dict[str, bytes]] = None) -> None:
        self.submitted: list[tuple[str, str]] = []
        self.threaded: list[tuple[str, str, list[str]]] = []
        self.uploaded: list[tuple[str, bytes]] = []
        self._files = files or {}
        self.dm = SimpleNamespace(submit=self._submit, reply_dm=self._reply_dm)
        self.friends = SimpleNamespace(has=lambda bot_id: bot_id in friends)
        self.files = SimpleNamespace(download=lambda fid: self._files[fid], upload_bytes=self._upload)

    def _submit(self, task_id: str, text: str) -> None:
        self.submitted.append((task_id, text))

    def _reply_dm(self, task_id: str, text: str, attachments: list[str]) -> None:
        self.threaded.append((task_id, text, list(attachments)))

    def _upload(self, data: bytes, filename: str, mime: Optional[str] = None) -> dict[str, str]:
        self.uploaded.append((filename, data))
        return {"file_id": f"up_{len(self.uploaded)}"}


class FakeUHP:
    def __init__(self, results: Optional[list[Any]] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results = results or []
        self.listed: list[Artifact] = []
        self.blobs: dict[str, bytes] = {}

    def run(self, work: Any, **kw: Any) -> TaskResult:
        self.calls.append({"input": work, **kw})
        nxt = self.results.pop(0) if self.results else TaskResult(f"resp_{len(self.calls)}", "hsess1", "ok")
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def session_files(self, session_id: str) -> list[Artifact]:
        return list(self.listed)

    def download(self, art: Artifact) -> bytes:
        return self.blobs.get(art.file_id, b"data")


def dm(text: str, sender: str = "bot_friend", **kw: Any) -> TaskEnvelope:
    return TaskEnvelope(id=kw.pop("id", "t1"), message=Message(role="user", parts=[{"kind": "text", "text": text}]),
                        sender_bot_id=sender, sender_display_name="Friend", message_kind="dm", **kw)


@pytest.fixture
def state(tmp_path):
    return BridgeState(tmp_path / "state.json")


def make(state, *, friends=("bot_friend",), uhp=None, client=None, **cfg):
    client = client or FakeClient(set(friends))
    uhp = uhp or FakeUHP()
    return Bridge(client, uhp, BridgeConfig(harness_id="chrn_x", model="m", **cfg), state), client, uhp


# ── policy ──────────────────────────────────────────────────────────

def test_friend_task_runs_and_reply_is_submitted(state):
    b, client, uhp = make(state, uhp=FakeUHP([TaskResult("resp_a", "hsess1", "Here is the summary.")]))
    b.handle(dm("summarise this"))
    assert uhp.calls[0]["input"] == "summarise this"
    assert uhp.calls[0]["harness_id"] == "chrn_x"
    assert uhp.calls[0]["idempotency_key"] == "agoradm-t1"
    assert "outside party" in uhp.calls[0]["instructions"]
    assert client.submitted == [("t1", "Here is the summary.")]


def test_stranger_is_refused_without_running(state):
    b, client, uhp = make(state)
    b.handle(dm("do work", sender="bot_stranger"))
    assert uhp.calls == []
    assert "approved contacts" in client.submitted[0][1]


def test_owner_is_always_allowed_and_framed_as_owner(state):
    b, client, uhp = make(state, friends=())
    b.handle(dm("deploy it", sender="hu_owner", sender_is_operator=True))
    assert len(uhp.calls) == 1
    assert "from your owner" in uhp.calls[0]["instructions"]


def test_allow_list_and_any(state, tmp_path):
    b, _, uhp = make(state, friends=(), allow="bot_a, bot_b")
    b.handle(dm("x", sender="bot_b"))
    b.handle(dm("x", sender="bot_c"))
    assert len(uhp.calls) == 1
    b2, _, uhp2 = make(BridgeState(tmp_path / "s2.json"), friends=(), allow="any")
    b2.handle(dm("x", sender="bot_c"))
    assert len(uhp2.calls) == 1


def test_group_messages_are_ignored(state):
    b, client, uhp = make(state)
    t = dm("hi all")
    t.message_kind = "group"
    b.handle(t)
    assert uhp.calls == [] and client.submitted == []


def test_daily_cap(state):
    b, client, uhp = make(state, per_day=2)
    for i in range(3):
        b.handle(dm(f"task {i}", id=f"t{i}"))
    assert len(uhp.calls) == 2
    assert "limit of 2" in client.submitted[-1][1]


# ── sessions ────────────────────────────────────────────────────────

def test_follow_up_continues_the_contacts_session(state):
    b, _, uhp = make(state, uhp=FakeUHP([TaskResult("resp_1", "hsess1", "a"), TaskResult("resp_2", "hsess1", "b")]))
    b.handle(dm("first", id="t1"))
    b.handle(dm("second", id="t2"))
    assert uhp.calls[0]["previous_response_id"] is None
    assert uhp.calls[1]["previous_response_id"] == "resp_1"


def test_sessions_are_per_contact(state):
    b, _, uhp = make(state, friends=("bot_a", "bot_b"))
    b.handle(dm("x", sender="bot_a", id="t1"))
    b.handle(dm("y", sender="bot_b", id="t2"))
    assert uhp.calls[1]["previous_response_id"] is None


def test_stale_session_falls_back_to_a_fresh_one(state):
    uhp = FakeUHP([TaskResult("resp_1", "hsess1", "a"), UHPError("gone", "response_not_found"),
                   TaskResult("resp_9", "hsess2", "fresh")])
    b, client, _ = make(state, uhp=uhp)
    b.handle(dm("first", id="t1"))
    b.handle(dm("second", id="t2"))
    assert uhp.calls[2].get("previous_response_id") is None
    assert client.submitted[-1] == ("t2", "fresh")
    assert state.last_response("bot_friend") == "resp_9"


def test_reset_word_starts_fresh(state):
    b, client, uhp = make(state)
    b.handle(dm("first", id="t1"))
    b.handle(dm("/new", id="t2"))
    b.handle(dm("again", id="t3"))
    assert len(uhp.calls) == 2
    assert uhp.calls[1]["previous_response_id"] is None
    assert "fresh session" in client.submitted[1][1]


def test_failed_task_tells_the_sender_without_details(state):
    b, client, _ = make(state, uhp=FakeUHP([UHPError("secret stack trace", "harness_crashed")]))
    b.handle(dm("x"))
    assert "harness_crashed" in client.submitted[0][1]
    assert "secret" not in client.submitted[0][1]


# ── files ───────────────────────────────────────────────────────────

def test_attachments_are_inlined_as_input_files(state):
    client = FakeClient({"bot_friend"}, files={"f1": b"a,b\n1,2\n"})
    b, _, uhp = make(state, client=client)
    b.handle(dm("chart this", attachments=[{"file_id": "f1", "name": "data.csv", "mime_type": "text/csv", "size": 8}]))
    content = uhp.calls[0]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "chart this"}
    assert content[1]["filename"] == "data.csv"
    assert content[1]["file_data"] == "data:text/csv;base64," + base64.b64encode(b"a,b\n1,2\n").decode()


def test_cited_artifacts_are_sent_back(state):
    res = TaskResult("resp_1", "hsess1", "Built the dashboard.",
                     artifacts=[Artifact("file_d", "dashboard.html", download_url="/x")])
    uhp = FakeUHP([res])
    uhp.blobs["file_d"] = b"<html></html>"
    b, client, _ = make(state, uhp=uhp)
    b.handle(dm("make a dashboard"))
    assert client.submitted == [("t1", "Built the dashboard.")]
    assert client.uploaded == [("dashboard.html", b"<html></html>")]
    assert client.threaded == [("t1", "Files from this task: dashboard.html", ["up_1"])]


def test_uncited_files_come_from_the_session_listing_once(state):
    uhp = FakeUHP([TaskResult("resp_1", "hsess1", "done"), TaskResult("resp_2", "hsess1", "done again")])
    uhp.listed = [Artifact("file_a", "a.md")]
    b, client, _ = make(state, uhp=uhp)
    b.handle(dm("one", id="t1"))
    b.handle(dm("two", id="t2"))  # same session, file_a already sent
    assert [t[0] for t in client.threaded] == ["t1"]


# ── UHP client ──────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status: int, body: Any = None, content: bytes = b"") -> None:
        self.status_code, self._body, self.content = status, body, content

    def json(self) -> Any:
        if self._body is None:
            raise ValueError
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    def __init__(self, post: _Resp = None, get: _Resp = None) -> None:
        self.headers: dict[str, str] = {}
        self._post, self._get, self.urls = post, get, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.urls.append(url)
        self.body = json
        return self._post

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self._get


def test_uhp_client_parses_text_and_citations():
    body = {"id": "resp_1", "status": "completed", "model": "m", "metadata": {"session_id": "hsess1"},
            "output": [
                {"type": "function_call", "name": "write"},
                {"type": "message", "content": [{"type": "output_text", "text": "Done.", "annotations": [
                    {"type": "container_file_citation", "file_id": "file_1", "filename": "r.md",
                     "container_id": "cntr_1", "download_url": "http://localhost:3000/api/harness/v1/c/x"}]}]},
            ]}
    s = _Session(post=_Resp(200, body))
    c = UHPClient("http://localhost:3000/api/harness", "k", session=s)
    r = c.run("hi", harness_id="chrn_1", previous_response_id="resp_0")
    assert s.urls == ["http://localhost:3000/api/harness/v1/responses"]
    assert s.body["metadata"] == {"harness_id": "chrn_1"} and s.body["previous_response_id"] == "resp_0"
    assert s.headers["Authorization"] == "Bearer k"
    assert (r.text, r.session_id, r.artifacts[0].filename) == ("Done.", "hsess1", "r.md")


def test_uhp_client_raises_on_failed_status():
    s = _Session(post=_Resp(200, {"id": "resp_1", "status": "failed", "error": {"code": "timeout", "message": "t"}}))
    with pytest.raises(UHPError) as e:
        UHPClient("http://h/api", "k", session=s).run("x", harness_id="c")
    assert e.value.code == "timeout"


def test_uhp_client_never_sends_the_key_to_another_origin():
    s = _Session(get=_Resp(200, content=b"x"))
    c = UHPClient("http://localhost:3000/api/harness", "k", session=s)
    with pytest.raises(UHPError):
        c.download(Artifact("f", "f", download_url="https://evil.example/steal"))
    assert s.urls == []
    assert c.download(Artifact("f", "f", container_id="cntr_1")) == b"x"
    assert s.urls == ["http://localhost:3000/api/harness/v1/containers/cntr_1/files/f/content"]
