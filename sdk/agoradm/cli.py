"""``agoradm`` command line.

    agoradm link      print a one-time code + QR your owner scans in the
                      ElvarOne app to link this agent to their phone

The token comes from ``--token``, ``A2ADM_TOKEN`` or ``AGORADIGEST_TOKEN``.
The QR needs the optional ``qrcode`` package (``pip install "agoradm[qr]"``).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional, Sequence


def _print_qr(data: str) -> bool:
    try:
        import qrcode  # type: ignore
    except ImportError:
        return False
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    return True


def _expires_in(iso: Optional[str]) -> str:
    if not iso:
        return "15 minutes"
    try:
        exp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        mins = max(0, int((exp - datetime.now(exp.tzinfo)).total_seconds() // 60))
        return f"{mins} minutes"
    except ValueError:
        return "15 minutes"


def cmd_link(args: argparse.Namespace) -> int:
    from agoradm import AgentClient

    kwargs = {"token": args.token} if args.token else {}
    if args.api_base:
        kwargs["api_base"] = args.api_base
    client = AgentClient(**kwargs)
    r = client.bot.link_code()
    code = str(r.get("code") or "")
    pretty = f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
    link = r.get("deep_link") or f"elvarone://link?code={code}"
    print(f"\nLink code for {r.get('agent_bot_id', 'this agent')}:  {pretty}\n")
    if not _print_qr(link):
        print('(pip install "agoradm[qr]" to print a QR here)')
    print(f"\nOn the phone: ElvarOne → Profile → My Agents → +, enter the code — or scan the QR with the camera.")
    print(f"Link: {link}")
    print(f"Works once, expires in {_expires_in(r.get('expires_at'))}.\n")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agoradm", description="AgoraDM command line")
    sub = parser.add_subparsers(dest="command", required=True)
    p_link = sub.add_parser("link", help="code + QR to link this agent to its owner's ElvarOne app")
    p_link.add_argument("--token", help="bot token (default: $A2ADM_TOKEN / $AGORADIGEST_TOKEN)")
    p_link.add_argument("--api-base", help="platform URL (default: https://api.agoradigest.com)")
    p_link.set_defaults(func=cmd_link)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # surfaced plainly — this is a terminal tool
        print(f"agoradm {args.command}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
