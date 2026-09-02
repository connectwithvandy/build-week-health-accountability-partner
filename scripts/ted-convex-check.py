#!/usr/bin/env python3
"""Refuse to let the gateway restart onto a Convex that cannot answer it.

The safety gate and the Convex backend are deployed by completely different
means. The gateway reloads `hermes/ted_safety_gates/__init__.py` from the repo
the moment it restarts; Convex only changes when someone runs a deploy. The
gate is therefore always the side that moves first, and nothing used to notice.

On 2 Sep 2026 the gate gained three new `logDailyEntry` arguments. Production
rejected them with `ArgumentValidationError`, and two new actions did not exist
there at all. Restarting the gateway at that moment would have broken every
meal log and silently suppressed five live reminders — with no error anywhere a
user or the builder would see. This is the check that would have caught it.

    npm run convex:check

Every probe is side-effect free. Existence comes from a read-only
`capabilities` call. Argument compatibility is proved by sending the exact
arguments the gate sends, with one field deliberately malformed so the mutation
throws on it *after* argument validation and before it touches the database —
which is precisely the difference this script needs to measure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")

# A key that belongs to nobody. Only ever sent with payloads that throw before
# any row is written, so it never creates a user (order 07 got fixture keys out
# of live state; they are not going back in).
PROBE_KEY = "whatsapp:sha256:" + "0" * 64


def _ok(message: str) -> str:
    return f"  ok    {message}"


def _fail(message: str) -> str:
    return f"  FAIL  {message}"


def load_env() -> dict[str, str]:
    found = {name: os.environ.get(name, "") for name in REQUIRED_ENV}
    if all(found.values()) or not HERMES_ENV.exists():
        return found
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in REQUIRED_ENV and not found.get(key.strip()):
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found


class Backend:
    def __init__(self, env: dict[str, str]) -> None:
        self.url = env["TED_CONVEX_SITE_URL"].rstrip("/") + "/ted-memory"
        self.secret = env["TED_HERMES_SHARED_SECRET"]
        self.host = env["TED_CONVEX_SITE_URL"].split("//")[-1].split(".")[0]

    def call(self, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "authorization": f"Bearer {self.secret}",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                return error.code, json.loads(body or "{}")
            except ValueError:
                return error.code, {"error": body[:300]}
        except (OSError, ValueError) as error:
            raise SystemExit(f"  FAIL  could not reach Convex: {error}")


# Each probe sends the arguments the gate really sends, with one field made
# invalid so the handler raises on it before writing anything. Seeing that
# specific complaint back means argument validation passed — the contract
# matches. Seeing ArgumentValidationError means it does not.
PROBES = (
    {
        "action": "log",
        "why": "meal, water, steps and workout logging",
        "payload": {
            "localDate": "not-a-date",
            "entryType": "meal",
            "source": "text",
            "occurredAt": 0,
            "today": "2026-01-01",
            "dateConfirmed": False,
            "secondOneConfirmed": False,
        },
        "expect": "localDate",
    },
    {
        "action": "reminderGate",
        "why": "quiet hours, pause and the per-day reminder cap",
        "payload": {"nowLocalTime": "not-a-time", "today": "2026-01-01"},
        "expect": "nowLocalTime",
    },
    {
        "action": "report",
        "why": "storing a reply the user reported as wrong",
        "payload": {
            "localDate": "not-a-date",
            "userMessage": "probe",
            "assistantMessage": "probe",
        },
        "expect": "localDate",
    },
)


def check(backend: Backend) -> tuple[list[str], bool]:
    from hermes.ted_safety_gates import REQUIRED_CONVEX_ACTIONS

    report: list[str] = []
    broken = False

    status, body = backend.call({"action": "capabilities", "whatsappUserId": PROBE_KEY})
    deployed: set[str] | None = None
    if body.get("success"):
        deployed = set(body.get("actions") or [])
    else:
        # A deployment older than the capabilities endpoint itself. Say so, then
        # keep going: the probes below still answer the question that matters,
        # and a report that names the actual gap is worth more than one that
        # stops at "too old".
        detail = str(body.get("error") or f"HTTP {status}")
        report.append(
            _fail(
                f"{backend.host} does not answer 'capabilities' ({detail}) — it "
                "predates this check. Probing the actions the gate calls instead."
            )
        )
        broken = True

    if deployed is not None:
        missing = sorted(REQUIRED_CONVEX_ACTIONS - deployed)
        if missing:
            report.append(
                _fail(
                    f"{backend.host} is missing "
                    + ", ".join(missing)
                    + " — the gate calls these and would get 'Unsupported action'."
                )
            )
            broken = True
        else:
            report.append(
                _ok(
                    f"{backend.host} supports all {len(REQUIRED_CONVEX_ACTIONS)} "
                    "actions the gate calls"
                )
            )
        extra = sorted(deployed - REQUIRED_CONVEX_ACTIONS)
        if extra:
            # Not a failure: a backend ahead of the gate is the safe direction.
            report.append(
                _ok(f"{backend.host} also has {', '.join(extra)} (unused by the gate)")
            )

    # A read-only existence check for the one action with no side effect and no
    # argument worth probing.
    _, listed = backend.call(
        {"action": "reports", "whatsappUserId": PROBE_KEY, "limit": 1}
    )
    if str(listed.get("error") or "") == "Unsupported action":
        report.append(_fail("'reports' is missing — npm run reports would fail."))
        broken = True
    elif listed.get("success"):
        report.append(_ok("'reports' answers"))

    for probe in PROBES:
        if deployed is not None and probe["action"] not in deployed:
            continue  # Already reported as missing above.
        _, result = backend.call(
            {"action": probe["action"], "whatsappUserId": PROBE_KEY, **probe["payload"]}
        )
        if str(result.get("error") or "") == "Unsupported action":
            report.append(
                _fail(
                    f"'{probe['action']}' is missing — {probe['why']} would break "
                    "on restart."
                )
            )
            broken = True
            continue
        error = str(result.get("error") or "")
        if "ArgumentValidationError" in error:
            field = error.split("extra field ")[-1].split(" ")[0].strip("`") or "?"
            report.append(
                _fail(
                    f"'{probe['action']}' rejects an argument the gate sends ({field}) — "
                    f"{probe['why']} would break on restart."
                )
            )
            broken = True
        elif probe["expect"] in error:
            report.append(_ok(f"'{probe['action']}' accepts the gate's arguments"))
        else:
            report.append(
                _fail(
                    f"'{probe['action']}' answered something unexpected: {error[:120] or result}"
                )
            )
            broken = True

    return report, broken


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    env = load_env()
    absent = [name for name in REQUIRED_ENV if not env.get(name)]
    if absent:
        print(_fail(f"{' and '.join(absent)} is not set in the environment or {HERMES_ENV}"))
        return 2

    backend = Backend(env)
    report, broken = check(backend)
    print("\n".join(report))

    if broken:
        print(
            "\nThe deployed Convex cannot answer the code in this repo.\n"
            "Deploy Convex FIRST, then restart the gateway:\n"
            "  npx convex deploy && hermes gateway restart && npm run gates:guard"
        )
        return 1
    print("\nConvex matches the code in this repo. Safe to restart the gateway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
