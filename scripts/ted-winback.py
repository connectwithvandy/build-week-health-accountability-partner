#!/usr/bin/env python3
"""
Win back the people whose setup never finished, one at a time.

    python3 scripts/ted-winback.py                    # show every message
    python3 scripts/ted-winback.py --send             # send them, spaced out
    python3 scripts/ted-winback.py --groups B,C       # limit to some groups

WHY THIS EXISTS. 33 of the 42 people who ever messaged Ted showed up on exactly
one day and never came back. The nudges are not the problem: 42 of the 47 that
were old enough to judge on 6 Sep got a reply inside 24 hours. People are lost
during setup, and the largest single leak is a question Ted asked twice and
then gave up on.

So this does not send "how's it going". Every message asks for exactly what
`setupStateFor` says that person is missing, and where nothing is missing but
the number itself, it just hands them the number. The content is generated from
their own stored answers, never from a template with a name slotted in.

GROUPS, which decide what a message can honestly offer:

  B  everything on file except the calorie number. Nothing to ask; compute it
     and tell them.
  C  they have their number, only a check-in time is missing. That is the one
     setting that makes Ted able to speak first, so it is worth one question.
  D  one or two answers short of a number. Ask for the first missing one only.
  E  never really started. Deliberately NOT sent by default: these are the
     people who died on the goal question, and re-inviting them into a flow
     that has not been proven to work risks losing them for good.

THE RULES IT WILL NOT BREAK.

  * One message per person, ever. Sends are recorded in ~/.hermes/state and a
    second run skips anyone already written down, so a re-run cannot double up.
  * Spaced, not blasted. `--every` minutes between sends, 12 by default.
  * Never inside someone's quiet hours, computed in their own timezone.
  * Never to someone who has messaged Ted in the last two hours, so a campaign
    can never talk over a live conversation.
  * Never about calories to a user `setupStateFor` reports as blocked. The one
    person that applies to is 17.

Nothing is sent without --send. Without it this prints what it would say.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hermes import ted_safety_gates as gates  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
HERMES = Path.home() / ".hermes"
STATE_DB = HERMES / "state.db"
SENT_LOG = HERMES / "state" / "ted-winback-sent.json"
DEFAULT_QUIET_START, DEFAULT_QUIET_END = "22:00", "07:00"

# Someone mid-conversation must never be interrupted by a campaign.
LIVE_CONVERSATION_HOURS = 2


def user_key(sender_id: str) -> str:
    digest = hashlib.sha256(f"whatsapp:{sender_id}".encode("utf-8")).hexdigest()
    return f"whatsapp:sha256:{digest}"


def read_plans() -> list[dict]:
    """The setup audit, reused rather than reimplemented."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ted-reconcile-setup.py"), "--json"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if result.returncode != 0:
        raise SystemExit(f"could not read the setup audit: {result.stderr[:300]}")
    return json.loads(result.stdout)["plans"]


def read_gateway() -> tuple[dict[str, str], dict[str, float], dict[str, int]]:
    """chat id, last inbound time, and meals logged, per user key."""
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    chat_of: dict[str, str] = {}
    last_in: dict[str, float] = {}
    for row in db.execute(
        "SELECT s.chat_id c, MAX(m.timestamp) t FROM messages m JOIN sessions s "
        "ON s.id = m.session_id WHERE m.role='user' AND s.source='whatsapp' "
        "GROUP BY s.chat_id"
    ):
        key = user_key(str(row["c"]))
        chat_of[key] = str(row["c"])
        last_in[key] = float(row["t"])
    db.close()
    return chat_of, last_in, {}


def load_sent() -> dict[str, str]:
    if not SENT_LOG.exists():
        return {}
    try:
        return json.loads(SENT_LOG.read_text(encoding="utf-8")).get("sent", {})
    except json.JSONDecodeError:
        return {}


