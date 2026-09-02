#!/usr/bin/env python3
"""Read back the replies users have reported as wrong (milestone 11).

A report is stored by the safety gate the moment a user says "report that" —
the exact turn, verbatim, not the model's summary of it. This is the read-back
side: without it the record exists but nobody can see it, which is the same as
not having it.

    npm run reports            # the 20 most recent
    npm run reports -- --all   # up to 200
    npm run reports -- --json  # for piping somewhere else

Reaches Convex with the shared secret from ~/.hermes/.env, the same way the
gate does. This is the builder's view: it is never exposed as a model tool, so
it cannot become a route for one user's turn to read another's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")


def load_env() -> dict[str, str]:
    """Environment first, then ~/.hermes/.env — same precedence as the gate."""
    found = {name: os.environ.get(name, "") for name in REQUIRED}
    if all(found.values()) or not HERMES_ENV.exists():
        return found
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in REQUIRED and not found.get(key):
            found[key] = value.strip().strip('"').strip("'")
    return found


def fetch(limit: int) -> dict:
    env = load_env()
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise SystemExit(
            f"{' and '.join(missing)} is not set in the environment or {HERMES_ENV}"
        )
    request = urllib.request.Request(
        env["TED_CONVEX_SITE_URL"].rstrip("/") + "/ted-memory",
        data=json.dumps(
            {"action": "reports", "whatsappUserId": "builder-readback", "limit": limit}
        ).encode("utf-8"),
        headers={
            "authorization": f"Bearer {env['TED_HERMES_SHARED_SECRET']}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Convex refused the read: HTTP {error.code} {error.reason}")
    except (OSError, ValueError) as error:
        raise SystemExit(f"Could not reach Convex: {error}")


def render(reports: list[dict]) -> None:
    if not reports:
        print("No reported replies. Users report one by saying 'report that'.")
        return

    print(f"{len(reports)} reported repl{'y' if len(reports) == 1 else 'ies'}, newest first.\n")
    for report in reports:
        stamp = report.get("reportedAt")
        when = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp / 1000))
            if isinstance(stamp, (int, float))
            else "unknown time"
        )
        # The stored id is already a one-way hash; the tail is enough to tell
        # two reporters apart without putting the whole key on screen.
        who = str(report.get("whatsappUserId") or "")[-8:] or "unknown"
        flag = "" if report.get("reviewedAt") else "  [unreviewed]"
        print(f"── {when}   user …{who}{flag}")
        for label, key in (("they said", "userMessage"), ("Ted said", "assistantMessage")):
            body = str(report.get(key) or "").strip() or "(empty)"
            wrapped = textwrap.indent(
                textwrap.fill(body, width=78, max_lines=8, placeholder=" …"),
                "      ",
            )
            print(f"   {label}:\n{wrapped}")
        if report.get("note"):
            print(f"   note: {report['note']}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="up to 200, not 20")
    parser.add_argument("--json", action="store_true", help="raw JSON")
    args = parser.parse_args()

    payload = fetch(200 if args.all else 20)
    if not payload.get("success"):
        raise SystemExit(f"Convex said: {payload.get('error', 'unknown error')}")

    reports = payload.get("reports") or []
    if args.json:
        json.dump(reports, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0
    render(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
