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
import os
import plistlib
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "ted-gate-guard.py"
PLIST_SRC = REPO / "scripts" / "ai.ted.gatewatch.plist"
PLIST_DST = Path.home() / "Library" / "LaunchAgents" / "ai.ted.gatewatch.plist"
LABEL = "ai.ted.gatewatch"

HERMES = Path.home() / ".hermes"
HERMES_ENV = HERMES / ".env"
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


PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_KEYS = ("PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN")

EMAIL_KEYS = ("TED_ALERT_EMAIL_TO", "TED_ALERT_SMTP_USER", "TED_ALERT_SMTP_PASSWORD")
EMAIL_DEFAULT_HOST = "smtp.gmail.com"
EMAIL_DEFAULT_PORT = 465


def setting(name: str) -> str:
    """One config value, from the environment or ~/.hermes/.env, else "".

    Both are read because the watcher runs under launchd, which inherits
    almost nothing, while a person testing it by hand has a shell full of
    exports. A value that works when you try it and vanishes at 3am is the
    kind of thing this whole file exists to stop.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        for line in HERMES_ENV.read_text().splitlines():
            key, _, raw = line.partition("=")
            if key.strip() == name:
                cleaned = raw.strip().strip("'\"")
                if cleaned:
                    return cleaned
    except OSError:
        pass
    return ""


def pushover_credentials() -> tuple[str, str] | None:
    """The user key and app token, or None when either is missing.

    None means "this channel is not set up", never an error. An unconfigured
    remote alert must not stop the desk alert going out, because a half
    configured watcher that refuses to run is worse than the one channel it
    already had.
    """
    found = {name: setting(name) for name in PUSHOVER_KEYS}
    if not all(found.values()):
        return None
    return found["PUSHOVER_USER_KEY"], found["PUSHOVER_API_TOKEN"]


def email_config() -> dict[str, Any] | None:
    """Where to mail an alert, or None when it is not set up.

    Gmail needs an app password rather than the account password, which means
    2-Step Verification has to be on first. That is a real step and the
    --test-alert output says so, because a silently refused login here looks
    identical to nothing being wrong.
    """
    found = {name: setting(name) for name in EMAIL_KEYS}
    if not all(found.values()):
        return None
    port = setting("TED_ALERT_SMTP_PORT")
    return {
        "to": found["TED_ALERT_EMAIL_TO"],
        "user": found["TED_ALERT_SMTP_USER"],
        "password": found["TED_ALERT_SMTP_PASSWORD"],
        "sender": setting("TED_ALERT_EMAIL_FROM") or found["TED_ALERT_SMTP_USER"],
        "host": setting("TED_ALERT_SMTP_HOST") or EMAIL_DEFAULT_HOST,
        "port": int(port) if port.isdigit() else EMAIL_DEFAULT_PORT,
    }


def send_email(title: str, body: str, urgent: bool, dry_run: bool) -> str:
    """Mail the alert somewhere that is not this laptop and not WhatsApp.

    Free, which is why it is here: the channel that gets used is the one
    nobody has to pay for on the day they set it up.

    Subject carries the whole headline, because a phone lock screen shows the
    subject and little else, and an alert you have to open to understand is an
    alert you will open later.
    """
    config = email_config()
    if config is None:
        return "not configured"
    if dry_run:
        return f"would email {config['to']}"
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = config["to"]
    message["Subject"] = f"{'[Ted] ' if urgent else '[Ted ok] '}{title}"
    message.set_content(
        f"{body}\n\n"
        f"Sent by ted-watch.py on {socket.gethostname()} at "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
        "This is Ted's watchdog, not Ted. It never messages users.\n"
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as server:
            server.login(config["user"], config["password"])
            server.send_message(message)
        return "sent"
    except smtplib.SMTPAuthenticationError:
        return "refused the login (app password wrong, or 2-Step not on)"
    except Exception as exc:  # noqa: BLE001 - an alert channel may never crash the watcher
        return f"failed ({exc})"


def push(title: str, body: str, urgent: bool, dry_run: bool) -> str:
    """Send the alert to a phone that is not this laptop and not WhatsApp.

    This is the channel the 8 Sep 2026 outage needed and did not have. The
    gateway was logged out for seventeen hours; the only alarm was a macOS
    notification popping up to an empty room, and Ted could not report it over
    WhatsApp because WhatsApp was the thing that was down.

    Pushover is a plain HTTPS POST with no SDK, so the watcher keeps its only
    dependency being Python itself. Every failure here is swallowed on
    purpose: this function exists to add a road, never to remove one.
    """
    credentials = pushover_credentials()
    if credentials is None:
        return "not configured"
    user_key, api_token = credentials
    if dry_run:
        return "would send"
    payload = urllib.parse.urlencode(
        {
            "token": api_token,
            "user": user_key,
            "title": title,
            "message": " ".join(body.split())[:1024],
            # 1 shows on the phone as a high-priority alert that bypasses a
            # quiet period. Recoveries go out at 0 so good news never wakes
            # anybody up.
            "priority": "1" if urgent else "0",
        }
    ).encode()
    request = urllib.request.Request(PUSHOVER_URL, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status == 200:
                return "sent"
            return f"refused (HTTP {response.status})"
    except Exception as exc:  # noqa: BLE001 - a phone alert may never crash the watcher
        return f"failed ({exc})"


REMOTE_CHANNELS = (("email", send_email), ("pushover", push))


def remote_alerts(title: str, body: str, urgent: bool, dry_run: bool) -> list[tuple[str, str]]:
    """Every configured channel that is not this screen, and what each did.

    All of them fire, rather than the first that works. They are cheap, they
    fail independently, and the whole point of this file is that one road
    being out is not a reason to be uninformed. Channels that are not set up
    say so and cost nothing.
    """
    return [(name, send(title, body, urgent, dry_run)) for name, send in REMOTE_CHANNELS]


def notify(title: str, body: str, dry_run: bool, urgent: bool = True) -> None:
    """The alert that does not depend on the thing being watched.

    Two kinds of road, on purpose. osascript reaches the screen without a
    network, a token or a linked device, which is what makes it worth keeping
    even though it is useless when she is out; the remote channels reach her
    when she is not at the screen, which is the half that was missing all of
    this week. None of them is WhatsApp.
    """
    if dry_run:
        print(f"--- would notify --- {title}: {body}")
        for name, result in remote_alerts(title, body, urgent, dry_run=True):
            print(f"--- {name} --- {result}")
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
    for name, result in remote_alerts(title, body, urgent, dry_run=False):
        if result != "sent":
            print(f"{name} alert: {result}", file=sys.stderr)


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


def test_alert() -> int:
    """Prove the phone alert works, without waiting for something to break.

    A channel nobody has ever seen fire is not a channel anybody trusts, and
    the failure this exists to report is exactly the moment you cannot afford
    to be discovering a typo in a key. Touches no user, no WhatsApp and no
    saved state: it sends one notification down both roads and says what each
    one did.
    """
    ready = {
        "email": email_config() is not None,
        "pushover": pushover_credentials() is not None,
    }
    for name, ok in ready.items():
        print(f"{name:9s} {'configured' if ok else 'not configured'}")

    if not any(ready.values()):
        print()
        print("  No channel can reach you away from the laptop yet.")
        print()
        print("  For email, set these three:")
        for name in EMAIL_KEYS:
            print(f"    {name}")
        print(f"  Either as environment variables, or as lines in {HERMES_ENV}.")
        print()
        print("  With Gmail, TED_ALERT_SMTP_PASSWORD is an app password, not")
        print("  your normal one. Turn on 2-Step Verification first, then make")
        print("  one at myaccount.google.com/apppasswords. The normal password")
        print("  will simply be refused, which looks like nothing happening.")
        print()
        print("  Optional: TED_ALERT_EMAIL_FROM, TED_ALERT_SMTP_HOST,")
        print(f"  TED_ALERT_SMTP_PORT (default {EMAIL_DEFAULT_HOST}:{EMAIL_DEFAULT_PORT}).")
        print()
        print("  Until one is set the desk notification still fires, so")
        print("  nothing is broken while this is pending.")
        return 1

    title = "Ted alert test"
    body = (
        "If you are reading this away from the laptop, the alarm can now "
        "reach you. Nothing is wrong, this is a test you asked for."
    )
    results = remote_alerts(title, body, urgent=False, dry_run=False)
    print()
    worked = False
    for name, result in results:
        if result == "not configured":
            continue
        print(f"  {name}: {result}")
        worked = worked or result == "sent"

    print()
    if worked:
        print("  Sent. Check the device you expect to be alerted on.")
        print("  This went out as a recovery, so a real failure will be louder.")
        return 0
    print("  Nothing got through. The line above says why.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="send one harmless alert to prove the phone channel works",
    )
    args = parser.parse_args()

    if args.install:
        return install()

    if args.test_alert:
        return test_alert()

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
