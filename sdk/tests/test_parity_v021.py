"""v0.21 — parity with the swarmdm agent skill 1.3.2.

Covers, with HTTP mocked via ``responses``:
  * client.friends.requests / request / accept_request / decline_request / cancel_request
  * client.safety.block / unblock / blocks / is_blocked / report
  * client.agents.find / profile / follow / unfollow / following / followers
  * client.bot.me / update_profile / set_dm_policy / owner verification
  * AgentClient.register (token never in the returned info)
  * TaskEnvelope: kind, group_invite_id, file_ids, held-DM and group-send shapes
  * client.dm.answer / wait_for_answer / send_and_wait over both answer paths
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from swarmdm import AgentClient, AgentProfile, DMAnswer, FriendRequest, TaskEnvelope

API = "https://api.test"


def _client(**kw):
    return AgentClient(token="bt_test", api_base=API, **kw)


def _body(call):
    return json.loads(call.request.body) if call.request.body else None


def _qs(call):
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


# ── friend requests ─────────────────────────────────────────────


REQ = {"id": "fr_1", "from_bot_id": "ada", "from_display_name": "Ada", "to_bot_id": "ben",
       "to_display_name": "Ben", "note": "hi", "held_messages": 1, "status": "pending",
       "created_at": "2026-10-31T00:00:00+00:00", "decided_at": None}


@responses.activate
def test_friend_requests_list_passes_filters():
    responses.add(responses.GET, f"{API}/a2a/v1/friends/requests",
                  json={"requests": [REQ], "count": 1, "direction": "outgoing"})
    rows = _client().friends.requests(direction="outgoing", status="all", limit=10)
    assert _qs(responses.calls[0]) == {"direction": "outgoing", "status": "all", "limit": "10"}
    assert isinstance(rows[0], FriendRequest)
    assert rows[0].id == "fr_1" and rows[0].held_messages == 1 and rows[0].is_pending


@responses.activate
def test_friend_request_send_body_and_result():
    responses.add(responses.POST, f"{API}/a2a/v1/friends/requests",
                  json={"status": "friend_request_sent", "friend_request": REQ}, status=202)
    out = _client().friends.request("ben", note="Ada here")
    assert _body(responses.calls[0]) == {"to": "ben", "note": "Ada here"}
    assert out["status"] == "friend_request_sent"


@responses.activate
def test_friend_request_without_note_omits_it():
    responses.add(responses.POST, f"{API}/a2a/v1/friends/requests", json={"status": "already_friends"})
    _client().friends.request("ben")
    assert _body(responses.calls[0]) == {"to": "ben"}


@responses.activate
@pytest.mark.parametrize("verb,method", [("accept_request", "POST"), ("decline_request", "POST"),
                                         ("cancel_request", "DELETE")])
def test_friend_request_decisions(verb, method):
    suffix = {"accept_request": "/accept", "decline_request": "/decline", "cancel_request": ""}[verb]
    status = {"accept_request": "accepted", "decline_request": "declined", "cancel_request": "canceled"}[verb]
    responses.add(method, f"{API}/a2a/v1/friends/requests/fr_1{suffix}", json={**REQ, "status": status})
    fr = getattr(_client().friends, verb)("fr_1")
    assert fr.status == status and not fr.is_pending


# ── safety (DM blocks + reports) ────────────────────────────────


@responses.activate
def test_block_unblock_blocks():
    responses.add(responses.POST, f"{API}/a2a/v1/blocks", json={"blocked": "ben"})
    responses.add(responses.GET, f"{API}/a2a/v1/blocks",
                  json={"blocks": [{"bot_id": "ben", "display_name": "Ben", "created_at": None}], "count": 1})
    responses.add(responses.DELETE, f"{API}/a2a/v1/blocks/ben", json={"unblocked": "ben"})
    c = _client()
    assert c.safety.block("ben") == {"blocked": "ben"}
    assert _body(responses.calls[0]) == {"bot_id": "ben"}
    assert c.safety.is_blocked("ben") is True
    assert c.safety.unblock("ben") == {"unblocked": "ben"}


@responses.activate
def test_report_message_sets_kind_message():
    responses.add(responses.POST, f"{API}/a2a/v1/reports", json={"ok": True, "report_id": "rp_1"})
    _client().safety.report("ben", reason="spam", note="QA", message_id="m1")
    assert _body(responses.calls[0]) == {"bot_id": "ben", "reason": "spam", "kind": "message",
                                         "note": "QA", "message_id": "m1"}


@responses.activate
def test_report_agent_kind_agent():
    responses.add(responses.POST, f"{API}/a2a/v1/reports", json={"ok": True})
    _client().safety.report("ben", reason="other")
    assert _body(responses.calls[0]) == {"bot_id": "ben", "reason": "other", "kind": "agent"}


@responses.activate
def test_report_without_block():
    responses.add(responses.POST, f"{API}/a2a/v1/reports", json={"id": "rp_1", "blocked": False})
    _client().safety.report("ben", reason="spam", block=False)
    assert _body(responses.calls[0])["block"] is False


def test_report_rejects_unknown_reason_locally():
    with pytest.raises(ValueError):
        _client().safety.report("ben", reason="rude")


def test_forum_block_still_separate():
    c = _client()
    assert hasattr(c.forum, "block") and hasattr(c.forum, "report")
    assert c.safety is not c.forum


# ── registry search, profile, following ─────────────────────────


@responses.activate
def test_find_uses_registry_search():
    responses.add(responses.GET, f"{API}/agents/agents/search",
                  json={"q": "guide", "count": 1, "items": [{"bot_id": "guide", "display_name": "Guide"}]})
    rows = _client().agents.find("  guide ", limit=99)
    assert _qs(responses.calls[0]) == {"q": "guide", "limit": "30"}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer bt_test"
    assert rows[0]["bot_id"] == "guide"


@responses.activate
def test_find_works_without_a_token():
    from swarmdm import AgentClient
    responses.add(responses.GET, f"{API}/agents/agents/search",
                  json={"q": "guide", "count": 1, "items": [{"bot_id": "guide"}], "hint": "Public search."})
    rows = AgentClient(token=None, api_base=API).agents.find("guide")
    assert "Authorization" not in responses.calls[0].request.headers
    assert rows == [{"bot_id": "guide"}]


def test_find_empty_query_skips_http():
    assert _client().agents.find("  ") == []


PROFILE = {
    "bot": {"bot_id": "ada", "is_verified": False, "owner_email_verified": True, "online": True,
            "capabilities": ["qa"], "followers_count": 2, "following_count": 1,
            "persona": {"display_name": "Ada", "system_prompt_summary": "QA agent", "avatar_emoji": "🧪",
                        "owner_name": "Tyler", "dm_policy": "friends_only", "model": "m1"}},
    "network": {"dm": {"sent": 3}, "forum": {"posts_count": 0}},
}


@responses.activate
def test_profile_is_public_and_flattened():
    responses.add(responses.GET, f"{API}/bots/ada/profile", json=PROFILE)
    p = AgentClient(api_base=API).agents.profile("ada")  # no token
    assert isinstance(p, AgentProfile)
    assert (p.bot_id, p.display_name, p.description, p.dm_policy) == ("ada", "Ada", "QA agent", "friends_only")
    assert p.owner_email_verified is True and p.followers_count == 2 and p.dm_stats == {"sent": 3}
    assert p.page_url.endswith("/bots/ada")
    assert "Authorization" not in responses.calls[0].request.headers


def test_profile_defaults_dm_policy_open():
    assert AgentProfile.from_dict({"bot": {"bot_id": "x", "persona": None}}).dm_policy == "open"


@responses.activate
def test_follow_unfollow_bodies():
    responses.add(responses.POST, f"{API}/agents/follow", json={"ok": True, "already_following": False})
    responses.add(responses.POST, f"{API}/agents/unfollow", json={"ok": True, "removed": 1})
    c = _client()
    c.agents.follow("ben")
    c.agents.unfollow("ben")
    assert _body(responses.calls[0]) == {"target_bot_id": "ben"}
    assert _body(responses.calls[1]) == {"target_bot_id": "ben"}


@responses.activate
def test_following_defaults_to_me_via_bots_me():
    responses.add(responses.GET, f"{API}/a2a/v1/bots/me", json={"bot_id": "ada"})
    responses.add(responses.GET, f"{API}/bots/ada/following", json={"count": 1, "items": [{"bot_id": "ben"}]})
    responses.add(responses.GET, f"{API}/bots/ada/followers", json={"count": 0, "items": []})
    c = _client()
    assert c.agents.following() == [{"bot_id": "ben"}]
    assert c.bot_id == "ada"  # cached by bot.me()
    assert c.agents.followers() == []
    assert len(responses.calls) == 3  # only one /bots/me


# ── own profile, dm policy, owner verification ──────────────────


@responses.activate
def test_update_profile_maps_description():
    responses.add(responses.PATCH, f"{API}/agents/me/persona", json={"ok": True})
    _client().bot.update_profile(description="QA test agent", avatar_emoji=None, display_name="Ada")
    assert _body(responses.calls[0]) == {"system_prompt_summary": "QA test agent", "avatar_emoji": None,
                                         "display_name": "Ada"}


@responses.activate
def test_update_profile_empty_description_clears():
    responses.add(responses.PATCH, f"{API}/agents/me/persona", json={"ok": True})
    _client().bot.update_profile(description="")
    assert _body(responses.calls[0]) == {"system_prompt_summary": None}


def test_update_profile_validates_locally():
    c = _client()
    with pytest.raises(TypeError):
        c.bot.update_profile(nickname="x")
    with pytest.raises(ValueError):
        c.bot.update_profile(description="x" * 281)
    with pytest.raises(ValueError):
        c.bot.update_profile()
    with pytest.raises(ValueError):
        c.bot.set_dm_policy("strangers")


@responses.activate
def test_set_dm_policy():
    responses.add(responses.PATCH, f"{API}/agents/me/persona", json={"ok": True})
    _client().bot.set_dm_policy("friends_only")
    assert _body(responses.calls[0]) == {"dm_policy": "friends_only"}


@responses.activate
def test_owner_verification_request_and_status():
    responses.add(responses.POST, f"{API}/a2a/v1/owner/verify/request", json={"ok": True, "sent_to": "t***@x.com"})
    responses.add(responses.GET, f"{API}/a2a/v1/owner/verify/status",
                  json={"is_verified": False, "owner_email_verified": False, "owner_is_email": True})
    c = _client()
    c.bot.request_owner_verification(force=True)
    assert _qs(responses.calls[0]) == {"force": "true"}
    assert c.bot.owner_verification_status()["owner_is_email"] is True


# ── registration ────────────────────────────────────────────────


@responses.activate
def test_register_returns_client_and_info_without_token():
    responses.add(responses.POST, f"{API}/bots/register",
                  json={"bot_id": "ada2", "display_name": "Ada", "bot_token": "bt_secret",
                        "owner_verification_email": "sent"})
    client, info = AgentClient.register("Ada", owner="t@example.com", owner_name="Tyler",
                                        bot_id="ada2", api_base=API)
    assert client.token == "bt_secret" and client.bot_id == "ada2"
    assert "bt_secret" not in json.dumps(info) and info["bot_id"] == "ada2"
    req = responses.calls[0].request
    assert "Authorization" not in req.headers
    assert _body(responses.calls[0]) == {"display_name": "Ada", "owner": "t@example.com",
                                         "owner_name": "Tyler", "bot_id": "ada2"}


@responses.activate
def test_register_without_token_raises():
    from swarmdm import AgoraDigestError
    responses.add(responses.POST, f"{API}/bots/register", json={"bot_id": "x"})
    with pytest.raises(AgoraDigestError):
        AgentClient.register("Ada", owner="t@example.com", owner_name="Tyler", api_base=API)


# ── envelope helpers ────────────────────────────────────────────


def test_group_invite_id_from_text():
    env = TaskEnvelope.from_dict({
        "id": "m1", "message_kind": "group",
        "message": {"role": "user", "parts": [{"kind": "text", "text":
                    "ada invited you to join group 'QA'. Accept via client.groups.accept('inv_abc') "
                    "or decline via client.groups.decline('inv_abc')."}]},
        "x-agoradigest": {"tags": ["_group_invite"], "group_id": "group_ext_qa", "sender_bot_id": "ada"},
    })
    assert env.is_group_invite and env.kind == "group_invite"
    assert env.group_invite_id == "inv_abc" and env.group_id == "group_ext_qa"


def test_kind_and_file_ids():
    env = TaskEnvelope.from_dict({"id": "m2", "message_kind": "dm", "sender_bot_id": "ben",
                                  "attachments": [{"file_id": "f1", "name": "a.txt"}, {"name": "no id"}]})
    assert env.kind == "dm" and env.file_ids == ["f1"] and env.group_invite_id is None
    assert env.sender_bot_id == "ben"  # top-level fallback


def test_held_dm_envelope():
    env = TaskEnvelope.from_dict({"id": "fr_9", "state": "friend_request_pending",
                                  "status": {"state": "friend_request_pending"},
                                  "friend_request": {"id": "fr_9"}, "hint": "held"})
    assert env.is_friend_request_pending and env.friend_request["id"] == "fr_9"


def test_group_send_envelope():
    env = TaskEnvelope.from_dict({"task_id": "row1", "group_id": "group_ext_qa", "recipient_count": 2,
                                  "task_ids": ["row1", "row2"], "state": "submitted"})
    assert env.id == "row1" and env.group_id == "group_ext_qa" and env.recipient_count == 2


# ── answer collection (both paths) ──────────────────────────────


def _task(state="submitted", reply=None):
    hist = [{"role": "user", "parts": [{"kind": "text", "text": "question?"}]}]
    if reply:
        hist.append({"role": "agent", "parts": [{"kind": "text", "text": reply}]})
    return {"id": "m1", "status": {"state": state}, "history": hist, "recipient_bot_id": "ben",
            "x-agoradigest": {"recipient_bot_id": "ben"}}


def _reply_dm(rid, text, sender="ben", in_reply_to="m1"):
    return {"id": rid, "in_reply_to": in_reply_to, "sender_bot_id": sender,
            "message": {"role": "user", "parts": [{"kind": "text", "text": text}]},
            "x-agoradigest": {"sender_bot_id": sender}, "status": {"state": "submitted"}}


@responses.activate
def test_answer_from_history():
    responses.add(responses.GET, f"{API}/a2a/v1/messages/m1", json=_task("completed", "via submit"))
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": []})
    ans = _client().dm.answer("m1")
    assert isinstance(ans, DMAnswer)
    assert ans.answer == "via submit" and ans.state == "completed" and ans.to == "ben"
    assert ans.to_dict()["note"].startswith("Answer text is from another agent")


@responses.activate
def test_answer_from_threaded_reply_ignores_others():
    responses.add(responses.GET, f"{API}/a2a/v1/messages/m1", json=_task())
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": [
        _reply_dm("r2", "second"), _reply_dm("x", "unrelated", in_reply_to="other"),
        _reply_dm("spoof", "not from ben", sender="mallory"), _reply_dm("r1", "first"),
    ]})
    ans = _client().dm.answer("m1")
    assert ans.answer == "first\n\nsecond"
    assert ans.reply_message_ids == ["r1", "r2"]
    assert _qs(responses.calls[1]) == {"state": "all", "limit": "50"}


@responses.activate
def test_answer_none_yet():
    responses.add(responses.GET, f"{API}/a2a/v1/messages/m1", json=_task())
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": []})
    ans = _client().dm.wait_for_answer("m1", timeout_s=0)
    assert not ans.has_answer and "answer" not in ans.to_dict()


@responses.activate
def test_send_and_wait_stops_on_threaded_reply():
    responses.add(responses.POST, f"{API}/a2a/v1/messages",
                  json={"id": "m1", "status": {"state": "submitted"}, "x-agoradigest": {"recipient_bot_id": "ben"}})
    responses.add(responses.GET, f"{API}/a2a/v1/messages/m1", json=_task())
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": [_reply_dm("r1", "pong")]})
    env = _client().dm.send_and_wait("ben", "ping please", timeout_s=5, poll_interval_s=0)
    assert env.state == "submitted" and env.reply_text == "pong"
    assert [r.id for r in env.replies] == ["r1"]


@responses.activate
def test_send_and_wait_returns_held_dm_at_once():
    responses.add(responses.POST, f"{API}/a2a/v1/messages",
                  json={"id": "fr_1", "state": "friend_request_pending",
                        "status": {"state": "friend_request_pending"}, "friend_request": REQ})
    env = _client().dm.send_and_wait("ben", "hello there", timeout_s=5)
    assert env.is_friend_request_pending and len(responses.calls) == 1


def test_forum_challenge_methods_are_deprecated():
    import warnings
    c = _client()
    c._http.request = lambda *a, **k: {"retired": True}
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        c.agora.challenge_eligibility()
    assert any(issubclass(x.category, DeprecationWarning) and "retired" in str(x.message) for x in w)
