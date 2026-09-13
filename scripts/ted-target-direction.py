#!/usr/bin/env python3
"""
Find people whose calorie target cannot produce the goal they asked for.

    python3 scripts/ted-target-direction.py
    python3 scripts/ted-target-direction.py --all   # show everyone, not just hits

WHAT THIS IS FOR, and why it is not ted-repair-goal-drift.py.

That script asks "is this number unsafe" — is the target below resting burn,
which is under-eating rather than a deficit. It found Vandy at 47 under and
Gourav at 117 under, and both are known and deliberate.

Nothing asked the opposite question. A target can be perfectly safe and still
be useless: if somebody says they want to lose weight and their number is their
maintenance, Ted spends every day telling them to eat exactly what they burn,
scoring every meal against it, and reporting success. The scale does not move,
and nothing in the system considers that a fault, because no rule was broken.

Found on 13 Sep 2026. Nine users had `nutritionSource: maintenanceEstimate`
alongside a goal that needs a deficit or a surplus. Three of them sat at their
maintenance to the calorie:

    Aadi              lose   maintenance 2170   target 2170
    Vishnu            lose   maintenance 2550   target 2550
    Protein Smoothie  gain   maintenance 1900   target 1900

WHY IT DOES NOT WRITE ANYTHING.

ted-repair-goal-drift.py states the rule this file obeys: what the user was
already told wins, unless it is unsafe. These numbers are not unsafe, so they
are not this script's to overwrite. Aadi was told 2,170 to his face. Silently
moving him to 1,740 would make Ted contradict itself with no explanation, which
is the exact failure the whole repair-script family exists to avoid.

So this reports, and a person decides. The fix for any individual row is a
conversation with that user; the fix for the class is that a directional goal
should never store a maintenance number as the target in the first place.

ACTIVITY. Read from the `activity_level` fact, which is free text ("desk job,
trains daily"), through the gate's own `_find_activity`. This matters: assuming
sedentary for everybody makes PG and Namrata look wrong when they train, and
their targets are fine once their real burn is used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hermes import ted_safety_gates as gates  # noqa: E402

DEPLOYMENT = "hardy-scorpion-901"
DIRECTIONAL = {"loseWeight", "gainWeight"}


def convex(table: str) -> list[dict]:
    done = subprocess.run(
        ["npx", "convex", "data", table, "--deployment", DEPLOYMENT,
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    rows = []
    for line in done.stdout.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def profile_for(user: dict, activity: str) -> gates.CalorieProfile:
    return gates.CalorieProfile(
        age=user.get("age"),
        height_cm=user.get("heightCm"),
        weight_kg=user.get("weightKg"),
        sex=user.get("sex") or "female",
        activity=activity,
        goal=user.get("goal"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="show every user, not only the hits")
    args = parser.parse_args()

    users = {u["_id"]: u for u in convex("users")}
    targets = {t["userId"]: t for t in convex("targets")}
    activity_text = {
        f["userId"]: f["value"]
        for f in convex("userFacts")
        if f.get("key") == "activity_level"
    }

    hits, fine, skipped = [], [], []
    for uid, user in users.items():
        goal = user.get("goal")
        target = targets.get(uid, {}).get("calories")
        if goal not in DIRECTIONAL or not isinstance(target, int):
            continue
        if None in (user.get("age"), user.get("heightCm"), user.get("weightKg")):
            skipped.append((user.get("name"), "not enough profile to compute a burn"))
            continue

        raw = activity_text.get(uid) or ""
        activity = gates._find_activity([raw]) if raw else None
        profile = profile_for(user, activity or "sedentary")
        maintenance = gates._estimated_maintenance(profile)
        would_set = (
            gates._loss_target(profile) if goal == "loseWeight"
            else gates._gain_target(profile)
        )

        wrong_way = target >= maintenance if goal == "loseWeight" else target <= maintenance
        row = {
            "name": user.get("name") or "(no name)",
            "goal": goal,
            "activity": activity or "sedentary (assumed)",
            "raw": raw,
            "maintenance": maintenance,
            "target": target,
            "would_set": would_set,
            "source": targets.get(uid, {}).get("nutritionSource"),
        }
        (hits if wrong_way else fine).append(row)

    width = 92
    print("=" * width)
    print("TARGET DIRECTION CHECK   READ ONLY — nothing is written, ever")
    print("=" * width)

    if not hits:
        print("\nEvery directional goal has a target that moves in that direction.")
    else:
        print(f"\n{len(hits)} target(s) cannot produce the goal they belong to:\n")
        for r in hits:
            direction = "deficit" if r["goal"] == "loseWeight" else "surplus"
            print(f"  {r['name']}")
            print(f"      goal            {r['goal']}")
            print(f"      activity        {r['activity']}   (\"{r['raw']}\")")
            print(f"      burns about     {r['maintenance']:,}")
            print(f"      target is       {r['target']:,}   <- no {direction} at all")
            print(f"      gate would set  {r['would_set']:,}")
            print(f"      source          {r['source']}")
            print()

    if args.all and fine:
        print("-" * width)
        print("POINTING THE RIGHT WAY:")
        for r in sorted(fine, key=lambda x: x["name"]):
            gap = r["target"] - r["maintenance"]
            print(f"    {r['name'][:18]:18s} {r['goal']:12s} burns {r['maintenance']:5,}  "
                  f"target {r['target']:5,}  ({gap:+,})")

    if skipped:
        print("-" * width)
        for name, why in skipped:
            print(f"    skipped  {str(name)[:18]:18s} {why}")

    print("-" * width)
    print("These are safe numbers, so this script will not change them. Each one")
    print("was said to that person's face, and moving it silently would make Ted")
    print("contradict itself. They need a conversation, not a write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
