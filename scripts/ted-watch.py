#!/usr/bin/env python3
"""Tell Vandy when Ted stops working, over a channel that is not Ted.

Why this exists. `ted-gate-guard.py` answers "are the gates loaded" correctly,
but only when somebody runs it, and the person who most needs the answer is the
one away from the laptop. Hermes catches plugin load failures, logs one WARNING
and keeps serving, so an ungated Ted looks exactly like a healthy one from the
outside: messages still arrive, replies still come back, and nothing says the
18+ check and the no-deficit rule are gone.

WHAT 8 SEP 2026 ADDED. At 18:00 WhatsApp logged the linked device out. The
gateway stayed up and retried the bridge every five minutes, sixty-five times,
until 10:57 the next morning. Seventeen hours, thirteen daily reviews and two
reminders undelivered, and nobody knew until a user said so. Two things were
wrong and both are fixed here:

  * This watcher was never installed. The plist sat in scripts/ and was never
    copied into ~/Library/LaunchAgents, so it had never run once. `install`
    below is the missing step, and it is idempotent.
  * It only ever watched the gates. A perfect gate report says nothing about
    whether Ted can speak, so the link is now checked too.

WHY THE ALERT IS NOT WHATSAPP AT ALL. WhatsApp is the only platform Hermes has
configured, so a WhatsApp alert about a WhatsApp outage is a message that
cannot be sent. It was briefly kept as a second copy anyway, and on 9 Sep 2026
a --force test run put two "recovered" messages into Vandy's own thread with
Ted. That thread is the product; the machine does not get to use it to talk
about itself. The macOS notification is the whole alert now, and it has the
property that matters: no dependency on the thing being watched.

LOGGED OUT IS NOT DISCONNECTED. A dropped connection is worth retrying and the
gateway handles it alone. A logout is terminal: the saved session is dead, no
number of retries can revive it, and it needs a human holding a phone to scan a
QR. They are reported as different things because they need different actions.

Deliberately --check-only. The guard can stop a gateway that is serving ungated,
and that is right when a human is at the keyboard. Unattended it is wrong:
stopping is one way here, `hermes gateway start` needs Vandy, and on 4 Sep 2026
a stop with nobody watching left Ted answering nobody for 16 minutes. An alert
she can act on beats an outage she has to discover.

Alerts on transitions, not on every run, so a long red spell is one message and
not ninety-six a day. Recovery is announced too: silence after bad news reads as
a broken watcher. The gates and the link carry their own transition state, so a
flapping gate can never mask a dead link.

    python3 scripts/ted-watch.py              # check, alert on change
    python3 scripts/ted-watch.py --dry-run    # print, send nothing
    python3 scripts/ted-watch.py --force      # alert even with no change
    python3 scripts/ted-watch.py --install    # load the launchd job, then exit
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "ted-gate-guard.py"
PLIST_SRC = REPO / "scripts" / "ai.ted.gatewatch.plist"
PLIST_DST = Path.home() / "Library" / "LaunchAgents" / "ai.ted.gatewatch.plist"
LABEL = "ai.ted.gatewatch"

HERMES = Path.home() / ".hermes"
STATE = HERMES / "state" / "ted-watch-state.json"
GATEWAY_STATE = HERMES / "gateway_state.json"
BRIDGE_LOG = HERMES / "whatsapp" / "bridge.log"

# The exact line the bridge prints when the saved session is dead. Matched as a
# substring because the bridge decorates it with an emoji.
LOGGED_OUT_MARKER = "Logged out. Delete session and restart to re-authenticate."
CONNECTED_MARKER = "WhatsApp connected!"

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


def bridge_says_logged_out() -> bool:
    """True when the last thing the bridge said was that the session is dead.

    Ordering matters more than presence: the log keeps every logout ever, so
    "does the file contain the marker" is true forever once it happens. What
    decides the current state is which marker came last.
    """
    try:
        tail = BRIDGE_LOG.read_text(errors="replace").splitlines()[-400:]
    except OSError:
        return False
    last_out = last_ok = -1
    for index, line in enumerate(tail):
        if LOGGED_OUT_MARKER in line:
            last_out = index
        if CONNECTED_MARKER in line:
            last_ok = index
    return last_out > last_ok


def check_link() -> tuple[bool, str, bool]:
    """(ok, what to say, needs_a_human).

    `needs_a_human` separates the outage that fixes itself from the one that
    cannot. Only a logout sets it, because only a logout requires a phone.
    """
    try:
        state = json.loads(GATEWAY_STATE.read_text())
    except (OSError, ValueError) as exc:
        return False, f"cannot read gateway_state.json: {exc}", False

    if state.get("gateway_state") != "running":
        return False, f"gateway is {state.get('gateway_state')!r}, not running", False

    whatsapp = (state.get("platforms") or {}).get("whatsapp") or {}
    link = whatsapp.get("state")

    if bridge_says_logged_out():
        return False, "WhatsApp logged the device out", True
    if link == "connected":
        return True, "connected", False
    return False, f"WhatsApp is {link!r}", False


def notify(title: str, body: str, dry_run: bool) -> None:
    """The alert that does not depend on the thing being watched.

    osascript is used rather than a Hermes send precisely because it reaches
    the screen without a network, a token or a linked device.
    """
    if dry_run:
        print(f"--- would notify --- {title}: {body}")
        return
    # A notification body is one line on screen, so the newlines that read well
    # in WhatsApp are flattened here rather than silently truncated.
    flat = " ".join(body.split())[:240]
    script = (
        f'display notification {json.dumps(flat)} '
        f'with title {json.dumps(title)} sound name "Basso"'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"notify failed: {exc}", file=sys.stderr)


# NO WHATSAPP COPY. An earlier version of this file sent the alert to Vandy's
# own thread as a second copy. On 9 Sep 2026 a --force test run did what it was
# built to do and put two "recovered" messages into her chat with Ted, which is
# the product talking to her about its own plumbing. Ted's thread is for the
# user, not for the machine's status. The alert is a notification and nothing
# else; anything that needs to reach her away from the desk gets its own
# channel, not this one.


def install() -> int:
    """Copy the plist in and load it. Idempotent, so re-running is safe."""
    try:
        plistlib.loads(PLIST_SRC.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"refusing to install a plist that does not parse: {exc}", file=sys.stderr)
        return 1
    PLIST_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLIST_SRC, PLIST_DST)
    subprocess.run(["launchctl", "unload", str(PLIST_DST)], capture_output=True)
    done = subprocess.run(["launchctl", "load", str(PLIST_DST)], capture_output=True, text=True)
    if done.returncode != 0:
        print(f"launchctl load failed: {(done.stdout + done.stderr).strip()}", file=sys.stderr)
        return 1
    listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if LABEL not in listed.stdout:
        print(f"{LABEL} did not appear in launchctl list", file=sys.stderr)
        return 1
    print(f"installed and loaded {LABEL} -> {PLIST_DST}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    if args.install:
        return install()

    gates_ok, output = run_guard()
    link_ok, link_detail, needs_human = check_link()

    state = read_state()
    now = time.time()
    stamp = time.strftime("%H:%M")

    # Each component carries its own transition and its own repeat clock, so a
    # gate that flaps cannot swallow the alert for a link that died.
    components = [
        ("gates", gates_ok, "Ted's safety gates"),
        ("link", link_ok, "Ted's WhatsApp"),
    ]

    for key, ok, label in components:
        was = state.get(key)
        last_alert = state.get(f"{key}_last_alert_at", 0)
        changed = was is None or was != ok
        stale = (not ok) and (now - last_alert) > REPEAT_SECONDS
        should_alert = args.force or changed or stale

        if ok:
            title = f"✅ {label} is back"
            body = f"recovered at {stamp}."
        elif key == "gates":
            title = f"⚠️ {label} are NOT on"
            body = (
                f"{failing_lines(output)}\n\n"
                "Ted is still answering people, without the 18+ check or the "
                "no-deficit rule. On the laptop: npm run gates:guard"
            )
        elif needs_human:
            title = "🔴 Ted is logged out of WhatsApp"
            body = (
                f"{link_detail} at {stamp}. Retrying cannot fix this, it needs "
                "your phone. On the laptop: mv ~/.hermes/whatsapp/session aside, "
                "hermes whatsapp, scan the QR, hermes gateway restart."
            )
        else:
            title = f"⚠️ {label} is down"
            body = f"{link_detail} at {stamp}. Ted cannot send or receive."

        print(f"{key}: {'ok' if ok else 'FAILING'} ({link_detail if key == 'link' else stamp})")
        if not ok and key == "gates":
            print(failing_lines(output))

        # Nothing is announced on the very first healthy run: a watcher that
        # says hello the moment it is installed trains you to ignore it.
        if should_alert and not (ok and was is None):
            notify(title, body, args.dry_run)
            if not args.dry_run:
                state[f"{key}_last_alert_at"] = now
        state[key] = ok

    state["last_checked_at"] = now
    if not args.dry_run:
        write_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
