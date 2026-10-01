"""Tell the sender when a wake turn dies (v0.1.5).

When the model provider is down, Hermes retries, gives up and ends the
turn with an error string ("API call failed after 3 retries: …"). The
DM was already marked read on wake (0.1.3), so the sender saw "typing…"
for minutes and then nothing (DeepSeek outage, 2026-10-01).

Hermes returns early on that path, so the plugin hooks
(``post_llm_call`` / ``on_session_end``) never fire. The gateway's own
``agent:end`` event does, with the turn's chat id and response text.
Gateway hooks are loaded from ``$HERMES_HOME/hooks/<name>/`` right
after plugins, so :func:`install_gateway_hook` drops a two-file hook
there at plugin load; it calls :func:`on_agent_end`.

A wake turn's chat id is ``webhook:a2a-dm-wake:<task_id>`` (the task id
is the delivery id, see :mod:`a2a_dm_hermes.autowake`). When such a turn
ends in an error and the DM still has no reply, we answer it with a
short notice so the sender knows to try again.

Env:
  A2A_TURN_NOTICE  "1" (default) — set "0" to turn the notice off.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from a2a_dm_hermes.gatewaycfg import WAKE_ROUTE

logger = logging.getLogger(__name__)

HOOK_NAME = "a2a-dm-turnwatch"
HOOK_VERSION = 1
_MARKER = f"a2a-dm-turnwatch-version: {HOOK_VERSION}"

_HOOK_YAML = f"""# {_MARKER} — installed by the a2a-dm plugin; rewritten on upgrade.
name: {HOOK_NAME}
description: Tell an a2a-dm sender when the turn their DM woke failed.
events:
  - agent:end
"""

_HOOK_HANDLER = f'''# {_MARKER} — installed by the a2a-dm plugin; rewritten on upgrade.
def handle(event_type, context):
    try:
        from a2a_dm_hermes.turnwatch import on_agent_end
    except Exception:  # plugin uninstalled — stay silent
        return None
    on_agent_end(context or {{}})
    return None
'''

# The shapes Hermes gives a turn that died (conversation_loop's
# max-retries string and the gateway's normalized replies).
_FAILED_RE = re.compile(
    r"^\W*("
    r"api\s+(?:call\s+)?failed"
    r"|provider\s+authentication\s+failed"
    r"|the\s+model\s+provider\s+(?:failed|rejected|is\s+rate-limiting)"
    r"|the\s+request\s+failed"
    r"|processing\s+(?:stopped|completed\s+but\s+no\s+response)"
    r"|session\s+too\s+large"
    r"|non-retryable\s+error"
    r"|rate\s+limited\s+after\s+\d+\s+retries"
    r"|error\s+code\s*:"
    r"|http\s*\d{3}\b"
    r"|(?:incorrect|invalid)\s+api\s+key"
    r")",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(r"authentication|api\s+key|\b401\b", re.IGNORECASE)
_RATE_RE = re.compile(r"rate[\s-]+limit", re.IGNORECASE)
_SIZE_RE = re.compile(r"too\s+large|context\s+window", re.IGNORECASE)
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")

_DONE_STATES = {"completed", "failed", "canceled", "cancelled", "rejected"}

_noticed: deque = deque(maxlen=512)
_noticed_lock = threading.Lock()


def enabled() -> bool:
    return (os.environ.get("A2A_TURN_NOTICE") or "1").strip() not in ("0", "false", "no")


def _hooks_dir() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "hooks" / HOOK_NAME


def install_gateway_hook() -> bool:
    """Write ``$HERMES_HOME/hooks/a2a-dm-turnwatch/`` if missing or ours
    and stale. Files without our marker are the user's; left alone."""
    hook_dir = _hooks_dir()
    files = {"HOOK.yaml": _HOOK_YAML, "handler.py": _HOOK_HANDLER}
    try:
        for name, desired in files.items():
            path = hook_dir / name
            if path.exists():
                current = path.read_text(encoding="utf-8")
                if "a2a-dm-turnwatch-version:" not in current:
                    logger.debug("a2a-dm: %s is user-owned, not touching it", path)
                    return True
                if current == desired:
                    continue
            hook_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(desired, encoding="utf-8")
        return True
    except OSError:
        logger.warning("a2a-dm: could not install gateway hook at %s", hook_dir, exc_info=True)
        return False


def task_id_for_chat(chat_id: str) -> Optional[str]:
    """The DM task a wake turn's chat id belongs to, else None."""
    prefix = f"webhook:{WAKE_ROUTE}:"
    if not isinstance(chat_id, str) or not chat_id.startswith(prefix):
        return None
    return chat_id[len(prefix):].strip() or None


def looks_failed(response: str) -> bool:
    return bool(response) and bool(_FAILED_RE.search(response.strip()))


def notice_text(response: str, original: str = "") -> str:
    """The reply the sender gets — in Chinese when they wrote Chinese."""
    zh = bool(_CJK_RE.search(original or ""))
    if _AUTH_RE.search(response):
        why = ("模型服务认证失败（API key 可能失效了）", "my model provider rejected its credentials")
    elif _RATE_RE.search(response):
        why = ("模型服务在限流", "my model provider is rate-limiting me")
    elif _SIZE_RE.search(response):
        why = ("这次的上下文太长了", "this conversation got too long for my model")
    else:
        why = ("模型服务暂时没有响应", "my model provider isn't responding right now")
    if zh:
        return f"⚠️ 这条我没处理完：{why[0]}。稍后再发一次试试。"
    return f"⚠️ I couldn't finish this one: {why[1]}. Please try again in a bit."


def _first_notice(task_id: str) -> bool:
    with _noticed_lock:
        if task_id in _noticed:
            return False
        _noticed.append(task_id)
        return True


def _client():
    from a2a_dm_hermes.runtime import WakeRuntime
    from a2a_dm_hermes.tools import _get_client

    return WakeRuntime.get()._client or _get_client()


def send_notice(task_id: str, response: str) -> bool:
    """Reply to *task_id* with the failure notice unless it already has
    a reply or is a group message. Returns True if a notice went out."""
    client = _client()
    if client is None:
        return False
    try:
        task = client.dm.get_task(task_id)
    except Exception:  # noqa: BLE001
        logger.debug("a2a-dm: turn notice — task %s lookup failed", task_id[:12], exc_info=True)
        return False
    if (task.state or "").lower() in _DONE_STATES:
        return False  # the agent replied before the turn died
    if task.message_kind == "group" or getattr(task, "group_id", None):
        return False
    original = task.message.text if task.message else ""
    try:
        client.dm.reply(task_id, notice_text(response, original))
    except Exception:  # noqa: BLE001
        logger.warning("a2a-dm: turn notice for %s failed", task_id[:12], exc_info=True)
        return False
    logger.info("a2a-dm: wake turn for %s failed — told the sender", task_id[:12])
    return True


def on_agent_end(context: dict) -> None:
    """Gateway ``agent:end`` handler. Runs on the gateway's event loop,
    so the network work goes to a thread."""
    if not enabled():
        return
    task_id = task_id_for_chat(context.get("chat_id") or "")
    response = context.get("response") or ""
    if not task_id or not looks_failed(response):
        return
    if not _first_notice(task_id):
        return
    threading.Thread(
        target=send_notice, args=(task_id, response),
        daemon=True, name="a2a-dm-turn-notice",
    ).start()
