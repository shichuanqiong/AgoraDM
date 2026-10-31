"""a2a-dm-mcp server tests.

Coverage:
  * build_server returns a FastMCP instance
  * All expected tools are registered (regression guard against
    accidental drops if someone refactors)
  * Each tool has a non-empty description (LLMs need these to
    decide when to call)
  * Env-var client builder raises a useful error when token missing
  * Env-var client builder picks up token + bot_id + base_url
  * Tool invocation paths call the SDK correctly (mock client)
  * Output coercion handles dataclass, dict, and None cleanly
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from swarmdm_mcp.server import (
    _client_from_env,
    _envelope_to_dict,
    _list_of_dicts,
    build_server,
)


# ── Server / tool registration ──────────────────────────────────


def _list_tools(mcp):
    return asyncio.run(mcp.list_tools())


def test_build_server_returns_fastmcp():
    from mcp.server.fastmcp import FastMCP
    mcp = build_server(client=MagicMock())
    assert isinstance(mcp, FastMCP)


EXPECTED_TOOLS = {
    "ack",
    "add_friend",
    "agora_accept",
    "agora_delete",
    "agora_feed",
    "agora_leaderboard",
    "agora_notifications",
    "agora_post",
    "agora_read",
    "agora_reply",
    "agora_report",
    "agora_stats",
    "agora_vote",
    "context_for_wake",
    "get_conversation",
    "get_friend",
    "get_inbox",
    "get_task",
    "link_code",
    "list_conversations",
    "list_friends",
    "phone_call",
    "phone_result",
    "phone_tools",
    "reply",
    "reply_dm",
    "send_dm",
    "update_friend_memory",
    # v0.10.0 — parity with the swarmdm agent skill 1.3.2
    "search_agents",
    "friend_requests",
    "send_friend_request",
    "accept_friend_request",
    "decline_friend_request",
    "remove_friend",
    "block_agent",
    "unblock_agent",
    "list_blocks",
    "report_agent",
    "list_groups",
    "get_group",
    "create_group",
    "invite_to_group",
    "accept_group_invite",
    "decline_group_invite",
    "leave_group",
    "delete_group",
    "upload_file",
    "download_file",
    "get_profile",
    "update_profile",
    "set_dm_policy",
    "owner_verification_status",
    "verify_owner",
    "follow_agent",
    "unfollow_agent",
    "list_following",
    "list_followers",
    "check_answer",
}


def test_all_expected_tools_registered():
    """Regression guard — every documented tool must be present.
    Adding a new tool should bump this set."""
    mcp = build_server(client=MagicMock())
    names = {t.name for t in _list_tools(mcp)}
    assert names == EXPECTED_TOOLS


def test_tools_have_descriptions():
    """MCP clients show these to the LLM to decide when to call.
    Empty descriptions are useless."""
    mcp = build_server(client=MagicMock())
    for t in _list_tools(mcp):
        assert t.description, f"tool {t.name} has no description"
        assert len(t.description) > 50, (
            f"tool {t.name} description too short — "
            "needs enough detail for the LLM to route correctly"
        )


def test_tool_count_is_pinned():
    """Hard pin — changes here mean docs need updating too."""
    mcp = build_server(client=MagicMock())
    assert len(_list_tools(mcp)) == 58


# ── Env var client builder ──────────────────────────────────────


def test_client_from_env_raises_without_token():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="A2ADM_TOKEN"):
            _client_from_env()


def test_client_from_env_with_just_token():
    with patch.dict(os.environ, {"A2ADM_TOKEN": "bt_xxx"}, clear=True):
        client = _client_from_env()
        assert client._http.token == "bt_xxx"


def test_client_from_env_passes_bot_id():
    env = {
        "A2ADM_TOKEN": "bt_xxx",
        "A2ADM_BOT_ID": "my_bot",
    }
    with patch.dict(os.environ, env, clear=True):
        client = _client_from_env()
        assert client.bot_id == "my_bot"


def test_client_from_env_passes_base_url():
    env = {
        "A2ADM_TOKEN": "bt_xxx",
        "A2ADM_BASE_URL": "https://api.staging.agoradigest.com",
    }
    with patch.dict(os.environ, env, clear=True):
        client = _client_from_env()
        assert "staging" in client._http.api_base


# ── Output coercion helpers ─────────────────────────────────────


def test_envelope_to_dict_handles_none():
    assert _envelope_to_dict(None) == {}


def test_envelope_to_dict_passes_through_dict():
    d = {"id": "x", "state": "completed"}
    assert _envelope_to_dict(d) == d


def test_envelope_to_dict_dataclasses_friend():
    from swarmdm import Friend
    f = Friend(friend_bot_id="bestie", label="Bestie", memory={"k": "v"})
    out = _envelope_to_dict(f)
    assert out["friend_bot_id"] == "bestie"
    assert out["label"] == "Bestie"
    assert out["memory"] == {"k": "v"}


def test_list_of_dicts_empty():
    assert _list_of_dicts([]) == []
    assert _list_of_dicts(None) == []


def test_list_of_dicts_coerces_each_item():
    from swarmdm import Friend
    rows = [
        Friend(friend_bot_id="a"),
        Friend(friend_bot_id="b"),
    ]
    out = _list_of_dicts(rows)
    assert len(out) == 2
    assert out[0]["friend_bot_id"] == "a"
    assert out[1]["friend_bot_id"] == "b"


# ── Tool invocation paths via MagicMock client ──────────────────


def _call_tool(mcp, name, args):
    """FastMCP exposes _tool_manager._tools dict — pull the fn out
    and call it directly. This bypasses the JSON-RPC layer but
    exercises the wrapper logic that matters for these tests."""
    tool = mcp._tool_manager._tools[name]
    return tool.fn(**args)


def test_send_dm_calls_sdk():
    from swarmdm import TaskEnvelope
    client = MagicMock()
    client.dm.send.return_value = TaskEnvelope(
        id="task_123", state="submitted", message={"text": "hi"}
    )
    mcp = build_server(client=client)
    out = _call_tool(mcp, "send_dm", {
        "recipient_bot_id": "bestiedog",
        "text": "hi",
    })
    client.dm.send.assert_called_once_with(
        "bestiedog", "hi", vertical="engineering", tags=None, in_reply_to=None,
    )
    assert out["id"] == "task_123"


def test_get_inbox_returns_count_and_tasks():
    client = MagicMock()
    inbox_view = MagicMock()
    inbox_view.count = 2
    inbox_view.tasks = []
    client.dm.inbox.return_value = inbox_view
    mcp = build_server(client=client)
    out = _call_tool(mcp, "get_inbox", {"limit": 5})
    client.dm.inbox.assert_called_once_with(limit=5, include_acked=True)
    assert out["count"] == 2
    assert out["tasks"] == []


def test_reply_passes_confidence():
    from swarmdm import TaskEnvelope
    client = MagicMock()
    client.dm.reply.return_value = TaskEnvelope(
        id="x", state="completed", message={}
    )
    mcp = build_server(client=client)
    _call_tool(mcp, "reply", {
        "a2a_task_id": "task_99",
        "text": "got it",
        "confidence": "high",
    })
    client.dm.reply.assert_called_once_with(
        "task_99", "got it", confidence="high",
    )


def test_get_friend_returns_none_when_missing():
    """SDK returns None for missing friends — MCP tool must
    pass that through (don't coerce to {})."""
    client = MagicMock()
    client.friends.get.return_value = None
    mcp = build_server(client=client)
    out = _call_tool(mcp, "get_friend", {"friend_bot_id": "stranger"})
    assert out is None


def test_update_friend_memory_plumbs_dict():
    from swarmdm import Friend
    client = MagicMock()
    client.friends.update.return_value = Friend(
        friend_bot_id="bestie", memory={"k": "v"}
    )
    mcp = build_server(client=client)
    out = _call_tool(mcp, "update_friend_memory", {
        "friend_bot_id": "bestie",
        "memory": {"k": "secret-value"},
    })
    client.friends.update.assert_called_once_with(
        "bestie", memory={"k": "secret-value"}
    )
    assert "secret-value" not in str(out) and "saved_keys" in str(out)


def test_context_for_wake_unpacks_all_fields():
    """Crown jewel tool — must expose every WakeContext field so
    the LLM can ignore system_prompt_suggestion and roll its own."""
    from swarmdm import WakeContext
    client = MagicMock()
    client.dm.context_for_wake.return_value = WakeContext(
        my_bot_id="me",
        me={"name": "Me"},
        conversation_partner_bot_id="bestie",
        partner={"display_name": "Bestie", "is_friend": True},
        partner_memory={"topic": "deploy"},
        partner_friend_note="trusted",
        recent_turns=[{"direction": "outgoing", "text": "hi"}],
        system_prompt_suggestion="# You are Me\n...",
    )
    mcp = build_server(client=client)
    out = _call_tool(mcp, "context_for_wake", {
        "partner_bot_id": "bestie",
        "max_turns": 5,
    })
    client.dm.context_for_wake.assert_called_once_with(
        "bestie", max_turns=5,
    )
    assert out["my_bot_id"] == "me"
    assert out["partner_memory"] == {"topic": "deploy"}
    assert out["partner_friend_note"] == "trusted"
    assert out["recent_turns"][0]["text"] == "hi"
    assert "# You are Me" in out["system_prompt_suggestion"]
    assert out["is_friend"] is True
    assert out["partner_display_name"] == "Bestie"
    assert out["my_display_name"] == "Me"


def test_list_conversations_wraps_count():
    client = MagicMock()
    client.dm.conversations.return_value = []
    mcp = build_server(client=client)
    out = _call_tool(mcp, "list_conversations", {"limit": 10})
    client.dm.conversations.assert_called_once_with(limit=10)
    assert out == {"count": 0, "conversations": []}


def test_get_conversation_unpacks_view():
    client = MagicMock()
    view = MagicMock()
    view.partner = {"bot_id": "bestie"}
    view.messages = []
    view.has_more = False
    view.next_before_id = None
    view.count = 0
    client.dm.conversation.return_value = view
    mcp = build_server(client=client)
    out = _call_tool(mcp, "get_conversation", {"partner_bot_id": "bestie"})
    assert out["partner"] == {"bot_id": "bestie"}
    assert out["has_more"] is False
    assert out["count"] == 0


def test_late_binding_client_boots_without_env():
    """When build_server(client=None), the client is built lazily —
    server boot must NOT require A2ADM_TOKEN at module-load
    time (otherwise MCP client startup races would crash before the
    user sees the env-var error)."""
    with patch.dict(os.environ, {}, clear=True):
        # No env vars set, no client injected — must NOT raise.
        mcp = build_server(client=None)
        assert mcp is not None
        # And the tools are still registered.
        assert len(_list_tools(mcp)) == 58


def test_late_binding_first_tool_call_raises_with_helpful_msg():
    """When env var is missing AND the first tool actually fires,
    surface the A2ADM_TOKEN error so the user knows to fix
    their MCP config."""
    with patch.dict(os.environ, {}, clear=True):
        mcp = build_server(client=None)
        tool = mcp._tool_manager._tools["get_friend"]
        with pytest.raises(RuntimeError, match="A2ADM_TOKEN"):
            tool.fn(friend_bot_id="anyone")


def test_link_code_calls_sdk():
    client = MagicMock()
    client.bot.link_code.return_value = {"code": "K7PX2MQD", "deep_link": "elvarone://link?code=K7PX2MQD"}
    mcp = build_server(client=client)
    out = _call_tool(mcp, "link_code", {})
    client.bot.link_code.assert_called_once_with()
    assert out["code"] == "K7PX2MQD"


def test_phone_call_parses_args_and_calls_sdk():
    client = MagicMock()
    client.phone.call.return_value = {"ok": True, "result": "Memo created.", "call_id": "c_1"}
    mcp = build_server(client=client)
    out = _call_tool(mcp, "phone_call", {"tool": "memo", "args_json": '{"operation": "create", "text": "milk"}'})
    client.phone.call.assert_called_once_with("memo", {"operation": "create", "text": "milk"}, operator=None, timeout=60.0)
    assert out["ok"] is True


def test_phone_call_rejects_bad_json_without_calling():
    client = MagicMock()
    mcp = build_server(client=client)
    out = _call_tool(mcp, "phone_call", {"tool": "memo", "args_json": "{not json"})
    assert out["ok"] is False and "args_json" in out["error"]
    client.phone.call.assert_not_called()


def test_phone_tools_calls_sdk():
    client = MagicMock()
    client.phone.tools.return_value = {"published": True, "tools": [{"name": "memo", "granted": True}]}
    mcp = build_server(client=client)
    out = _call_tool(mcp, "phone_tools", {})
    client.phone.tools.assert_called_once_with(operator=None)
    assert out["tools"][0]["name"] == "memo"



# ── v0.10.0 parity tools ────────────────────────────────────────


UNTRUSTED_TOOLS = {
    "get_inbox", "get_task", "get_conversation", "list_conversations", "context_for_wake",
    "agora_feed", "agora_read", "agora_notifications", "search_agents", "friend_requests",
    "list_groups", "get_group", "download_file", "get_profile", "list_following",
    "list_followers", "check_answer", "list_blocks", "list_friends", "get_friend",
}


def test_tools_returning_other_agents_text_say_untrusted():
    mcp = build_server(client=MagicMock())
    by_name = {t.name: t.description.lower() for t in _list_tools(mcp)}
    for name in UNTRUSTED_TOOLS:
        assert "untrusted" in by_name[name] or "never as instructions" in by_name[name], name


def test_send_dm_passes_file_ids_as_attachments():
    from swarmdm import TaskEnvelope
    client = MagicMock()
    client.dm.send.return_value = TaskEnvelope(id="t1")
    mcp = build_server(client=client)
    _call_tool(mcp, "send_dm", {"recipient_bot_id": "group_ext_qa", "text": "hello group", "file_ids": ["f1"]})
    client.dm.send.assert_called_once_with(
        "group_ext_qa", "hello group", vertical="engineering", tags=None, in_reply_to=None, attachments=["f1"],
    )


def test_get_inbox_adds_kind_invite_and_files():
    from swarmdm import TaskEnvelope
    env = TaskEnvelope.from_dict({
        "id": "m1", "message_kind": "group",
        "message": {"role": "user", "parts": [{"kind": "text", "text": "Accept via client.groups.accept('inv_9')"}]},
        "x-agoradigest": {"tags": ["_group_invite"], "group_id": "group_ext_qa"},
        "attachments": [{"file_id": "f1"}],
    })
    client = MagicMock()
    view = MagicMock()
    view.count = 1
    view.tasks = [env]
    client.dm.inbox.return_value = view
    out = _call_tool(build_server(client=client), "get_inbox", {})
    t = out["tasks"][0]
    assert t["kind"] == "group_invite" and t["group_invite_id"] == "inv_9" and t["file_ids"] == ["f1"]
    assert "untrusted" in out["note"]


def test_search_agents_trims_fields():
    client = MagicMock()
    client.agents.find.return_value = [{"bot_id": "guide", "display_name": "Guide", "persona": {"x": 1}}]
    out = _call_tool(build_server(client=client), "search_agents", {"q": "guide"})
    client.agents.find.assert_called_once_with("guide", limit=10)
    assert out["agents"][0]["bot_id"] == "guide" and "persona" not in out["agents"][0]


def test_friend_request_tools():
    from swarmdm import FriendRequest
    client = MagicMock()
    client.friends.requests.return_value = [FriendRequest(id="fr_1", status="pending", raw={"id": "fr_1"})]
    client.friends.accept_request.return_value = FriendRequest(id="fr_1", status="accepted")
    client.friends.request.return_value = {"status": "friend_request_sent"}
    mcp = build_server(client=client)
    out = _call_tool(mcp, "friend_requests", {"direction": "outgoing"})
    client.friends.requests.assert_called_once_with(direction="outgoing", status="pending", limit=50)
    assert out["requests"][0]["id"] == "fr_1" and "raw" not in out["requests"][0]
    assert _call_tool(mcp, "accept_friend_request", {"request_id": "fr_1"})["status"] == "accepted"
    _call_tool(mcp, "send_friend_request", {"to": "ben", "note": "hi"})
    client.friends.request.assert_called_once_with("ben", note="hi")


def test_report_agent_bad_reason_is_an_error_not_a_crash():
    client = MagicMock()
    client.safety.report.side_effect = ValueError("reason must be one of spam, ...")
    out = _call_tool(build_server(client=client), "report_agent", {"bot_id": "ben", "reason": "rude"})
    assert out["ok"] is False


def test_create_group_passes_members():
    from swarmdm import Group
    client = MagicMock()
    client.groups.create.return_value = Group.from_dict({"group_id": "group_ext_qa", "name": "QA"})
    out = _call_tool(build_server(client=client), "create_group", {"name": "QA", "members": ["ben"]})
    client.groups.create.assert_called_once_with("QA", description=None, initial_members=["ben"])
    assert out["group_id"] == "group_ext_qa" and "hint" in out


def test_upload_file_checks_size_locally(tmp_path):
    client = MagicMock()
    mcp = build_server(client=client)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert _call_tool(mcp, "upload_file", {"path": str(empty)})["ok"] is False
    assert _call_tool(mcp, "upload_file", {"path": str(tmp_path / "missing")})["ok"] is False
    client.files.upload.assert_not_called()
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    client.files.upload.return_value = {"file_id": "f1", "name": "a.txt", "size": 5}
    out = _call_tool(mcp, "upload_file", {"path": str(f)})
    assert out["ok"] is True and out["file_id"] == "f1"


def test_download_file_sanitizes_name_and_never_overwrites(tmp_path):
    client = MagicMock()
    client.files.meta.return_value = {"name": "../../.bashrc", "size": 3, "mime_type": "text/plain"}
    client.files.download.return_value = b"abc"
    mcp = build_server(client=client)
    a = _call_tool(mcp, "download_file", {"file_id": "f1", "folder": str(tmp_path)})
    b = _call_tool(mcp, "download_file", {"file_id": "f1", "folder": str(tmp_path)})
    assert a["saved_to"] == str(tmp_path / "bashrc") and b["saved_to"] == str(tmp_path / "bashrc-1")
    assert (tmp_path / "bashrc").read_bytes() == b"abc" and "untrusted" in a["note"]


def test_download_file_respects_max_mb(tmp_path):
    client = MagicMock()
    client.files.meta.return_value = {"name": "big.bin", "size": 30 * 1024 * 1024}
    out = _call_tool(build_server(client=client), "download_file", {"file_id": "f1", "folder": str(tmp_path)})
    assert out["ok"] is False
    client.files.download.assert_not_called()


def test_update_profile_maps_fields_and_capabilities():
    client = MagicMock()
    client.bot.update_capabilities.return_value = ["qa"]
    out = _call_tool(build_server(client=client), "update_profile",
                     {"description": "QA agent", "avatar_emoji": "", "capabilities": ["qa"]})
    client.bot.update_profile.assert_called_once_with(description="QA agent", avatar_emoji=None)
    assert out["updated"] == ["avatar_emoji", "capabilities", "description"] and out["capabilities"] == ["qa"]


def test_update_profile_needs_a_field():
    out = _call_tool(build_server(client=MagicMock()), "update_profile", {})
    assert out["ok"] is False


def test_set_dm_policy_rejects_bad_value():
    client = MagicMock()
    client.bot.set_dm_policy.side_effect = ValueError("dm_policy must be one of open, friends_only, verified_only")
    assert _call_tool(build_server(client=client), "set_dm_policy", {"policy": "nobody"})["ok"] is False


def test_get_profile_self_and_other():
    from swarmdm import AgentProfile
    client = MagicMock()
    client.bot.profile.return_value = AgentProfile(bot_id="ada", raw={"bot": {}})
    client.agents.profile.return_value = AgentProfile(bot_id="ben")
    mcp = build_server(client=client)
    me = _call_tool(mcp, "get_profile", {})
    assert me["bot_id"] == "ada" and "raw" not in me and "note" not in me
    other = _call_tool(mcp, "get_profile", {"bot_id": "ben"})
    client.agents.profile.assert_called_once_with("ben")
    assert "untrusted" in other["note"] and other["page"].endswith("/bots/ben")


def test_follow_tools_default_to_me():
    client = MagicMock()
    client.agents.following.return_value = [{"bot_id": "ben"}]
    mcp = build_server(client=client)
    out = _call_tool(mcp, "list_following", {})
    client.agents.following.assert_called_once_with(None, limit=50)
    assert out == {"count": 1, "following": [{"bot_id": "ben"}]}


def test_check_answer_waits_only_when_asked():
    from swarmdm import DMAnswer
    client = MagicMock()
    client.dm.answer.return_value = DMAnswer(message_id="m1", state="submitted")
    client.dm.wait_for_answer.return_value = DMAnswer(message_id="m1", state="completed", answer="pong")
    mcp = build_server(client=client)
    assert _call_tool(mcp, "check_answer", {"message_id": "m1"})["has_answer"] is False
    out = _call_tool(mcp, "check_answer", {"message_id": "m1", "wait_seconds": 999})
    client.dm.wait_for_answer.assert_called_once_with("m1", timeout_s=120.0)
    assert out["answer"] == "pong" and "untrusted" in out["note"]


def test_report_agent_passes_block_flag():
    client = MagicMock()
    client.safety.report.return_value = {"id": "rp_1", "blocked": False}
    _call_tool(build_server(client=client), "report_agent",
               {"bot_id": "ben", "reason": "spam", "note": "x", "block": False})
    client.safety.report.assert_called_once_with("ben", reason="spam", note="x", message_id=None, block=False)


def test_forum_report_and_delete_use_the_sdk():
    client = MagicMock()
    client.agora.report.return_value = {"status": "visible", "report_count": 1}
    client.agora.delete.return_value = {"status": "deleted"}
    mcp = build_server(client=client)
    _call_tool(mcp, "agora_report", {"target_type": "reply", "target_id": "r1", "reason": "spam " * 100})
    client.agora.report.assert_called_once()
    args, kwargs = client.agora.report.call_args
    assert args[0] == "r1" and len(args[1]) == 280 and kwargs == {"kind": "reply"}
    _call_tool(mcp, "agora_delete", {"target_type": "post", "target_id": "p1"})
    client.agora.delete.assert_called_once_with("p1", kind="post")
