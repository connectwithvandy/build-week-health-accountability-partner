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
import re
import shutil
import smtplib
import sqlite3
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
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
AGENT_LOG = HERMES / "logs" / "agent.log"

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


# Errors that never heal on their own. A connection reset is worth a retry and
# not a 3am notification; a bill is not going to pay itself, and the retry
# quietly succeeds against the fallback so nothing downstream ever looks wrong.
MODEL_DEAD_ENDS = (
    ("credit balance is too low", "the Anthropic credit balance is empty"),
    ("insufficient_quota", "the provider quota is used up"),
    ("invalid_api_key", "the API key is not valid"),
    ("authentication_error", "the API key was rejected"),
    ("permission_error", "the API key is not allowed to use that model"),
)
MODEL_WINDOW_HOURS = 24
LOG_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def configured_primary() -> tuple[str, str] | None:
    """(provider, model) the gateway is meant to be using, or None.

    Read through ted-pin-cron-jobs.py's own parser rather than a second copy
    here. Which model counts as "the primary" is exactly the kind of fact that
    goes wrong when two files answer it differently.
    """
    import importlib.util

    source = Path(__file__).resolve().parent / "ted-pin-cron-jobs.py"
    if not source.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("ted_pin_cron_jobs", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.current_config()
    except Exception:  # noqa: BLE001 - a missing config must not break the check
        return None


def primary_model_recovered_since(last_failure: "datetime | None") -> "datetime | None":
    """When the primary model last answered, if that was after `last_failure`.

    Reads `session_model_usage`, which records a row per model actually billed,
    so a successful call on the configured provider is positive evidence rather
    than an absence of errors.

    Fails towards the alarm. Anything unreadable here returns None, which leaves
    the failure reported: a false alarm costs a look, a missed outage cost ten
    days last time.
    """
    if last_failure is None:
        return None
    primary = configured_primary()
    if not primary:
        return None
    provider, model = primary
    try:
        connection = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT MAX(last_seen) FROM session_model_usage "
            "WHERE model = ? AND billing_provider = ?",
            (model, provider),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if not row or not row[0]:
        return None
    when = datetime.fromtimestamp(float(row[0]))
    return when if when > last_failure else None


def check_model() -> tuple[bool, str]:
    """Whether Ted is still talking to the model it is supposed to be.

    Nothing watched this, and it is the failure that hid the longest. The
    Anthropic balance ran dry on 5 Sep 2026 and every turn since has failed and
    silently fallen back to openai/gpt-5.3-codex through OpenRouter. Users kept
    getting answers, the gates stayed green, the link stayed connected, and by
    15 Sep that was 1,070 failed calls over ten days that nobody had seen.

    A working fallback is exactly what makes this invisible, so the check reads
    the failure rather than the outcome. Only dead ends count. A timeout or a
    dropped connection is the fallback doing its job and is not worth waking
    anybody for.
    """
    if not AGENT_LOG.exists():
        return True, "no agent log yet"

    cutoff = datetime.now() - timedelta(hours=MODEL_WINDOW_HOURS)
    hits = 0
    reason = ""
    first_seen = ""
    last_hit: datetime | None = None
    try:
        with AGENT_LOG.open(errors="replace") as handle:
            for line in handle:
                found = next((why for mark, why in MODEL_DEAD_ENDS if mark in line), "")
                if not found:
                    continue
                stamp = LOG_STAMP.match(line)
                if not stamp:
                    continue
                when = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S")
                if not first_seen:
                    first_seen = stamp.group(1)
                if when >= cutoff:
                    hits += 1
                    reason = found
                    if last_hit is None or when > last_hit:
                        last_hit = when
    except OSError as exc:
        return True, f"cannot read agent.log: {exc}"

    if not hits:
        return True, "primary model answering"

    # Has it since come back? The window is 24 hours wide, so without this an
    # outage that ended at lunchtime keeps raising the same alarm until the
    # following lunchtime. That is how an alarm stops being read: on 17 Sep the
    # balance had been topped up, the primary had answered every call for
    # seventeen hours, and this still said FAILING because errors from the
    # previous evening were inside the window.
    #
    # The test is not "how long ago" but "which happened last": a success on the
    # primary model *after* the newest dead end means the bill is paid.
    recovered_at = primary_model_recovered_since(last_hit)
    if recovered_at:
        return True, (
            f"primary model answering (recovered {recovered_at:%H:%M}; "
            f"{hits} failed calls earlier in the window)"
        )

    # first_seen is a floor, not the truth: the log rotates, so the real start
    # may be older than anything still on disk.
    return False, (
        f"{reason}, {hits} failed calls in the last {MODEL_WINDOW_HOURS}h "
        f"(seen from at least {first_seen})"
    )


STATE_DB = HERMES / "state.db"
DROPPED_WINDOW_DAYS = 7


def check_dropped() -> tuple[bool, str]:
    """Anyone still waiting on a reply that was written and never sent.

    Patch 12 decided, correctly, that a reply which missed its moment should be
    dropped rather than delivered hours late. What it did not add was anybody
    noticing. The row goes to 'abandoned' and sits there, and the person is
    simply never answered.

    On 11 Sep 2026 GT sent "All" and the reply died with the link. On 15 Sep at
    00:29 Ankiita sent a photo and asked why the responses were late; the agent
    hung for thirty minutes and the apology it finally wrote could not be sent
    either. Neither of them heard anything again. GT went four days, and both
    kept receiving scheduled nudges the whole time, which reads as being
    ignored rather than being failed.

    A later successful message to the same person closes it: Shreya was dropped
    on 14 Sep at 14:22 and answered that evening, so she is not owed anything.
    """
    if not STATE_DB.exists():
        return True, "no delivery ledger yet"

    cutoff = time.time() - DROPPED_WINDOW_DAYS * 24 * 60 * 60
    try:
        database = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return True, f"cannot open the delivery ledger: {exc}"
    try:
        rows = database.execute(
            """
            SELECT a.chat_id, MIN(a.created_at)
            FROM delivery_obligations a
            WHERE a.state IN ('abandoned', 'failed')
              AND a.created_at > ?
              AND NOT EXISTS (
                  SELECT 1 FROM delivery_obligations d
                  WHERE d.chat_id = a.chat_id
                    AND d.state = 'delivered'
                    AND d.created_at > a.created_at
              )
            GROUP BY a.chat_id
            """,
            (cutoff,),
        ).fetchall()
    except sqlite3.Error as exc:
        return True, f"cannot read the delivery ledger: {exc}"
    finally:
        database.close()

    rows = [
        (chat, when)
        for chat, when in rows
        if when and not _reached_by_cron_since(str(chat), float(when))
    ]
    if not rows:
        return True, "nobody is waiting"

    oldest = min(when for _, when in rows if when)
    hours = (time.time() - oldest) / 3600
    waited = f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.0f} days"
    people = "person" if len(rows) == 1 else "people"
    return False, f"{len(rows)} {people} never got a reply, longest waiting {waited}"