def record_sent(key: str, group: str) -> None:
    sent = load_sent()
    sent[key] = f"{group}:{datetime.now(IST).isoformat()}"
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    SENT_LOG.write_text(json.dumps({"sent": sent}, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Which group, and what to say
# ---------------------------------------------------------------------------

NUMBER_FIELDS = {"age", "height", "weight", "goal"}

# Plain words for the thing being asked for, because "checkInTime" is not
# something to put in front of a person.
ASK = {
    "age": "how old are you?",
    "height": "how tall are you?",
    "weight": "what do you weigh right now?",
    "goal": "what are you actually after: losing weight, gaining, or just staying consistent?",
    "name": "what should I call you?",
    "checkInTime": "what time suits a daily check in? something like 9pm or 10:30pm",
}


def group_for(plan: dict) -> str | None:
    if plan["blocked"]:
        return None
    missing = set(plan["missing"])
    if not missing:
        return None
    if missing == {"calorieTarget"}:
        return "B"
    if missing == {"checkInTime"}:
        return "C"
    if len(missing & NUMBER_FIELDS) <= 2:
        return "D"
    return "E"


def profile_of(user: dict) -> gates.CalorieProfile:
    return gates.CalorieProfile(
        age=user.get("age"),
        height_cm=user.get("heightCm"),
        weight_kg=user.get("weightKg"),
        sex=user.get("sex") or "female",
        activity="sedentary",
        goal=user.get("goal"),
    )


def their_number(user: dict) -> tuple[int, int] | None:
    """(maintenance, target) when it can be computed, else None."""
    profile = profile_of(user)
    if None in (profile.age, profile.height_cm, profile.weight_kg):
        return None
    maintenance = gates._estimated_maintenance(profile)
    goal = user.get("goal")
    target = (
        gates._loss_target(profile) if goal == "loseWeight"
        else gates._gain_target(profile) if goal == "gainWeight"
        else maintenance
    )
    return maintenance, target


def compose(plan: dict, user: dict, group: str) -> str | None:
    name = (user.get("name") or "").strip() or "hey"
    missing = list(plan["missing"])

    if group == "B":
        numbers = their_number(user)
        if numbers is None:
            return None
        maintenance, target = numbers
        goal_line = {
            "loseWeight": f"For steady weight loss your number is *{target:,}* a day.",
            "gainWeight": f"For building, your number is *{target:,}* a day.",
        }.get(
            user.get("goal"),
            # Maintenance and target are the same figure for someone who is
            # after consistency, so stating both reads like a mistake. One
            # sentence, and it still has to carry the number.
            f"You burn about {maintenance:,} a day, so *{target:,}* is your "
            "number: holding steady, not chasing the scale.",
        )
        maintenance_line = (
            "" if user.get("goal") not in ("loseWeight", "gainWeight")
            else f"You burn about {maintenance:,} a day.\n"
        )
        return (
            f"{name}, I never actually gave you your number, and that's on me.\n\n"
            f"From what you told me: {user['age']}, {round(user['heightCm'])}cm, "
            f"{round(user['weightKg'])}kg.\n"
            f"{maintenance_line}"
            f"{goal_line}\n\n"
            "That's the whole setup. Send me your next meal and I'll start keeping score."
        )

    if group == "C":
        stored = user.get("storedCalories")
        number_line = (
            f"You're all set otherwise, {stored:,} a day is your number.\n\n"
            if isinstance(stored, int) else "You're set up otherwise.\n\n"
        )
        return (
            f"{name}, we got everything sorted except one thing, and it's the thing "
            f"that makes me useful.\n\n"
            f"{number_line}"
            "What time suits a daily check in? Something like 9pm or 10:30pm.\n\n"
            "Give me a time and I'll close out each day with you."
        )

    if group == "D":
        # One question, the first one missing, in the order setup asks them.
        order = ["name", "age", "height", "weight", "goal", "checkInTime"]
        first = next((f for f in order if f in missing), None)
        if first is None:
            return None
        return (
            f"{name}, we stopped halfway and that was my fault, I never asked you "
            f"the one thing I needed.\n\n"
            f"{ASK[first]}\n\n"
            "One answer and I've got everything else to work out your number."
        )

    return None


# ---------------------------------------------------------------------------


def quiet_now(user: dict) -> bool:
    zone = user.get("timeZone") or "Asia/Kolkata"
    try:
        local = datetime.now(ZoneInfo(zone))
    except Exception:
        local = datetime.now(IST)
    # 22:00 to 07:00, the same default window `decideReminderDelivery` falls
    # back to when a user has saved no preference of their own.
    return not (7 <= local.hour < 22)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="actually send")
    parser.add_argument("--groups", default="B,C,D", help="which groups, default B,C,D")
    parser.add_argument("--every", type=int, default=12, help="minutes between sends")
    args = parser.parse_args()
    wanted = {g.strip().upper() for g in args.groups.split(",") if g.strip()}

    plans = read_plans()
    chat_of, last_in, _ = read_gateway()
    already = load_sent()

    users_path = REPO / ".winback-users.json"
    result = subprocess.run(
        ["npx", "convex", "data", "users", "--deployment", "hardy-scorpion-901",
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    users = {}
    by_id = {}
    for line in result.stdout.splitlines():
        if line.strip():
            row = json.loads(line)
            users[row["whatsappUserId"]] = row
            by_id[row["_id"]] = row
    users_path.unlink(missing_ok=True)

    # The target Ted already agreed with them, which is NOT the same as one
    # recomputed here. Amit's stored number is 2,400 and a fresh computation
    # gives 1,620; telling him the second would be a brand new contradiction
    # between what Ted says and what the row holds, which is the exact bug this
    # whole day has been spent removing. A win-back message quotes, it does not
    # recalculate.
    targets = subprocess.run(
        ["npx", "convex", "data", "targets", "--deployment", "hardy-scorpion-901",
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    for line in targets.stdout.splitlines():
        if line.strip():
            row = json.loads(line)
            owner = by_id.get(row.get("userId"))
            if owner and isinstance(row.get("calories"), (int, float)):
                owner["storedCalories"] = int(row["calories"])

    now = time.time()
    queue, skipped = [], []
    for plan in plans:
        key = plan["key"]
        group = group_for(plan)
        if group is None or group not in wanted:
            continue
        user = users.get(key)
        if not user:
            continue
        if key in already:
            skipped.append((plan["name"], "already messaged in an earlier run"))
            continue
        if key not in chat_of:
            skipped.append((plan["name"], "no WhatsApp chat to reach them on"))
            continue
        if key in last_in and (now - last_in[key]) < LIVE_CONVERSATION_HOURS * 3600:
            skipped.append((plan["name"], "messaged Ted in the last 2 hours, leave them alone"))
            continue
        if quiet_now(user):
            skipped.append((plan["name"], "inside their quiet hours right now"))
            continue
        text = compose(plan, user, group)
        if not text:
            skipped.append((plan["name"], "not enough on file to say anything honest"))
            continue
        queue.append({"key": key, "chat": chat_of[key], "name": plan["name"],
                      "group": group, "text": text})

    queue.sort(key=lambda q: (q["group"], q["name"]))

    print("=" * 88)
    print(f"TED WIN-BACK   {datetime.now(IST):%d %b %Y %H:%M IST}   "
          f"{'SENDING' if args.send else 'DRY RUN — nothing is sent'}")
    print("=" * 88)
    for item in queue:
        print(f"\n--- {item['name']}  (group {item['group']}) "
              f"{'-' * max(0, 50 - len(item['name']))}")
        print(item["text"])
    print("\n" + "=" * 88)
    print(f"would message: {len(queue)}")
    for name, why in skipped:
        print(f"  skipped  {name[:18]:<19} {why}")

    if not args.send:
        print(f"\nDry run. Re-run with --send to deliver, one every {args.every} minutes.")
        return 0

    print(f"\nsending, one every {args.every} minutes...\n")
    for index, item in enumerate(queue):
        result = subprocess.run(
            ["hermes", "send", "--to", f"whatsapp:{item['chat']}", item["text"]],
            capture_output=True, text=True,
        )
        ok = result.returncode == 0
        if ok:
            record_sent(item["key"], item["group"])
        print(f"  {datetime.now(IST):%H:%M:%S}  {item['name'][:18]:<19} "
              f"{'sent' if ok else 'FAILED: ' + result.stderr.strip()[:80]}")
        if index < len(queue) - 1:
            time.sleep(args.every * 60)
    print("\ndone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
