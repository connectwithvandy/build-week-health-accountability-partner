#!/usr/bin/env python3
"""
Re-align the gate's stored goal and tracked calories with the goal the user
actually has.

    python3 scripts/ted-repair-goal-drift.py
    python3 scripts/ted-repair-goal-drift.py --apply \
      && HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart

THE BUG. `setup_gate` computes a calorie target once, at the moment the counted
questions close, and stores it as `tracking_kcal` — the number every meal card
counts "left" against. When the user then corrects their goal in open
conversation, the model updates Convex and nothing updates the gate. The two
stores disagree from that moment on, and the one the user sees is the stale one.

UD, 7 Sep 2026, is the clearest case. Asked "lose, gain, or stay consistent?"
he answered "Gaining" at 14:15, then at 14:36 said "I want to lose healthy a
kilo a week", and at 14:37 "i want to lose weight idiot". Convex moved to
loseWeight. The gate still held gainWeight and `tracking_kcal` 2580, which is
his *gaining* number, so every meal he logged was being scored against a
surplus while Ted told him he was cutting. Namrata, the same morning, said
"holding steady" and corrected herself two minutes later; same drift.

WHAT IT CHANGES, and only this, for a user whose gate goal disagrees with
Convex's:

  * `goal`          -> the Convex goal, which is the one the user last stated
  * `tracking_kcal` -> the number below
  * `target_lower`  -> the same, so a re-offer of the choice is consistent

THE NUMBER. What the user was already told wins, unless it is unsafe:

    the Convex target, when it is at or above their resting burn
    the gate's own `_loss_target`/`_gain_target`, when it is not

Resting burn is the floor `_loss_target` already enforces: below what the body
burns at rest is not a deficit, it is under-eating. UD's Convex target was
1,850 against a resting burn of 1,956, so his becomes 2,000 — the gate's own
maths, floored. Namrata's 1,700 clears her 1,334, so hers is left alone and
only the gate's copy is corrected to match.

WHAT IT WILL NOT TOUCH. A user whose two goals agree is not drift, even if
their target looks low. Gourav asked for 1,500-1,600 himself and Ted agreed to
1,550 against a 1,667 resting burn; that is a promise made to his face, and
silently moving it is worse than leaving it. Cases like his are printed as
needing a conversation, and the real fix is the gate that stops the model
agreeing in the first place.

Convex is only ever written when the stored target is below resting, and never
downwards.

THE RESTART MATTERS. The gateway holds this file in memory and rewrites the
whole thing on the next turn, so a repair without a restart is overwritten by
the stale copy. Run the two together, as above.

Dry run by default: it prints the plan and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hermes import ted_safety_gates as gates  # noqa: E402

GATE_STATE = Path.home() / ".hermes" / "state" / "ted-safety-gates-onboarding.json"
HERMES_ENV = Path.home() / ".hermes" / ".env"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")


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
        return {"success": False, "error": f"HTTP {error.code}: "
                f"{error.read().decode('utf-8', errors='replace')[:200]}"}
    except urllib.error.URLError as error:
        return {"success": False, "error": f"could not reach Convex: {error.reason}"}


def profile_from(record: dict) -> gates.CalorieProfile | None:
    """The gate's own profile object, or None when too little is on file."""
    if not all(record.get(f) is not None for f in ("age", "height_cm", "weight_kg")):
        return None
    return gates.CalorieProfile(
        age=int(record["age"]),
        height_cm=float(record["height_cm"]),
        weight_kg=float(record["weight_kg"]),
        # Defaults chosen to under-estimate rather than over-estimate the
        # resting burn, so an unknown sex or activity can never invent a floor
        # high enough to push somebody's target up on a guess.
        sex=record.get("sex") or "female",
        activity=record.get("activity") or "sedentary",
    )


