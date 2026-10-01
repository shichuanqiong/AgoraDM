"""v0.1.5 — tell the sender when the turn their DM woke dies."""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from a2a_dm_hermes import turnwatch

TASK = "8fb99053-eb89-4041-97a0-b28df528cd3f"
CHAT = f"webhook:a2a-dm-wake:{TASK}"


@pytest.fixture(autouse=True)
def _fresh_noticed():
    turnwatch._noticed.clear()
    yield
    turnwatch._noticed.clear()


def _task(state="working", kind="dm", text="今天有什么新闻"):
    return SimpleNamespace(
        state=state, message_kind=kind,
        message=SimpleNamespace(text=text),
    )


# ── shapes ────────────────────────────────────────────────────────


def test_task_id_comes_from_wake_chat_ids_only():
    assert turnwatch.task_id_for_chat(CHAT) == TASK
    assert turnwatch.task_id_for_chat("webhook:a2a-dm-notify:x") is None
    assert turnwatch.task_id_for_chat("12345") is None
    assert turnwatch.task_id_for_chat("") is None


@pytest.mark.parametrize("response", [
    "API call failed after 3 retries: [Errno 32] Broken pipe",
    "⚠️ The model provider failed after retries. I kept raw provider details out of chat; check gateway logs for diagnostics.",
    "⏱️ The model provider is rate-limiting requests. Please wait a moment and try again.",
    "⚠️ Provider authentication failed. Check the configured credentials.",
    "The request failed: Request timed out.\nTry again or use /reset to start a fresh session.",
    "⚠️ Processing completed but no response was generated. This may be a transient error.",
])
def test_failed_turns_are_recognised(response):
    assert turnwatch.looks_failed(response)


@pytest.mark.parametrize("response", [
    "",
    "Replied to 水哥 with today's headlines.",
    "Done — sent the news summary via a2a_reply.",
    "The API call to the weather service failed, so I used yesterday's forecast.",
])
def test_normal_turns_are_left_alone(response):
    assert not turnwatch.looks_failed(response)


def test_notice_follows_the_senders_language_and_the_cause():
    zh = turnwatch.notice_text("API call failed after 3 retries: Broken pipe", "今天有什么新闻")
    assert "没处理完" in zh and "模型服务暂时没有响应" in zh
    en = turnwatch.notice_text("API call failed after 3 retries: Broken pipe", "any news today?")
    assert "couldn't finish" in en and "isn't responding" in en
    assert "限流" in turnwatch.notice_text("⏱️ The model provider is rate-limiting requests.", "新闻")
    assert "API key" in turnwatch.notice_text("⚠️ Provider authentication failed.", "新闻")


# ── sending ───────────────────────────────────────────────────────


def _client(task):
    c = MagicMock()
    c.dm.get_task.return_value = task
    return c


def test_unreplied_dm_gets_the_notice():
    c = _client(_task())
    with patch.object(turnwatch, "_client", return_value=c):
        assert turnwatch.send_notice(TASK, "API call failed after 3 retries: x")
    c.dm.reply.assert_called_once()
    task_id, text = c.dm.reply.call_args.args
    assert task_id == TASK and text.startswith("⚠️ 这条我没处理完")


def test_replied_or_group_dms_get_nothing():
    for task in (_task(state="completed"), _task(kind="group")):
        c = _client(task)
        with patch.object(turnwatch, "_client", return_value=c):
            assert not turnwatch.send_notice(TASK, "API call failed after 3 retries: x")
        c.dm.reply.assert_not_called()


def test_on_agent_end_sends_once_per_task_in_the_background():
    with patch.object(turnwatch, "send_notice") as send, \
         patch.object(turnwatch.threading, "Thread") as thread:
        ctx = {"chat_id": CHAT, "response": "API call failed after 3 retries: x"}
        turnwatch.on_agent_end(ctx)
        turnwatch.on_agent_end(ctx)
    thread.assert_called_once()
    assert thread.call_args.kwargs["args"] == (TASK, "API call failed after 3 retries: x")
    thread.return_value.start.assert_called_once()
    send.assert_not_called()  # runs on the thread, not the event loop


def test_on_agent_end_ignores_other_chats_good_turns_and_opt_out(monkeypatch):
    with patch.object(turnwatch.threading, "Thread") as thread:
        turnwatch.on_agent_end({"chat_id": "telegram:1", "response": "API call failed after 3 retries"})
        turnwatch.on_agent_end({"chat_id": CHAT, "response": "Sent the headlines."})
        monkeypatch.setenv("A2A_TURN_NOTICE", "0")
        turnwatch.on_agent_end({"chat_id": CHAT, "response": "API call failed after 3 retries"})
    thread.assert_not_called()


# ── the gateway hook files ────────────────────────────────────────


def test_hook_files_install_and_call_back(_isolated_hermes_home):
    assert turnwatch.install_gateway_hook()
    hook_dir = _isolated_hermes_home / "hooks" / "a2a-dm-turnwatch"
    yaml_text = (hook_dir / "HOOK.yaml").read_text()
    assert "name: a2a-dm-turnwatch" in yaml_text and "- agent:end" in yaml_text

    # Load handler.py the way the gateway does and fire it.
    spec = importlib.util.spec_from_file_location("hermes_hook_test", hook_dir / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(turnwatch, "on_agent_end") as hit:
        module.handle("agent:end", {"chat_id": CHAT})
    hit.assert_called_once_with({"chat_id": CHAT})


def test_hook_install_refreshes_ours_and_keeps_user_files(_isolated_hermes_home):
    hook_dir = _isolated_hermes_home / "hooks" / "a2a-dm-turnwatch"
    hook_dir.mkdir(parents=True)
    (hook_dir / "HOOK.yaml").write_text("# a2a-dm-turnwatch-version: 0\nold")
    assert turnwatch.install_gateway_hook()
    assert "- agent:end" in (hook_dir / "HOOK.yaml").read_text()

    (hook_dir / "HOOK.yaml").write_text("name: mine\nevents: [agent:end]\n")
    assert turnwatch.install_gateway_hook()
    assert (hook_dir / "HOOK.yaml").read_text() == "name: mine\nevents: [agent:end]\n"


def test_register_installs_the_hook(_isolated_hermes_home, monkeypatch):
    import a2a_dm_hermes

    monkeypatch.delenv("AGORADIGEST_TOKEN", raising=False)
    a2a_dm_hermes.register(MagicMock())
    assert (_isolated_hermes_home / "hooks" / "a2a-dm-turnwatch" / "handler.py").exists()
