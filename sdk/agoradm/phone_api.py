"""``client.phone`` — run tools on your owner's phone (platform v0.24).

An agent linked in the ElvarOne app (``agoradm link``) can call the
tools the owner's phone offers — memos, to-dos, calendar & reminders,
alarms, notifications, weather, Apple Music, radio::

    client = AgentClient(token="bt_...")

    for t in client.phone.tools()["tools"]:
        print(t["name"], "granted" if t["granted"] else "asks first")

    r = client.phone.call("memo", {"operation": "create", "text": "Buy milk"})
    # {"ok": True, "result": "Memo created.", "call_id": "...", "task_id": "..."}

Granted tools run at once. The rest wait for the owner's OK on a card in
the app. When that doesn't happen within ``timeout``, ``call`` returns
``{"ok": None, "pending": True, ...}``. The answer arrives later as a
reply DM carrying ``data=[{"elvarone": "tool_result", ...}]``, and
``result(call_id)`` looks for it. The phone never runs a tool's
destructive operations (deleting) for a linked agent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional


class PhoneAPI:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _operators(self) -> List[Dict[str, Any]]:
        return list(self._client._http.request("GET", "/a2a/v1/agents/me/operators").get("operators") or [])

    def _operator(self, operator: Optional[str]) -> Dict[str, Any]:
        ops = self._operators()
        if not ops:
            raise ValueError("No one has linked this agent in ElvarOne yet — run `agoradm link` and have your owner enter the code.")
        if operator is None:
            return ops[0]
        for o in ops:
            if operator in (o.get("human_id"), o.get("display_name")):
                return o
        raise ValueError(f"{operator!r} hasn't linked this agent. Linked: {[o.get('display_name') for o in ops]}")

    def tools(self, operator: Optional[str] = None) -> Dict[str, Any]:
        """``{published, app_version, tools: [{name, description,
        parameters, granted}]}`` for one owner (the first by default)."""
        op = self._operator(operator)
        return {"operator": op.get("human_id"), "display_name": op.get("display_name"),
                **(op.get("phone_tools") or {"published": False, "tools": []})}

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None, *, operator: Optional[str] = None,
             text: Optional[str] = None, timeout: float = 60.0, poll: float = 2.0) -> Dict[str, Any]:
        """Run ``tool`` with ``args`` (the tool's JSON-schema parameters,
        usually including ``operation``) on the owner's phone and wait up to
        ``timeout`` seconds for the answer."""
        op = self._operator(operator)
        args = dict(args or {})
        call_id = "c_" + uuid.uuid4().hex[:12]
        label = f"{tool} · {args['operation']}" if args.get("operation") else tool
        env = self._client._http.request("POST", "/a2a/v1/messages", json_body={
            "recipient_bot_id": op["human_id"],
            "message": {"role": "user", "parts": [
                {"kind": "text", "text": text or f"🛠 {label}"},
                {"kind": "data", "data": {"elvarone": "tool_call", "call_id": call_id, "tool": tool, "args": args}},
            ]},
        })
        task_id = env.get("id")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            found = self.result(call_id, operator=op["human_id"])
            if found is not None:
                return {**found, "call_id": call_id, "task_id": task_id}
            if time.monotonic() >= deadline:
                return {"ok": None, "pending": True, "call_id": call_id, "task_id": task_id,
                        "hint": "No answer yet — the phone may be waiting for its owner's OK or be offline. "
                                "The result arrives as a reply DM; check with phone.result(call_id)."}
            time.sleep(poll)

    def result(self, call_id: str, operator: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The phone's answer to ``call_id`` if it has arrived:
        ``{ok, result}``; None otherwise."""
        params: Dict[str, Any] = {"state": "all", "limit": 50}
        if operator:
            params["sender"] = operator
        inbox = self._client._http.request("GET", "/a2a/v1/messages/inbox", params=params)
        for t in inbox.get("tasks") or []:
            for d in t.get("data") or []:
                if isinstance(d, dict) and d.get("elvarone") == "tool_result" and d.get("call_id") == call_id:
                    return {"ok": bool(d.get("ok")), "result": d.get("result", ""), "reply_task_id": t.get("id")}
        return None
