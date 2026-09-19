#!/usr/bin/env python3
"""
Bring every existing user onto the one definition of "set up".

    npm run setup:audit        # what Convex thinks, and what it is missing
    npm run setup:reconcile    # the same, plus exactly what would be written
    npm run setup:reconcile -- --apply

Onboarding changed shape several times during build week: five counted
questions, then six, then stretches of open conversation. Which flow someone
arrived through decided which store ended up holding their answers, so on
6 Sep 2026 the same fact could live in three places that never reconciled:

  * Convex `users`/`targets`/`reminders`, written by the model
  * the gate's own file, ~/.hermes/state/ted-safety-gates-onboarding.json
  * the Hermes cron jobs, which know a check-in time nothing else recorded

`setupStateFor` in convex/model.ts is now the single definition. This script is
the one-time consequence of that: it copies what the gateway already proved,
into Convex, and then asks Convex to recompute. It invents nothing.

WHAT IT WILL NEVER DO. It only ever copies a value that already exists in one
of the local records. It does not estimate a weight, guess a goal, or derive a
calorie number from anything. Where the evidence is absent the gap stays open
and is reported as a question a human still has to ask. It does not create
users, delete anything, send any message, or create or change a cron job, so
running it cannot make Ted speak to anybody.

DRY RUN BY DEFAULT. Without --apply it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ted_deletion_guard

IST = timezone(timedelta(hours=5, minutes=30))
HERMES = Path.home() / ".hermes"
HERMES_ENV = HERMES / ".env"
GATE_STATE = HERMES / "state" / "ted-safety-gates-onboarding.json"
DISCLOSURES = HERMES / "state" / "ted-safety-gates-disclosures.json"
CRON_JOBS = HERMES / "cron" / "jobs.json"
STATE_DB = HERMES / "state.db"

REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")

# The privacy notice, as the gate composes it. Matched loosely on purpose: the
# greeting in front of it is per-user, and the sentence after it has been
# reworded at least once.
NOTICE_MARKER = "stores your profile"

# Convex goal literals. The gate happens to store the same spellings, but that
# is checked rather than assumed — a value that is not one of these is dropped
# rather than guessed at.
GOALS = {"maintainWeight", "loseWeight", "gainWeight", "improveConsistency"}


# ---------------------------------------------------------------------------
# Reaching Convex, the same way the gate and the reports script do
# ---------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    found = {name: os.environ.get(name, "") for name in REQUIRED_ENV}
    if all(found.values()) or not HERMES_ENV.exists():
        return found
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in REQUIRED_ENV and not found.get(key):
            found[key] = value.strip().strip('"').strip("'")
    return found


def convex(action: str, whatsapp_user_id: str, **body) -> dict:
    env = load_env()
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise SystemExit(
            f"{' and '.join(missing)} is not set in the environment or {HERMES_ENV}"
        )
    payload = {"action": action, "whatsappUserId": whatsapp_user_id, **body}
    request = urllib.request.Request(
        env["TED_CONVEX_SITE_URL"].rstrip("/") + "/ted-memory",
        data=json.dumps(payload).encode("utf-8"),
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
        detail = error.read().decode("utf-8", errors="replace")[:300]
        return {"success": False, "error": f"HTTP {error.code}: {detail}"}
    except urllib.error.URLError as error:
        return {"success": False, "error": f"could not reach Convex: {error.reason}"}


# ---------------------------------------------------------------------------
# The local records, read only
# ---------------------------------------------------------------------------


def user_key(sender_id: str) -> str:
    """The same hash the gate computes in `_user_state_key`."""
    digest = hashlib.sha256(f"whatsapp:{sender_id}".encode("utf-8")).hexdigest()
    return f"whatsapp:sha256:{digest}"


def read_gate_state() -> dict[str, dict]:
    if not GATE_STATE.exists():
        return {}
    users = json.loads(GATE_STATE.read_text(encoding="utf-8")).get("users", {})
    # A tombstone is not a user with missing fields. See ted_deletion_guard.
    # Reported in the human section below, never here: this function is also
    # on the --json path the sweep reads.
    return ted_deletion_guard.living(users)


def forgotten_note() -> str:
    """The skip line, for the human output only."""
    if not GATE_STATE.exists():
        return ""
    raw = json.loads(GATE_STATE.read_text(encoding="utf-8")).get("users", {})
    return ted_deletion_guard.note(raw)


def read_disclosed() -> set[str]:
    if not DISCLOSURES.exists():
        return set()
    return set(json.loads(DISCLOSURES.read_text(encoding="utf-8")).get("user_keys", []))


def read_cron_check_in_times() -> dict[str, str]:
    """user key -> HH:MM, from each daily_review job's own cron expression.

    The scheduler is the only record of a check-in time for people who named
    one before the reminders row existed. `0 21 * * *` is 21:00; anything that
    is not a fixed minute and hour is skipped rather than approximated.
    """
    if not CRON_JOBS.exists():
        return {}

    def walk(node):
        if isinstance(node, dict):
            if "schedule" in node and "prompt" in node:
                yield node
                return
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    times: dict[str, str] = {}
    for job in walk(json.loads(CRON_JOBS.read_text(encoding="utf-8"))):
        if "daily_review" not in str(job.get("name") or ""):
            continue
        deliver = str(job.get("deliver") or "")
        jid = deliver.split(":", 1)[1] if deliver.startswith("whatsapp:") else ""
        if not jid:
            jid = str((job.get("origin") or {}).get("chat_id") or "")
        if not jid:
            continue
        expression = str((job.get("schedule") or {}).get("expr") or "")
        match = re.match(r"^\s*(\d{1,2})\s+(\d{1,2})\s", expression)
        if not match:
            continue
        minute, hour = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        times[user_key(jid)] = f"{hour:02d}:{minute:02d}"
    return times


def read_notice_times() -> dict[str, int]:
    """user key -> epoch ms the privacy notice was actually delivered.

    From delivery_obligations, which is what left the gateway, rather than the
    messages table, which is what the model wrote. The notice is added at
    delivery, so it appears in one and not the other.
    """
    if not STATE_DB.exists():
        return {}
    times: dict[str, int] = {}
    database = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = database.execute(
            "SELECT chat_id, MIN(created_at) FROM delivery_obligations "
            "WHERE content LIKE ? GROUP BY chat_id",
            (f"%{NOTICE_MARKER}%",),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        database.close()
    for chat_id, created_at in rows:
        if chat_id and created_at:
            times[user_key(str(chat_id))] = int(float(created_at) * 1000)
    return times


# ---------------------------------------------------------------------------
# What we can prove, per user
# ---------------------------------------------------------------------------

PROFILE_FROM_GATE = {
    "name": ("name", str),
    "age": ("age", int),
    "heightCm": ("height_cm", float),
    "weightKg": ("weight_kg", float),
}

# Not one of the eight requirements, so it never shows as a gap, but Convex
# needs it for `calorieFloorFor`: without it the floor has to assume the lower
# female term and is 166 kcal too permissive. Backfilled from the gate's own
# answer to question 4 of 6 wherever there is one.
SEX_VALUES = {"male", "female"}


def evidence_for(
    row: dict,
    gate: dict,
    disclosed: set[str],
    cron_times: dict[str, str],
    notice_times: dict[str, int],
) -> tuple[dict, dict, dict, list[str]]:
    """Return (profile, target, reminder, unprovable) for one Convex user.

    `unprovable` is the honest half: gaps no local record can close, which are
    the ones that still need a person to ask a question.
    """
    key = row["whatsappUserId"]
    missing = set(row.get("missing") or [])
    record = gate.get(key, {})
    profile: dict = {}
    target: dict = {}
    reminder: dict = {}
    unprovable: list[str] = []

    if "privacyNotice" in missing:
        if key in notice_times:
            profile["privacyNoticeSentAt"] = notice_times[key]
        elif key in disclosed:
            # The gate recorded sending it but kept no time, and the delivery
            # log only reaches back to 2 Sep. The notice goes out on the first
            # turn, so the user's own createdAt is the tightest defensible
            # bound rather than an invented moment. Counted separately in the
            # summary so the approximation is never silent.
            profile["privacyNoticeSentAt"] = int(row["createdAt"])
        else:
            unprovable.append("privacyNotice")

    for field, (source, cast) in PROFILE_FROM_GATE.items():
        want = {"name": "name", "age": "age", "heightCm": "height", "weightKg": "weight"}[field]
        if want not in missing:
            continue
        value = record.get(source)
        if value is None or (isinstance(value, str) and not value.strip()):
            unprovable.append(want)
            continue
        try:
            profile[field] = cast(value)
        except (TypeError, ValueError):
            unprovable.append(want)

    # Planned only when the two stores actually disagree. `sex` is not one of
    # `setupStateFor`'s requirements, so it never lands in `missing` and this
    # block cannot key off that like the others do. Without the comparison it
    # re-planned the same write forever: the 17 Sep run wrote 30 and the next
    # dry run still offered 29, which makes "can be closed from local evidence"
    # a number nobody can act on.
    stored_sex = record.get("sex")
    if stored_sex in SEX_VALUES and row.get("sex") != stored_sex:
        profile["sex"] = stored_sex

    if "goal" in missing:
        goal = record.get("goal")
        if isinstance(goal, str) and goal in GOALS:
            profile["goal"] = goal
        else:
            unprovable.append("goal")

    if "calorieTarget" in missing:
        # tracking_kcal is the number meals are counted against, which is the
        # one a target means. maintenance_kcal is the resting figure and is
        # only used when no target was ever agreed.
        calories = record.get("tracking_kcal") or record.get("maintenance_kcal")
        if isinstance(calories, (int, float)) and calories > 0:
            target["calories"] = int(calories)
            target["nutritionSource"] = (
                "userProvided" if record.get("tracking_kcal") else "maintenanceEstimate"
            )
        else:
            unprovable.append("calorieTarget")

    if "checkInTime" in missing:
        time_value = record.get("review_time") or cron_times.get(key)
        if isinstance(time_value, str) and re.fullmatch(r"\d{2}:\d{2}", time_value):
            reminder["dailyReviewTime"] = time_value
        else:
            unprovable.append("checkInTime")

    return profile, target, reminder, unprovable


# ---------------------------------------------------------------------------


def mask(key: str) -> str:
    """Hashed keys are already unreadable; this only shortens them for a table."""
    return key.split(":")[-1][:8] if ":" in key else key[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the plan to Convex. Without this nothing is written.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    arguments = parser.parse_args()

    audit = convex("setupAudit", "builder-readback")
    if not audit.get("success"):
        print(f"could not read the audit: {audit.get('error')}", file=sys.stderr)
        return 1
    rows = audit.get("users", [])

    gate = read_gate_state()
    disclosed = read_disclosed()
    cron_times = read_cron_check_in_times()
    notice_times = read_notice_times()

    plans = []
    for row in rows:
        profile, target, reminder, unprovable = evidence_for(
            row, gate, disclosed, cron_times, notice_times
        )
        plans.append(
            {
                "key": row["whatsappUserId"],
                "name": row.get("name") or "(no name)",
                "currentField": row.get("currentField"),
                "storedStatus": row["storedStatus"],
                "derivedStatus": row["derivedStatus"],
                "disagrees": row["disagrees"],
                "missing": row.get("missing") or [],
                "blocked": row.get("blocked"),
                "profile": profile,
                "target": target,
                "reminder": reminder,
                "unprovable": unprovable,
            }
        )

    if arguments.json:
        print(json.dumps({"plans": plans, "apply": arguments.apply}, indent=2))
        return 0

    mode = "APPLY — writing to Convex" if arguments.apply else "DRY RUN — nothing is written"
    print("=" * 96)
    print(f"TED SETUP RECONCILE   {datetime.now(IST):%d %b %Y %H:%M IST}   {mode}")
    print("=" * 96)
    print(f"users in Convex: {len(rows)}")
    skipped = forgotten_note()
    if skipped:
        print(skipped.strip())
    print()

    already = [p for p in plans if not p["missing"] and not p["blocked"]]
    fixable = [p for p in plans if (p["profile"] or p["target"] or p["reminder"])]
    stuck = [p for p in plans if p["unprovable"]]

    print(f"{'user':<10}{'name':<13}{'stored':<12}{'derived':<11}  what this would write")
    print("-" * 96)
    for plan in sorted(plans, key=lambda p: (len(p["missing"]), p["name"])):
        writes = []
        if plan["profile"]:
            writes.append("profile: " + ", ".join(sorted(plan["profile"])))
        if plan["target"]:
            writes.append(f"target: {plan['target'].get('calories')} kcal")
        if plan["reminder"]:
            writes.append(f"check-in: {plan['reminder'].get('dailyReviewTime')}")
        if not writes:
            writes.append(
                "status only" if plan["disagrees"] else "nothing, already correct"
            )
        note = ""
        if plan["unprovable"]:
            note = "   still needs asking: " + ", ".join(plan["unprovable"])
        if plan["blocked"]:
            note += f"   BLOCKED: {plan['blocked']}"
        print(
            f"{mask(plan['key']):<10}{plan['name'][:12]:<13}{plan['storedStatus']:<12}"
            f"{plan['derivedStatus']:<11}  {'; '.join(writes)}{note}"
        )

    print()
    print(f"  already correct, nothing to do        {len(already)}")
    print(f"  can be closed from local evidence     {len(fixable)}")
    print(f"  still need a human to ask something   {len(stuck)}")
    print(f"  stored status disagrees with the data {sum(1 for p in plans if p['disagrees'])}")
    inferred = sum(
        1
        for p in plans
        if "privacyNoticeSentAt" in p["profile"] and p["key"] not in notice_times
    )
    if inferred:
        print(
            f"  privacy-notice times taken from the user's first contact rather than"
            f" a delivery record: {inferred}"
        )
    gaps = Counter(gap for p in plans for gap in p["unprovable"])
    if gaps:
        print("\n  what is left to ask, by field:")
        for field, count in gaps.most_common():
            print(f"    {field:<16} {count}")

    if not arguments.apply:
        print("\nDry run. Re-run with --apply to write this.")
        return 0

    print("\napplying...")
    written = Counter()
    for plan in plans:
        key = plan["key"]
        # Captured before the first write. Every one of these mutations
        # recomputes the status itself, so by the time refreshSetup runs the
        # flip has already happened and comparing there reports nothing — which
        # it did on the first live run, printing 31 writes and no transitions.
        status_before = plan["storedStatus"]
        if plan["profile"]:
            # currentField is echoed back unchanged so backfilling a weight
            # does not move anybody's place in their own conversation.
            field = plan["currentField"] or "confirmation"
            result = convex("onboarding", key, currentField=field, profile=plan["profile"])
            written["profile" if result.get("success") else "profile FAILED"] += 1
            if not result.get("success"):
                print(f"  {mask(key)} profile: {result.get('error')}")
        if plan["target"]:
            result = convex("target", key, **plan["target"])
            written["target" if result.get("success") else "target FAILED"] += 1
            if not result.get("success"):
                print(f"  {mask(key)} target: {result.get('error')}")
        if plan["reminder"]:
            result = convex("reminder", key, **plan["reminder"])
            written["reminder" if result.get("success") else "reminder FAILED"] += 1
            if not result.get("success"):
                print(f"  {mask(key)} reminder: {result.get('error')}")

        # Always, including for users nothing was written for: this is the call
        # that recomputes status, and the seven users who were complete all
        # along need only this.
        result = convex("refreshSetup", key)
        if result.get("success"):
            if result.get("after") != status_before:
                written[f"status {status_before} -> {result['after']}"] += 1
        else:
            written["refresh FAILED"] += 1
            print(f"  {mask(key)} refresh: {result.get('error')}")

    print()
    for label, count in sorted(written.items()):
        print(f"  {label:<34} {count}")
    print("\nRe-run without --apply to see the state you are left with.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
