#!/usr/bin/env python3
"""Take Ted's own voice back out of the users' memory.

    python3 scripts/ted-purge-voice-rules.py               # dry run
    python3 scripts/ted-purge-voice-rules.py --keys-only   # no values printed
    python3 scripts/ted-purge-voice-rules.py --apply       # writes

WHY. T14's audit found seven rows in `userFacts` that are not facts about
anybody: `tone_preference`, `chat_style_preference`, `voice_style_preference`
and `meal_reply_rule`, each one restating SOUL.md's "How I talk" in the model's
own words. They are injected into every turn for those six people on top of a
SOUL.md that already says all of it, and they are the only rules in the system
that a conversation could rewrite.

The gate now refuses to save another one. That closed the door and left what
was already inside, because deleting live user data is not a side effect of
shipping a gate change.

WHICH KEYS. `is_voice_rule_key` from `hermes/ted_safety_gates`, which is the
same function the gate refuses with. One definition, so a key that stops being
refused stops being purged on the same day, and neither list can drift into
deleting something the other would have kept.

READ THE VALUES BEFORE YOU APPROVE ANYTHING. The first cut of T14's layer table
called four keys voice rules on the strength of their names, and reading the
values proved it wrong: `nudge_preferences` is "meals, water, supplements,
moving" and `daily_preference` is "wants end of day check for missed items" —
those are the person's own choices, and deleting them would have thrown away
the only record of what they asked for. So this prints what it would delete,
values and all, and `--keys-only` is there for a shoulder-surfed terminal.
Nothing is written to disk either way.

Dry run by default. `--apply` goes through the same authenticated `/ted-memory`
door the gateway uses, one person at a time, and prints what each one returned.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")
DEPLOYMENT = os.environ.get("TED_CONVEX_DEPLOYMENT", "hardy-scorpion-901")

# The gate refuses at most ten keys a request and so does the endpoint. Nobody
# in the live table is close, and a person who is has a bigger problem than
# this script.
MAX_KEYS_PER_REQUEST = 10


def voice_rule_test():
    """`is_voice_rule_key`, imported from the gate rather than restated here.

    By name on the path, the way `ted-idle-nudges.py` does it. Loading the
    package's `__init__.py` by file path instead looks equivalent and is not:
    the module never lands in `sys.modules`, and every frozen dataclass in the
    gate fails to build.
    """
    sys.path.insert(0, str(REPO / "hermes"))
    try:
        import ted_safety_gates as gates
    except ImportError as exc:
        raise SystemExit(f"Could not import the Ted safety gates: {exc}")
    return gates.is_voice_rule_key


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
    """One table from production, read-only. Twin of the reader in
    `ted-backfill-timezone.py`; the gate's per-user `/ted-memory` door cannot
    answer a question about everybody at once."""
    result = subprocess.run(
        ["npx", "convex", "data", table, "--deployment", DEPLOYMENT,
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if result.returncode != 0:
        print(f"could not read {table} from {DEPLOYMENT}:\n{result.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def voice_rules(facts: list[dict], users: list[dict], is_voice_rule) -> list[dict]:
    """Every stored fact that is a rule about how Ted talks, with its owner.

    A fact whose user row has gone is left out rather than reported: there is
    nobody for it to be injected into, and naming a deleted person in a report
    is the one thing a privacy teardown is supposed to have ended.
    """
    by_id = {user["_id"]: user for user in users}
    found = []
    for fact in facts:
        if not is_voice_rule(str(fact.get("key", ""))):
            continue
        user = by_id.get(fact.get("userId"))
        if not user or not user.get("whatsappUserId"):
            continue
        found.append({
            "name": user.get("name") or "(no name)",
            "whatsappUserId": user["whatsappUserId"],
            "key": str(fact["key"]),
            "value": str(fact.get("value", "")),
        })
    return sorted(found, key=lambda row: (row["name"].lower(), row["key"]))


def by_person(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["whatsappUserId"], []).append(row)
    return grouped


def forget(env: dict[str, str], whatsapp_user_id: str, keys: list[str]) -> str:
    """Delete named keys for one person through the gateway's own endpoint."""
    payload = json.dumps({
        "action": "forget-facts",
        "whatsappUserId": whatsapp_user_id,
        "keys": keys,
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
    if body.get("error") == "Unsupported action":
        return "refused: production has not been deployed with this route yet"
    if not body.get("success"):
        return f"refused: {body.get('error')}"
    return f"deleted {body.get('deleted', 0)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete them")
    parser.add_argument(
        "--keys-only",
        action="store_true",
        help="print key names without the rules themselves",
    )
    args = parser.parse_args()

    env = load_env()
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if args.apply and missing:
        print(f"cannot write without {', '.join(missing)}", file=sys.stderr)
        return 1

    rows = voice_rules(convex_rows("userFacts"), convex_rows("users"), voice_rule_test())
    if not rows:
        print("No voice rules are stored in anybody's memory.")
        return 0

    grouped = by_person(rows)
    people = "person" if len(grouped) == 1 else "people"
    print(
        f"{len(rows)} voice rule(s) stored across {len(grouped)} {people}. "
        f"Every one of these is injected into that person's every turn, "
        f"on top of the same thing said in SOUL.md.\n"
    )
    for row in rows:
        print(f"  {row['name']:16} {row['key']}")
        if not args.keys_only:
            value = row["value"]
            print(f"      {value if len(value) <= 300 else value[:300] + '…'}")

    if not args.apply:
        print(
            "\nNothing was deleted. Read the rules above and check that none of "
            "them is\nsomething the person actually asked for, then re-run with "
            "--apply."
        )
        return 0

    print()
    failures = 0
    for whatsapp_user_id, owned in grouped.items():
        keys = sorted({row["key"] for row in owned})[:MAX_KEYS_PER_REQUEST]
        result = forget(env, whatsapp_user_id, keys)
        print(f"  {owned[0]['name']:16} {', '.join(keys)} -> {result}")
        if not result.startswith("deleted"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