RUNAWAY_STATE = HERMES / "state" / "ted-runaway-conversations.json"
RUNAWAY_WINDOW_SECONDS = 6 * 60 * 60


def check_runaway() -> tuple[bool, str]:
    """Whether Ted has hit the conversation cap and gone quiet on somebody.

    The cap in `ted_safety_gates` drops inbound turns once a single chat passes
    sixty in an hour. It exists because of 7 Sep 2026, when one thread ran 330
    turns and 44.2M input tokens with Ted answering what reads like his own
    voice. Nothing bounded a conversation then, and the per-turn call budget
    never noticed, because every one of those turns was individually small.

    The cap is worth having and it is also the kind of thing that must never be
    silent. Whoever is on the other end is being ignored, and if they are a
    real person that is a bug with a person attached to it. It cannot be said
    over WhatsApp: the cap works by not answering WhatsApp.
    """
    if not RUNAWAY_STATE.exists():
        return True, "no conversation has hit the cap"
    try:
        payload = json.loads(RUNAWAY_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return True, f"cannot read the runaway record: {exc}"
    chats = payload.get("chats")
    if not isinstance(chats, dict):
        return True, "no conversation has hit the cap"

    cutoff = time.time() - RUNAWAY_WINDOW_SECONDS
    recent = [
        record
        for record in chats.values()
        if isinstance(record, dict) and float(record.get("lastAt") or 0) > cutoff
    ]
    if not recent:
        return True, "no conversation has hit the cap"

    dropped = sum(int(record.get("dropped") or 0) for record in recent)
    busiest = max(int(record.get("turnsInWindow") or 0) for record in recent)
    threads = "thread" if len(recent) == 1 else "threads"
    return (
        False,
        f"{len(recent)} {threads} hit the conversation cap, {dropped} messages "
        f"dropped, busiest ran {busiest} turns in an hour",
    )


def _reached_by_cron_since(chat_id: str, since: float) -> bool:
    """Whether a scheduled job delivered to this chat after `since`.

    The ledger only knows about replies the agent sends through the normal
    path. A cron job hands its text straight to the live adapter and writes no
    obligation row at all, so answering somebody that way left them looking
    unanswered forever. GT was reached at 18:40 on 15 Sep 2026 by exactly that
    route and this check went on reporting him as four days unanswered.

    Read from agent.log rather than the job file, because a job's last_status
    says the run succeeded and not whether it actually said anything: a run
    that the reminder gate silences returns SILENT and delivers nothing.

    The log rotates, so a delivery older than the current file cannot be seen.
    That only ever fails towards reporting somebody who has in fact been
    answered, which is the safe direction for this to be wrong in.
    """
    if not chat_id or not AGENT_LOG.exists():
        return False
    marker = f"delivered to whatsapp:{chat_id} via live adapter"
    try:
        with AGENT_LOG.open(errors="replace") as handle:
            for line in handle:
                if marker not in line:
                    continue
                stamp = LOG_STAMP.match(line)
                if stamp and datetime.strptime(
                    stamp.group(1), "%Y-%m-%d %H:%M:%S"
                ).timestamp() > since:
                    return True
    except OSError:
        return False
    return False

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_KEYS = ("PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN")

EMAIL_KEYS = ("TED_ALERT_EMAIL_TO", "TED_ALERT_SMTP_USER", "TED_ALERT_SMTP_PASSWORD")
EMAIL_DEFAULT_HOST = "smtp.gmail.com"
EMAIL_DEFAULT_PORT = 465
EMAIL_ATTEMPTS = 3
EMAIL_RETRY_SECONDS = 5


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
    # One timeout used to lose the alert outright. At 11:52 on 15 Sep 2026 the
    # watcher correctly caught the WhatsApp link going down, tried to mail it,
    # got "Connection unexpectedly closed: The read operation timed out", and
    # that was the end of it. The same credentials worked by hand an hour
    # later, so the alert was lost to a blip and not to a misconfiguration.
    # A refused login is different and is never retried: it will be refused
    # again, and three attempts at a wrong password only delays the report.
    last = ""
    for attempt in range(EMAIL_ATTEMPTS):
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                config["host"], config["port"], context=context, timeout=20
            ) as server:
                server.login(config["user"], config["password"])
                server.send_message(message)
            return "sent"
        except smtplib.SMTPAuthenticationError:
            return "refused the login (app password wrong, or 2-Step not on)"
        except Exception as exc:  # noqa: BLE001 - an alert channel may never crash the watcher
            last = f"failed ({exc})"
            if attempt + 1 < EMAIL_ATTEMPTS:
                time.sleep(EMAIL_RETRY_SECONDS)
    return last


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


