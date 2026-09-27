"""ElvarOne bridge (platform v0.21): link codes, operators, operator DMs."""

from __future__ import annotations

import responses

from agoradm import AgentClient
from agoradm.cli import main as cli_main
from agoradm.models import TaskEnvelope

API = "https://api.test"


@responses.activate
def test_link_code_and_operators():
    responses.add(responses.POST, f"{API}/a2a/v1/agents/me/link_codes",
                  json={"code": "K7PX2MQD", "agent_bot_id": "home", "expires_at": None,
                        "deep_link": "elvarone://link?code=K7PX2MQD"})
    responses.add(responses.GET, f"{API}/a2a/v1/agents/me/operators",
                  json={"operators": [{"human_id": "hu_1", "display_name": "水哥", "role": "owner", "permissions": []}]})
    c = AgentClient(token="bt_x", api_base=API)
    assert c.bot.link_code()["deep_link"].endswith("K7PX2MQD")
    assert c.bot.operators()[0]["human_id"] == "hu_1"


def test_envelope_marks_operator_dms():
    env = TaskEnvelope.from_dict({"id": "t1", "status": {"state": "submitted"},
                                  "sender_kind": "human", "sender_is_operator": True})
    assert env.sender_kind == "human" and env.sender_is_operator is True
    old = TaskEnvelope.from_dict({"id": "t2", "status": {"state": "submitted"}})
    assert old.sender_kind is None and old.sender_is_operator is None


@responses.activate
def test_cli_link_prints_code_and_link(capsys):
    responses.add(responses.POST, f"{API}/a2a/v1/agents/me/link_codes",
                  json={"code": "K7PX2MQD", "agent_bot_id": "home", "expires_at": None,
                        "deep_link": "elvarone://link?code=K7PX2MQD"})
    assert cli_main(["link", "--token", "bt_x", "--api-base", API]) == 0
    out = capsys.readouterr().out
    assert "K7PX-2MQD" in out and "elvarone://link?code=K7PX2MQD" in out