def safe_target(goal: str, stored: int | None, profile: gates.CalorieProfile) -> tuple[int, str]:
    """The number to track against, and why it was chosen."""
    resting = gates._resting_energy(profile)
    computed = (
        gates._loss_target(profile) if goal == "loseWeight"
        else gates._gain_target(profile) if goal == "gainWeight"
        else gates._estimated_maintenance(profile)
    )
    if isinstance(stored, int) and stored >= resting:
        return stored, f"what they were already told ({stored}), clears resting {resting}"
    if isinstance(stored, int):
        return computed, f"{stored} is {resting - stored} under resting {resting}"
    return computed, "nothing stored in Convex"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the plan")
    parser.add_argument("--user", help="limit to one whatsappUserId")
    args = parser.parse_args()

    audit = convex("setupAudit", "builder-readback")
    if not audit.get("success"):
        print(f"could not read Convex: {audit.get('error')}", file=sys.stderr)
        return 1
    convex_users = {u["whatsappUserId"]: u for u in audit.get("users", [])}

    state = json.loads(GATE_STATE.read_text(encoding="utf-8"))
    gate_users = state.get("users", {})

    # setupAudit carries the goal and target, so this is one read for everyone
    # rather than a round trip per user.
    plans, conversations = [], []
    for key, record in gate_users.items():
        if args.user and key != args.user:
            continue
        row = convex_users.get(key)
        if not row:
            continue
        cgoal = row.get("goal")
        ctarget = row.get("calorieTarget")
        ggoal = record.get("goal")
        profile = profile_from(record)
        if profile is None:
            continue
        resting = gates._resting_energy(profile)

        if cgoal and ggoal and cgoal != ggoal:
            target, why = safe_target(cgoal, ctarget, profile)
            plans.append({
                "key": key, "name": record.get("name") or row.get("name") or "(no name)",
                "from_goal": ggoal, "to_goal": cgoal,
                "from_track": record.get("tracking_kcal"), "to_track": target,
                "convex_target": ctarget, "raise_convex": bool(
                    isinstance(ctarget, int) and ctarget < resting
                ),
                "why": why, "resting": resting,
            })
        elif isinstance(ctarget, int) and ctarget < resting:
            conversations.append({
                "name": record.get("name") or row.get("name") or "(no name)",
                "target": ctarget, "resting": resting, "goal": cgoal,
            })

    mode = "APPLY" if args.apply else "DRY RUN — nothing is written"
    print("=" * 92)
    print(f"GOAL DRIFT REPAIR   {datetime.now():%d %b %Y %H:%M}   {mode}")
    print("=" * 92)

    if not plans:
        print("\nNo goal drift found.")
    for p in plans:
        print(f"\n  {p['name']}")
        print(f"    goal           {p['from_goal']}  ->  {p['to_goal']}")
        print(f"    tracking_kcal  {p['from_track']}  ->  {p['to_track']}")
        print(f"    Convex target  {p['convex_target']}"
              + (f"  ->  {p['to_track']}  (raised: {p['why']})" if p["raise_convex"]
                 else f"  (left alone: {p['why']})"))

    if conversations:
        print("\n" + "-" * 92)
        print("NOT TOUCHED — the goals agree, so this is a promise made to their face,")
        print("not drift. Moving it silently would be worse. These need a conversation:")
        for c in conversations:
            print(f"    {c['name']:<14} target {c['target']} vs resting {c['resting']}"
                  f"  ({c['resting'] - c['target']} under)  goal={c['goal']}")

    if not args.apply:
        print("\nDry run. Re-run with --apply, and restart the gateway in the same command.")
        return 0

    backup = GATE_STATE.with_suffix(
        f".json.bak.pre-goal-repair-{datetime.now():%Y%m%dT%H%M%S}"
    )
    shutil.copy2(GATE_STATE, backup)
    print(f"\nbacked up to {backup.name}")

    for p in plans:
        record = gate_users[p["key"]]
        record["goal"] = p["to_goal"]
        record["tracking_kcal"] = p["to_track"]
        record["target_lower"] = p["to_track"]
        if p["raise_convex"]:
            result = convex("target", p["key"], calories=p["to_track"])
            print(f"  {p['name']}: Convex target -> {p['to_track']}  "
                  f"{'ok' if result.get('success') else result.get('error')}")

    GATE_STATE.write_text(
        json.dumps({"users": gate_users}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  gate state written for {len(plans)} user(s)")
    print("\nRESTART THE GATEWAY NOW or this is overwritten from memory:")
    print("  HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
