"""client.phone — tools on the owner's phone (platform v0.24)."""

from __future__ import annotations

import json

import pytest
import responses

from agoradm import AgentClient

API = "https://api.test"
OPS = {"operators": [{"human_id": "hu_1", "display_name": "水哥", "permissions": ["phone.memo"],
                      "phone_tools": {"published": True, "app_version": "2.0.2 (54)", "tools": [
                          {"name": "memo", "description": "memos", "parameters": {}, "granted": True},
                          {"name": "todo", "description": "todos", "parameters": {}, "granted": False}]}}]}


def _client():
    return AgentClient(token="bt_test", api_base=API)


@responses.activate
def test_tools_reads_the_operator_manifest():
    responses.add(responses.GET, f"{API}/a2a/v1/agents/me/operators", json=OPS)
    t = _client().phone.tools()
    assert t["operator"] == "hu_1" and [x["name"] for x in t["tools"]] == ["memo", "todo"]
    assert t["tools"][0]["granted"] and not t["tools"][1]["granted"]


@responses.activate
def test_call_sends_a_tool_call_and_returns_the_result():
    responses.add(responses.GET, f"{API}/a2a/v1/agents/me/operators", json=OPS)
    responses.add(responses.POST, f"{API}/a2a/v1/messages", json={"id": "t1"})
    sent = {}

    def inbox(request):
        body = json.loads(responses.calls[1].request.body)
        cid = body["message"]["parts"][1]["data"]["call_id"]
        sent["body"] = body
        return (200, {}, json.dumps({"tasks": [{"id": "r1", "in_reply_to": "t1", "data": [
            {"elvarone": "tool_result", "call_id": cid, "ok": True, "result": "Memo created."}]}]}))

    responses.add_callback(responses.GET, f"{API}/a2a/v1/messages/inbox", callback=inbox)
    r = _client().phone.call("memo", {"operation": "create", "text": "milk"}, timeout=5, poll=0)
    assert r["ok"] is True and r["result"] == "Memo created." and r["task_id"] == "t1"
    body = sent["body"]
    assert body["recipient_bot_id"] == "hu_1"
    assert body["message"]["parts"][0]["text"] == "🛠 memo · create"
    data = body["message"]["parts"][1]["data"]
    assert data["elvarone"] == "tool_call" and data["tool"] == "memo" and data["args"]["text"] == "milk"
    # How long it waits, so the platform delivers an in-time answer quietly.
    assert data["wait_s"] == 5
    assert "sender=hu_1" in responses.calls[2].request.url


@responses.activate
def test_call_returns_pending_when_the_phone_is_slow():
    responses.add(responses.GET, f"{API}/a2a/v1/agents/me/operators", json=OPS)
    responses.add(responses.POST, f"{API}/a2a/v1/messages", json={"id": "t1"})
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": []})
    r = _client().phone.call("todo", {"operation": "create"}, timeout=0, poll=0)
    assert r["ok"] is None and r["pending"] is True and r["call_id"].startswith("c_")


@responses.activate
def test_unlinked_agent_gets_a_clear_error():
    responses.add(responses.GET, f"{API}/a2a/v1/agents/me/operators", json={"operators": []})
    with pytest.raises(ValueError, match="agoradm link"):
        _client().phone.tools()


@responses.activate
def test_envelopes_carry_data_parts():
    responses.add(responses.GET, f"{API}/a2a/v1/messages/inbox", json={"tasks": [
        {"id": "r1", "data": [{"elvarone": "tool_result", "call_id": "c1", "ok": True}],
         "x-agoradigest": {"sender_bot_id": "hu_1"}, "status": {"state": "submitted"}}]})
    view = _client().dm.inbox()
    assert view.tasks[0].data[0]["call_id"] == "c1"
