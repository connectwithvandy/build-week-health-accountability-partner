#!/usr/bin/env python3
"""
Make the gate's copy of a profile agree with Convex, taking the safer answer
wherever the two disagree about age.

    python3 scripts/ted-repair-profile-drift.py
    python3 scripts/ted-repair-profile-drift.py --apply \
      && HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart

WHY. The gate keeps its own copy of age, height, weight, sex and the tracked
calorie figure in a file on the gateway machine, and Convex keeps the same
facts. Nothing has ever reconciled them, so a fact can be correct in one and
absent or wrong in the other. Two things break when the gate's copy is the
empty one, and both were reported by the owner on 7 Sep 2026:

  * `setup_gate` sees no age and starts the counted questions again, so a
    long-standing user is asked "how old are you?" mid-conversation and thinks
    onboarding restarted.
  * `_tracked_kcal` returns nothing, so `_daily_overview` drops the "left"
    figure and the progress bar and prints a bare calorie total. That is the
    "old format" meal card.

THE ONE THAT MATTERS MOST. Tanishka answered "17 I said u brother" on 4 Sep and
Convex holds 17. The gate holds **50**, which is her weight: the answer landed
on the wrong question, the same anchoring bug ted-repair-swallowed-weights.py
was written for, pointed the other way. The gate is what decides whether
`calorie_gate` refuses, so for six days Ted has believed a 17-year-old is 50
and would have handed her calorie numbers on request. Nothing reached her only
because she stopped replying before the flow got that far.

So the age rule here is not "Convex wins". It is **the lower of the two wins**,
because the only direction that costs anything is believing a child is an
adult. Every other field takes Convex's value when the gate has none, and
leaves the gate alone when it already has one: a disagreement about height is
not worth overwriting an answer somebody typed.

Where the resulting age is under 18 this also sets the gate's `minor` flag, so
`_is_known_minor` refuses without having to re-derive it.

THE RESTART MATTERS. The gateway holds this file in memory and rewrites it on
the next turn, so a repair without a restart is lost. Run the two together.

Dry run by default.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import ted_deletion_guard

REPO = Path(__file__).resolve().parent.parent
GATE_STATE = Path.home() / ".hermes" / "state" / "ted-safety-gates-onboarding.json"
HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")

MINIMUM_AGE = 18

# Convex field -> the gate's name for the same fact.
PROFILE_FIELDS = {
    "age": "age",
    "heightCm": "height_cm",
    "weightKg": "weight_kg",
    "sex": "sex",
    "goal": "goal",
    "name": "name",
}


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
        ["npx", "convex", "data", table, "--deployment", "hardy-scorpion-901",
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def tracked_kcal_change(
    record: dict, convex_kcal: object
) -> tuple[int, str] | None:
    """The gate's tracked calorie figure to write, and why, or None.

    Two cases, and the second is the one `bfe6c7c` did not reach.

    The gate has nothing at all, so `_tracked_kcal` returns nothing,
    `_daily_overview` drops the "left" figure and the progress bar, and the
    user gets a bare calorie total — the "old format" meal card.

    Or the gate never recorded an agreed target and fell back to the
    maintenance figure while Convex holds one that was agreed. Ted then counts
    the day against maintenance and the record says something else. John was
    scored against 2,010 having been told 2,100; venky is trying to gain at
    2,100 and was counted against his 1,910 maintenance, which removes the
    surplus his goal needs; Hari is losing weight, was told 1,870, and was
    being scored against 2,200.

    Deliberately narrow. Only when the gate's tracked figure IS its maintenance
    figure, which is the tell that no target was ever stored there. A gate
    number that differs from both is a real second opinion, and
    `ted-target-direction.py` is explicit that those need a conversation and
    not a write.
    """
    if not isinstance(convex_kcal, (int, float)) or convex_kcal <= 0:
        return None
    tracking = record.get("tracking_kcal")
    maintenance = record.get("maintenance_kcal")
    if tracking in (None, "") and maintenance in (None, ""):
        return int(convex_kcal), f"tracking_kcal missing -> {int(convex_kcal)}"
    if (
        isinstance(tracking, (int, float))
        and isinstance(maintenance, (int, float))
        and int(tracking) == int(maintenance)
        and int(convex_kcal) != int(tracking)
    ):
        return int(convex_kcal), (
            f"tracking_kcal {int(tracking)} was only maintenance "
            f"-> {int(convex_kcal)} (the agreed target)"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    users = convex_rows("users")
    targets = {t["userId"]: t for t in convex_rows("targets")}
    state = json.loads(GATE_STATE.read_text(encoding="utf-8"))
    gate = state.get("users", {})
    # See ted_deletion_guard: a repair script must not refill an erased record.
    skipped = ted_deletion_guard.note(gate)
    if skipped:
        print(skipped)
    gate = ted_deletion_guard.living(gate)

    plans = []
    for user in users:
        key = user["whatsappUserId"]
        record = gate.get(key)
        if record is None:
            continue
        changes: dict[str, object] = {}
        notes: list[str] = []

        for convex_field, gate_field in PROFILE_FIELDS.items():
            convex_value = user.get(convex_field)
            gate_value = record.get(gate_field)
            if convex_value in (None, ""):
                continue

            if gate_field == "age":
                # The lower of the two, always. Believing a child is an adult
                # is the only error here with a cost.
                if isinstance(gate_value, (int, float)) and gate_value != convex_value:
                    safer = min(int(gate_value), int(convex_value))
                    if safer != gate_value:
                        changes["age"] = safer
                        notes.append(
                            f"age {gate_value} -> {safer} (Convex says "
                            f"{convex_value}; lower wins)"
                        )
                elif gate_value in (None, ""):
                    changes["age"] = int(convex_value)
                    notes.append(f"age missing -> {convex_value}")
                continue

            # Every other field: fill a gap, never overwrite an answer.
            if gate_value in (None, ""):
                changes[gate_field] = convex_value
                notes.append(f"{gate_field} missing -> {convex_value}")

        # The tracked figure, so the meal card can show "left" again.
        target = targets.get(user["_id"], {})
        tracked = tracked_kcal_change(record, target.get("calories"))
        if tracked:
            changes["tracking_kcal"], note = tracked
            notes.append(note)

        final_age = changes.get("age", record.get("age"))
        if isinstance(final_age, (int, float)) and final_age < MINIMUM_AGE:
            if not record.get("minor"):
                changes["minor"] = True
                notes.append(f"minor flag set (age {int(final_age)})")

        if changes:
            plans.append({
                "key": key, "name": user.get("name") or "(no name)",
                "changes": changes, "notes": notes,
            })

    mode = "APPLY" if args.apply else "DRY RUN — nothing is written"
    print("=" * 88)
    print(f"GATE PROFILE REPAIR   {datetime.now():%d %b %Y %H:%M}   {mode}")
    print("=" * 88)
    if not plans:
        print("\nNothing to repair.")
        return 0
    for plan in plans:
        print(f"\n  {plan['name']}")
        for note in plan["notes"]:
            marker = "  ** " if "minor" in note or "lower wins" in note else "     "
            print(f"{marker}{note}")

    if not args.apply:
        print("\nDry run. Re-run with --apply, and restart the gateway in the same command.")
        return 0

    backup = GATE_STATE.with_suffix(
        f".json.bak.pre-profile-repair-{datetime.now():%Y%m%dT%H%M%S}"
    )
    shutil.copy2(GATE_STATE, backup)
    print(f"\nbacked up to {backup.name}")

    for plan in plans:
        gate[plan["key"]].update(plan["changes"])
    GATE_STATE.write_text(
        json.dumps({"users": gate}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"repaired {len(plans)} user(s)")
    print("\nRESTART THE GATEWAY NOW or this is overwritten from memory:")
    print("  HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
