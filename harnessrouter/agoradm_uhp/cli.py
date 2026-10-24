"""``agoradm-uhp`` — run the bridge.

    export A2ADM_TOKEN=bt_...                 # the AgoraDM agent's token
    export HARNESSROUTER_API_KEY=...          # from the Console's API Keys page
    agoradm-uhp --harness-id chrn_... --model claude-sonnet-5.5

Secrets come from the environment or from files (``--token-file``,
``--api-key-file``), never from command-line values, which other local
users can read in the process list.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from agoradm import AgentClient
from agoradm.daemon import InboxDaemon

from agoradm_uhp import __version__
from agoradm_uhp.bridge import Bridge, BridgeConfig
from agoradm_uhp.state import BridgeState
from agoradm_uhp.uhp import UHPClient

DEFAULT_UHP_URL = "http://localhost:3000/api/harness"
DEFAULT_STATE = Path.home() / ".config" / "agoradm-uhp" / "state.json"


def _secret(env: str, file: Optional[str], what: str) -> str:
    if file:
        value = Path(file).expanduser().read_text().strip()
    else:
        value = os.environ.get(env, "").strip()
    if not value:
        sys.exit(f"agoradm-uhp: missing {what} — set {env} or pass the matching --*-file option")
    return value


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(prog="agoradm-uhp", description="Turn AgoraDM DMs into tasks on a UHP server.")
    p.add_argument("--harness-id", default=os.environ.get("HARNESSROUTER_HARNESS_ID"), help="configured harness id (chrn_…)")
    p.add_argument("--model", default=os.environ.get("HARNESSROUTER_MODEL"), help="model id; omit for the harness default")
    p.add_argument("--uhp-url", default=os.environ.get("HARNESSROUTER_BASE_URL", DEFAULT_UHP_URL))
    p.add_argument("--allow", default="friends", help='who may give work: "friends" (default), "any", or comma-separated bot ids')
    p.add_argument("--per-day", type=int, default=20, help="tasks per contact per day (default 20)")
    p.add_argument("--timeout", type=int, default=900, help="seconds per task (default 900)")
    p.add_argument("--name", default=os.environ.get("A2ADM_AGENT_NAME"), help="the agent's name, used in task instructions")
    p.add_argument("--instructions", help="extra guidance added to every task")
    p.add_argument("--token-file", help="file holding the AgoraDM bot token (else $A2ADM_TOKEN)")
    p.add_argument("--api-key-file", help="file holding the UHP API key (else $HARNESSROUTER_API_KEY)")
    p.add_argument("--state", default=str(DEFAULT_STATE), help=f"state file (default {DEFAULT_STATE})")
    p.add_argument("--api-base", default=os.environ.get("A2ADM_API_BASE"), help="AgoraDM API base (default: the SDK's)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"agoradm-uhp {__version__}")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.harness_id:
        sys.exit("agoradm-uhp: --harness-id is required (shown under the setup's name in the Console)")

    token = _secret("A2ADM_TOKEN", args.token_file, "the AgoraDM bot token")
    api_key = _secret("HARNESSROUTER_API_KEY", args.api_key_file, "the UHP API key")

    client = AgentClient(token=token, **({"api_base": args.api_base} if args.api_base else {}))
    name = args.name or "this agent"

    cfg = BridgeConfig(harness_id=args.harness_id, model=args.model, allow=args.allow,
                       per_day=args.per_day, timeout_seconds=args.timeout, agent_name=name,
                       extra_instructions=args.instructions)
    bridge = Bridge(client, UHPClient(args.uhp_url, api_key, timeout_s=args.timeout + 60), cfg,
                    BridgeState(Path(args.state).expanduser()))

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    logging.getLogger("agoradm_uhp").info(
        "%s → harness %s at %s (allow=%s, %d/day)", name, args.harness_id, args.uhp_url, args.allow, args.per_day)
    with InboxDaemon(client, handler=bridge.handle, interval_s=5.0):
        stop.wait()


if __name__ == "__main__":
    main()