def notify(title: str, body: str, dry_run: bool, urgent: bool = True) -> bool:
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
        return True
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
    # Whether anything reached her away from this screen. The desk notification
    # does not count: on 8 Sep 2026 it popped up to an empty room for seventeen
    # hours. The caller uses this to decide whether the alert may be written
    # down as delivered.
    reached = False
    for name, result in remote_alerts(title, body, urgent, dry_run=False):
        if result == "sent":
            reached = True
        else:
            print(f"{name} alert: {result}", file=sys.stderr)
    return reached


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
    model_ok, model_detail = check_model()
    dropped_ok, dropped_detail = check_dropped()
    runaway_ok, runaway_detail = check_runaway()

    state = read_state()
    now = time.time()
    stamp = time.strftime("%H:%M")

    # Each component carries its own transition and its own repeat clock, so a
    # gate that flaps cannot swallow the alert for a link that died.
    components = [
        ("gates", gates_ok, "Ted's safety gates"),
        ("link", link_ok, "Ted's WhatsApp"),
        ("model", model_ok, "Ted's model"),
        ("dropped", dropped_ok, "Someone Ted never answered"),
        ("runaway", runaway_ok, "A conversation Ted stopped answering"),
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
        elif key == "model":
            title = f"⚠️ {label} has been failing over"
            body = (
                f"{model_detail}.\n\n"
                "Ted is still replying, on the fallback model, so nothing looks "
                "broken from the outside. Top up the primary provider."
            )
        elif key == "runaway":
            title = f"⚠️ {label}"
            body = (
                f"{runaway_detail}.\n\n"
                "The cap did its job, so this cost nothing. If the other end "
                "is a real person they are being ignored right now. On the "
                "laptop: grep ted_runaway_conversation ~/.hermes/logs/agent.log"
            )
        elif key == "dropped":
            title = f"⚠️ {label}"
            body = (
                f"{dropped_detail}.\n\n"
                "Their reply was written and dropped for being stale, which is "
                "deliberate. Writing them something fresh is not. On the "
                "laptop: npm run reports"
            )
        else:
            title = f"⚠️ {label} is down"
            body = f"{link_detail} at {stamp}. Ted cannot send or receive."

        detail = {
            "link": link_detail,
            "model": model_detail,
            "dropped": dropped_detail,
        }.get(key, stamp)
        print(f"{key}: {'ok' if ok else 'FAILING'} ({detail})")
        if not ok and key == "gates":
            print(failing_lines(output))

        # Nothing is announced on the very first healthy run: a watcher that
        # says hello the moment it is installed trains you to ignore it.
        if should_alert and not (ok and was is None):
            # Only a delivered alert resets the repeat clock. Stamping it
            # regardless meant a single failed send bought four hours of
            # silence about a thing that was still broken, which is the exact
            # shape of the failure this whole file exists to prevent. If
            # nothing got through, the next run in fifteen minutes tries again.
            reached = notify(title, body, args.dry_run)
            if not args.dry_run and reached:
                state[f"{key}_last_alert_at"] = now
        state[key] = ok

    state["last_checked_at"] = now
    if not args.dry_run:
        write_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
