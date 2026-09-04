#!/usr/bin/env python3
"""Tell Vandy on WhatsApp when Ted's safety gates stop being on.

Why this exists. `ted-gate-guard.py` answers "are the gates loaded" correctly,
but only when somebody runs it, and the person who most needs the answer is the
one away from the laptop. Hermes catches plugin load failures, logs one WARNING
and keeps serving, so an ungated Ted looks exactly like a healthy one from the
outside: messages still arrive, replies still come back, and nothing says the
18+ check and the no-deficit rule are gone.

Deliberately --check-only. The guard can stop a gateway that is serving ungated,
and that is right when a human is at the keyboard. Unattended it is wrong:
stopping is one way here, `hermes gateway start` needs Vandy, and on 4 Sep 2026
a stop with nobody watching left Ted answering nobody for 16 minutes. An alert
she can act on beats an outage she has to discover.

Alerts on transitions, not on every run, so a long red spell is one message and
not ninety-six a day. Recovery is announced too: silence after bad news reads as
a broken watcher.

    python3 scripts/ted-watch.py              # check, alert on change
    python3 scripts/ted-watch.py --dry-run    # print, send nothing
    python3 scripts/ted-watch.py --force      # alert even with no change
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "ted-gate-guard.py"
STATE = Path.home() / ".hermes" / "state" / "ted-watch-state.json"
TARGET = "whatsapp:Vandana :)"

# While it stays broken, repeat once every four hours. Long enough not to be a
# nuisance, short enough that a red gate cannot sit unnoticed through a night.
REPEAT_SECONDS = 4 * 60 * 60


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        print(f"could not save state: {exc}", file=sys.stderr)


def run_guard() -> tuple[bool, str]:
    """(healthy, what the guard said). A crash is not health."""
    try:
        done = subprocess.run(
            [sys.executable, str(GUARD), "--check-only"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the guard itself could not run: {exc}"
    output = (done.stdout + done.stderr).strip()
    return done.returncode == 0, output


def failing_lines(output: str) -> str:
    lines = [ln.strip() for ln in output.splitlines() if "FAIL" in ln or "STALE" in ln]
    return "\n".join(lines) if lines else output[-400:]


def send(text: str, dry_run: bool) -> bool:
    if dry_run:
        print("--- would send ---")
        print(text)
        return True
    try:
        done = subprocess.run(
            ["hermes", "send", "--to", TARGET, "--quiet", text],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"send failed: {exc}", file=sys.stderr)
        return False
    if done.returncode != 0:
        print(f"send failed: {(done.stdout + done.stderr).strip()}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    healthy, output = run_guard()
    state = read_state()
    was_healthy = state.get("healthy")
    last_alert = state.get("last_alert_at", 0)
    now = time.time()

    changed = was_healthy is None or was_healthy != healthy
    stale = (not healthy) and (now - last_alert) > REPEAT_SECONDS
    should_alert = args.force or changed or stale

    stamp = time.strftime("%H:%M")
    if healthy:
        body = f"✅ Ted's safety gates are back on. ({stamp})"
    else:
        body = (
            f"⚠️ Ted's safety gates are NOT on. ({stamp})\n\n"
            f"{failing_lines(output)}\n\n"
            "Ted is still answering people, without the 18+ check or the "
            "no-deficit rule. On the laptop: npm run gates:guard"
        )

    print(("healthy" if healthy else "UNHEALTHY") + f" at {stamp}")
    if not healthy:
        print(failing_lines(output))

    if should_alert and not (healthy and was_healthy is None):
        # Nothing is announced on the very first healthy run: a watcher that
        # says hello the moment it is installed trains you to ignore it.
        if send(body, args.dry_run) and not args.dry_run:
            state["last_alert_at"] = now
    state["healthy"] = healthy
    state["last_checked_at"] = now
    if not args.dry_run:
        write_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
