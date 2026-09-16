#!/usr/bin/env python3
"""
Give back the reminders Ted was cleared to send and WhatsApp never delivered.

    python3 scripts/ted-release-undelivered-reminders.py
    python3 scripts/ted-release-undelivered-reminders.py --apply

`gateReminderDelivery` spends two things the moment it says yes: one of the
day's reminders, and one step towards "want me to pause the nudges?". Both are
spent before WhatsApp has been asked for anything, which is deliberate — a
commit that waits for proof of delivery leaves the cap unfilled when the proof
never comes, and an uncapped reminder loop nags people. The cost of committing
early is that a send which never happens is still charged to the user.

The gateway's plugin pays back the one case it can see for itself: a scheduled
ping it drops after asking. This pays back the other one. WhatsApp took the
message, never delivered it, and wrote that down in `~/.hermes/state.db` as
`delivery_obligations.state = 'failed'` or `'abandoned'`, minutes or hours
after the gate had already moved on.

WHY THIS IS A MATCH AND NOT A LOOKUP

The two stores cannot see each other. The ledger records a chat, a time and an
outcome, and **does not record what kind of message it was**: every row's
`session_key` is `agent:main:whatsapp:dm:<number>`, whether it carried a 9pm
nudge or an apology for a model timeout. Convex knows which sends were
reminders but nothing about whether they arrived. So the join is:

    the chat        -> sha256("whatsapp:" + chat_id), the gate's own
                       `_user_state_key`, imported rather than reimplemented
    the moment      -> the ledger row's `created_at` against the pending
                       delivery's `at`, inside MATCH_WINDOW_SECONDS

CONSERVATIVE ON PURPOSE, IN BOTH DIRECTIONS

A release that should not happen hands somebody an extra nudge and rewinds a
break offer they had earned. A release that does not happen costs one nudge.
The second is the cheaper mistake, so every ambiguity resolves that way:

  * Only an explicit `failed` or `abandoned` row releases anything. A missing
    row is **not** treated as a failure. The ledger holds 223 delivered rows
    against 704 assistant messages, so most sends never appear in it at all
    and "no row" means nothing either way.
  * A `delivered` row inside the same window wins over a failed one. A retry
    that eventually landed is a delivery.
  * `--since-days` bounds how far back it will look, because a pending record
    is only overwritten by the user's *next* reminder. Somebody who has had no
    reminders since July still has a pending row from July, and that is not a
    failure, it is quiet.

Nothing here decides anything twice. The release is keyed by the delivery id
Convex issued, so a second run over the same ledger is a no-op, and a release
cannot reach back past a send that has since gone out fine.

Dry run by default. Prints one line per user and writes nothing until --apply.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hermes import ted_safety_gates as gates  # noqa: E402

STATE_DB = Path.home() / ".hermes" / "state.db"
HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")

# How far either side of the grant a ledger row may sit and still be the same
# message. A cron reminder reaches the send path within seconds of the gate
# clearing it; the width here is for a slow model turn between the two, not for
# a guess. Wider would start swallowing unrelated failures in the same chat.
MATCH_WINDOW_SECONDS = 300

FAILED_STATES = ("failed", "abandoned")


def load_env() -> dict[str, str]:
    """The same two variables the gate reads, from the same file it reads."""
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


def convex(action: str, whatsapp_user_id: str, **body) -> dict:
    env = load_env()
    missing = [n for n in REQUIRED_ENV if not env.get(n)]
    if missing:
        raise SystemExit(f"{' and '.join(missing)} is not set")
    request = urllib.request.Request(
        env["TED_CONVEX_SITE_URL"].rstrip("/") + "/ted-memory",
        data=json.dumps(
            {"action": action, "whatsappUserId": whatsapp_user_id, **body}
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {env['TED_HERMES_SHARED_SECRET']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {
            "success": False,
            "error": f"HTTP {error.code}: "
            f"{error.read().decode('utf-8', errors='replace')[:200]}",
        }
    except urllib.error.URLError as error:
        return {"success": False, "error": f"could not reach Convex: {error.reason}"}


def ledger_rows(since_epoch: float) -> list[tuple[str, str, float]]:
    """Every outbound message the gateway wrote down, newest first.

    Read-only, and read whole rather than queried per user: the join needs a
    hash of each chat id, which SQLite cannot compute, and a few hundred rows
    is nothing. Opening read-only matters — this runs against the live
    gateway's own database while it is serving.
    """
    if not STATE_DB.exists():
        raise SystemExit(f"no delivery ledger at {STATE_DB}")
    database = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        return [
            (str(chat_id), str(state), float(created_at))
            for chat_id, state, created_at in database.execute(
                "SELECT chat_id, state, created_at FROM delivery_obligations "
                "WHERE created_at >= ? ORDER BY created_at DESC",
                (since_epoch,),
            )
        ]
    except sqlite3.Error as error:
        raise SystemExit(f"cannot read the delivery ledger: {error}")
    finally:
        database.close()


def verdict_for(
    pending_at_epoch: float, rows: list[tuple[str, str, float]]
) -> tuple[str, float | None]:
    """Did the send cleared at this moment arrive, fail, or leave no trace?

    `rows` is one chat's ledger. A delivered row in the window beats a failed
    one: a retry that eventually landed is a delivery, and the user got their
    reminder.
    """
    near = [
        (state, at)
        for _, state, at in rows
        if abs(at - pending_at_epoch) <= MATCH_WINDOW_SECONDS
    ]
    if any(state == "delivered" for state, _ in near):
        return "delivered", None
    for state, at in sorted(near, key=lambda row: row[1]):
        if state in FAILED_STATES:
            return state, at
    return "no record", None


def when(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the releases. Without it nothing is sent to Convex.",
    )
    parser.add_argument(
        "--since-days",
        type=float,
        default=7.0,
        help="how far back a pending record may be and still be worth judging "
        "(default 7). A pending record is only cleared by the user's next "
        "reminder, so an old one usually means quiet, not failure.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - args.since_days * 86400

    audit = convex("pendingReminders", "builder-readback")
    if not audit.get("success"):
        print(f"could not read Convex: {audit.get('error')}", file=sys.stderr)
        return 1
    pending = audit.get("pending", [])
    if not pending:
        print("nothing outstanding. No reminder is waiting to be accounted for.")
        return 0

    rows = ledger_rows(cutoff)
    by_chat: dict[str, list[tuple[str, str, float]]] = {}
    for chat_id, state, at in rows:
        by_chat.setdefault(gates._user_state_key("whatsapp", chat_id, ""), []).append(
            (chat_id, state, at)
        )

    releases: list[dict] = []
    print(f"{len(pending)} cleared send(s) outstanding, ledger from {when(cutoff)}\n")
    for record in sorted(pending, key=lambda r: r.get("at", 0)):
        key = str(record.get("whatsappUserId") or "")
        at_epoch = float(record.get("at", 0)) / 1000.0
        short = key.split(":")[-1][:12]
        if at_epoch < cutoff:
            print(f"  {short}  {when(at_epoch)}  older than the window, left alone")
            continue
        state, failed_at = verdict_for(at_epoch, by_chat.get(key, []))
        if state in FAILED_STATES:
            print(
                f"  {short}  {when(at_epoch)}  {state} at "
                f"{when(failed_at) if failed_at else '?'}  ->  RELEASE"
            )
            releases.append(record)
        else:
            print(f"  {short}  {when(at_epoch)}  {state}, left alone")

    if not releases:
        print("\nNothing to give back.")
        return 0

    if not args.apply:
        print(f"\n{len(releases)} to release. Dry run, nothing written. Re-run with --apply.")
        return 0

    print()
    for record in releases:
        key = str(record.get("whatsappUserId") or "")
        result = convex(
            "reminderMissed",
            key,
            deliveryId=str(record.get("id") or ""),
            today=str(record.get("day") or ""),
            reason="undelivered",
        )
        short = key.split(":")[-1][:12]
        if not result.get("success"):
            print(f"  {short}: FAILED {result.get('error')}", file=sys.stderr)
        elif result.get("released"):
            print(
                f"  {short}: released. sentToday now {result.get('sentToday')}, "
                f"unanswered nudges {result.get('unansweredNudges')}"
            )
        else:
            # Already released, or a newer send has replaced this one. Both are
            # ordinary on a second run and neither is a problem.
            print(f"  {short}: nothing to release ({result.get('reason')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
