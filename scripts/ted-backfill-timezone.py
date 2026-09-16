#!/usr/bin/env python3
"""
Give a check-in time a timezone, so Ted knows whose 9pm it is.

    python3 scripts/ted-backfill-timezone.py
    python3 scripts/ted-backfill-timezone.py --apply

WHY. 18 of the 24 people who have a daily check-in time have no `timeZone` on
their user row. Ted knows they want 21:00 and does not know 21:00 where. The
cause is upstream: the check-in question is written fresh by the model every
time — 49 asks in about 45 different wordings on 16 Sep 2026 — and most of
those wordings ask only for a time. `REVIEW_TIME_QUESTION` exists as a fixed
line and is almost never what goes out, and it does not ask for a city either.

WHERE THE ANSWER COMES FROM. `sessions` holds only WhatsApp `@lid` privacy
identifiers, never a phone number. `delivery_obligations` holds both, so a chat
that has ever had a message queued can be joined back to its number. Every
number that appears is +91, and India is a single timezone, so the country code
resolves to Asia/Kolkata without ambiguity — unlike +1 or +7, which would not.

THE RULE THAT MATTERS. This never overwrites a timezone that is already set.
Pradosh has an Indian number and lives in London, and his row correctly says
Europe/London. A backfill that trusted the country code over a stored value
would have moved his whole day by four and a half hours, and he is the one user
whose schedule is already a known open finding. A number says where the SIM was
bought, not where the person is standing, so it is only ever consulted for
somebody who has told us nothing.

Nine users can be resolved this way. The other nine have no number recorded
anywhere and can only be asked, which is a message to a real person and so not
this script's job.

Confirmed by Vandy on 16 Sep 2026: all nine are in India.

Dry run by default.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES_ENV = Path.home() / ".hermes" / ".env"
STATE_DB = Path.home() / ".hermes" / "state.db"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")
DEPLOYMENT = "hardy-scorpion-901"

# Country code -> timezone. Only codes whose country has exactly one timezone
# belong here. Adding +1 or +7 would be a bug: the code would not identify a
# zone, and this file would start inventing one.
SINGLE_ZONE_COUNTRIES = {"91": "Asia/Kolkata"}


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


def convex_rows(table: str) -> list[dict]:
    result = subprocess.run(
        ["npx", "convex", "data", table, "--deployment", DEPLOYMENT,
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if result.returncode != 0:
        print(f"could not read {table} from {DEPLOYMENT}:\n{result.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def user_key(lid: str) -> str:
    """The same hash `_user_state_key` builds in the gate, so the gateway's
    `@lid` can be matched to `users.whatsappUserId` in Convex."""
    return f"whatsapp:sha256:{sha256(f'whatsapp:{lid}'.encode()).hexdigest()}"


def numbers_by_user_key() -> dict[str, str]:
    """Every WhatsApp identity we hold a phone number for, keyed the way Convex
    keys it. Read-only, and only from rows the gateway wrote itself."""
    if not STATE_DB.exists():
        return {}
    found: dict[str, str] = {}
    connection = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select distinct chat_id, session_key from delivery_obligations"
        ).fetchall()
    finally:
        connection.close()
    for chat_id, session_key in rows:
        match = re.search(r"dm:(\d+)", session_key or "")
        if chat_id and match:
            found[user_key(chat_id)] = match.group(1)
    return found


def zone_for(number: str) -> str | None:
    for code, zone in SINGLE_ZONE_COUNTRIES.items():
        if number.startswith(code):
            return zone
    return None


def mask(number: str) -> str:
    return number[:4] + "*" * max(len(number) - 6, 0) + number[-2:]


def write_timezone(env: dict[str, str], whatsapp_user_id: str, current_field: str, zone: str) -> str:
    """Set one timezone through the same authenticated endpoint the gateway
    uses. `currentField` is passed back unchanged: `saveOnboarding` requires it
    and would otherwise move somebody's place in the flow as a side effect of a
    repair that is supposed to touch one column."""
    payload = json.dumps({
        "action": "onboarding",
        "whatsappUserId": whatsapp_user_id,
        "currentField": current_field,
        "profile": {"timeZone": zone},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{env['TED_CONVEX_SITE_URL'].rstrip('/')}/ted-memory",
        data=payload,
        headers={
            "authorization": f"Bearer {env['TED_HERMES_SHARED_SECRET']}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001
            pass
        return f"refused: {detail or error}"
    except (OSError, ValueError) as error:
        return f"failed: {error}"
    return "ok" if body.get("success") else f"refused: {body.get('error')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write the timezones")
    args = parser.parse_args()

    env = load_env()
    missing_env = [name for name in REQUIRED_ENV if not env.get(name)]
    if args.apply and missing_env:
        print(f"cannot write without {', '.join(missing_env)}", file=sys.stderr)
        return 1

    users = {row["_id"]: row for row in convex_rows("users")}
    reminders = {row["userId"]: row for row in convex_rows("reminders")}
    onboarding = {row["userId"]: row for row in convex_rows("onboarding")}
    numbers = numbers_by_user_key()

    planned: list[tuple[dict, str, str]] = []
    unresolved: list[dict] = []
    protected: list[dict] = []

    for user_id, reminder in reminders.items():
        if not reminder.get("dailyReviewTime"):
            continue
        user = users.get(user_id)
        if not user:
            continue
        if user.get("timeZone"):
            protected.append(user)
            continue
        number = numbers.get(user["whatsappUserId"])
        zone = zone_for(number) if number else None
        if zone:
            planned.append((user, number, zone))
        else:
            unresolved.append(user)

    name = lambda user: user.get("name") or "(no name)"  # noqa: E731

    print(f"{len(protected)} already have a timezone and are not touched: "
          f"{', '.join(sorted(name(u) for u in protected))}\n")

    if planned:
        print(f"{len(planned)} can be resolved from the phone country code:\n")
        print(f"  {'name':<18}{'number':<15}{'check-in':<10}timezone")
        print("  " + "-" * 56)
        for user, number, zone in planned:
            check_in = reminders[user["_id"]]["dailyReviewTime"]
            print(f"  {name(user):<18}{mask(number):<15}{check_in:<10}{zone}")

    if unresolved:
        print(f"\n{len(unresolved)} have a check-in time and no number on record, "
              f"so they can only be asked:")
        print(f"  {', '.join(sorted(name(u) for u in unresolved))}")

    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply.")
        return 0

    print()
    failures = 0
    for user, _number, zone in planned:
        row = onboarding.get(user["_id"])
        # No onboarding row means no `currentField` to hand back, and inventing
        # one would move somebody's place in the flow. Those are left alone.
        if not row:
            print(f"  {name(user):<18}skipped, no onboarding row to preserve")
            failures += 1
            continue
        outcome = write_timezone(env, user["whatsappUserId"], row["currentField"], zone)
        print(f"  {name(user):<18}{zone:<16}{outcome}")
        failures += outcome != "ok"

    print(f"\n{len(planned) - failures} of {len(planned)} written.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
