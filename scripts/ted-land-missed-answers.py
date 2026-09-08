#!/usr/bin/env python3
"""
Land answers people gave that no store ever recorded.

    ~/.hermes/hermes-agent/venv/bin/python scripts/ted-land-missed-answers.py
    ~/.hermes/hermes-agent/venv/bin/python scripts/ted-land-missed-answers.py --apply

Not a general tool. Named users, named fields, each one quoted from where it
was actually said, because every one of them was about to be asked a question
they had already answered — which is the thing that made a beta user write
"But you have this info already. I have answer this before already."

PALLAVI, `sex`. She answered "Fenale" at 09:03:56 and "Female" at 09:04:37 on
4 Sep 2026. Neither landed: Convex holds her age, height, weight and goal, and
an empty `sex`. `setup_gate` reads that empty field and starts the counted
questions, which is how the 7 Sep win-back message came to ask her for a height
and weight she had given three days earlier.

SARAH, `dailyReviewTime`. The win-back message at 16:54 on 7 Sep asked her for
a check-in time. She replied "9pm work" at 16:54, meaning 9pm works. Ted read
it as her working late and answered "working late tonight?", so nothing saved
it. Her setup is otherwise complete: `setupAudit` reports `checkInTime` as the
only missing piece and her calorie target is already 1,430.

VANDY, `sex` and `activity`. She onboarded on 4 Sep, when the counted flow was
five questions and sex was not one of them, so she was never asked. At 15:50:53
on 8 Sep `_missing_profile_reply` asked her mid-meal, uncounted: "one more for
the formula: male or female?". She answered "Female" at 15:51:00, quoting the
question. Nothing stored it. Unlike the counted questions, that one records no
`setup_asking`, so there was nothing listening for the answer, and the model's
"noted, vandy" was stripped by `action_claim_gate` as a claim no tool backed.
Her `activity` was never asked for at all and is the next question in that same
uncounted list.

Her sex is her own word in `~/.hermes/state.db`. Her activity is not: she gave
it to the builder session on 8 Sep as "4 5 days gym", not to Ted. It is written
here because she asked for it to be, and it is recorded that way rather than
dressed up as a WhatsApp answer she never sent.

WHAT IT WRITES, and nothing else:

  * Pallavi  sex             -> "female"
  * Sarah    dailyReviewTime -> "21:00", then her `ted:<key>:daily_review`
                                cron job, which is what actually makes the
                                check-in happen
  * Vandy    sex             -> "female", in Convex and in the gate's file
             activity        -> "active", in the gate's file only

`active` is not a value anybody typed. It is what the gate's own
`_find_activity` returns for "4 5 days gym", asserted below so this script and
the live path can never drift apart. There is no `activity` column in Convex:
`_estimated_maintenance` reads the gate's file, so that is where it goes.

`currentField` is echoed back unchanged on the profile write, the same way
`ted-reconcile-setup.py` does it, so neither write moves anybody's place in
their own conversation. The cron job is created by calling the gate's own
`_sync_reminder_jobs` rather than by assembling a `hermes cron add` by hand:
the naming convention, the timezone and the prompt text are all decided in one
place already, and a second copy of that logic would eventually disagree with
the first.

Run under the Hermes venv python — `_sync_reminder_jobs` imports the gate,
which needs PyYAML. Dry run by default.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PALLAVI = (
    "whatsapp:sha256:caf33e89c565052614a429eeb1c6afb90d91c71e0f21265d5900db0b649efee7"
)
SARAH = (
    "whatsapp:sha256:6bc15477a7983be13f560e56d41c3adc7e7b660cf5d373ff2383f729b62e6504"
)
SARAH_CHAT = "86483545419925@lid"
SARAH_REVIEW_TIME = "21:00"
VANDY = (
    "whatsapp:sha256:cbf8ffc790890dc7ffa6f11d91a70647fca0cf4c119ec238ed5827b6eabe8c71"
)
# Her words, and the value the gate reads them as. The second is asserted
# against `_find_activity` at apply time rather than trusted here.
VANDY_ACTIVITY_SAID = "4 5 days gym"
VANDY_ACTIVITY = "active"


def _convex_module():
    """Reuse the reconcile script's Convex client, secret handling included."""
    path = REPO / "scripts" / "ted-reconcile-setup.py"
    spec = importlib.util.spec_from_file_location("ted_reconcile_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate_module():
    sys.path.insert(0, str(REPO / "hermes"))
    import ted_safety_gates  # noqa: PLC0415 — deliberately late, needs the venv

    return ted_safety_gates


def _audit_row(convex, key: str) -> dict:
    audit = convex("setupAudit", "builder-readback")
    for row in audit.get("users") or audit.get("rows") or []:
        if str(row.get("whatsappUserId") or "") == key:
            return row
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    # Every write below is idempotent except Sarah's cron sync, and a second
    # copy of a reminder is its own bug — see `ted-dedupe-reminders.py`. Once
    # someone's answer has landed there is no reason to replay it, so a later
    # addition to this script can be applied on its own.
    parser.add_argument(
        "--only",
        choices=("pallavi", "sarah", "vandy"),
        action="append",
        help="apply just these people (default: all of them)",
    )
    args = parser.parse_args()

    recon = _convex_module()
    convex = recon.convex

    pallavi = _audit_row(convex, PALLAVI)
    sarah = _audit_row(convex, SARAH)
    vandy = _audit_row(convex, VANDY)
    if not pallavi or not sarah or not vandy:
        print("could not read all three users back from setupAudit; nothing written")
        return 1

    print("=" * 78)
    print("LAND MISSED ANSWERS   " + ("APPLY" if args.apply else "DRY RUN — nothing is written"))
    print("=" * 78)
    print()
    print(f"  Pallavi   sex -> female")
    print(f"            her words, twice, 4 Sep 09:03:56 and 09:04:37")
    print(f"            currentField stays {pallavi.get('currentField')!r}")
    print(f"            still missing after this: {pallavi.get('missing')}")
    print()
    print(f"  Sarah     dailyReviewTime -> {SARAH_REVIEW_TIME}")
    print(f"            her words, '9pm work', 7 Sep 16:54")
    print(f"            plus the daily_review cron job that makes it fire")
    print(f"            still missing before this: {sarah.get('missing')}")
    print()
    print(f"  Vandy     sex -> female")
    print(f"            her word, 8 Sep 15:51:00, replying to the gate's own question")
    print(f"            activity -> {VANDY_ACTIVITY} (from {VANDY_ACTIVITY_SAID!r},")
    print(f"            said to the builder session, not to Ted)")
    print(f"            currentField stays {vandy.get('currentField')!r}")
    print(f"            still missing before this: {vandy.get('missing')}")
    print()

    chosen = set(args.only or ("pallavi", "sarah", "vandy"))
    if args.only:
        print(f"  applying only: {', '.join(sorted(chosen))}")
        print()

    if not args.apply:
        print("Dry run. Re-run with --apply.")
        return 0

    if "pallavi" in chosen:
        field = str(pallavi.get("currentField") or "confirmation")
        result = convex(
            "onboarding", PALLAVI, currentField=field, profile={"sex": "female"}
        )
        print(f"  Pallavi sex: {'ok' if result.get('success') else result.get('error')}")

    if "sarah" in chosen:
        if _apply_sarah(convex, sarah) != 0:
            return 1

    if "vandy" not in chosen:
        return 0
    return _apply_vandy(convex, vandy)


def _apply_sarah(convex, sarah: dict) -> int:
    result = convex("reminder", SARAH, dailyReviewTime=SARAH_REVIEW_TIME)
    print(f"  Sarah time:  {'ok' if result.get('success') else result.get('error')}")
    if not result.get("success"):
        print("  cron job not attempted, because the preference it comes from did not save")
        return 1

    gate = _gate_module()
    settings = {"dailyReviewTime": SARAH_REVIEW_TIME, "items": []}
    scheduled = gate._sync_reminder_jobs(SARAH, SARAH_CHAT, settings)
    print(f"  Sarah cron:  {scheduled or 'nothing scheduled — check hermes cron list'}")

    # The gate keeps its own copy and `_review_time_done` reads that, not
    # Convex: "dailyReview" in its `done` list is the only thing standing
    # between Sarah and being asked for a check-in time a third time. Writing
    # Convex alone would have set the schedule and left the question loaded.
    # Mirrors exactly what `_save_review_time` writes on the normal path.
    record = dict(gate._onboarding(SARAH))
    done = sorted(set(record.get("done") or ()) | {"dailyReview"})
    gate._update_onboarding(
        SARAH,
        done=done,
        reminders_row=True,
        review_state="done",
        review_time=SARAH_REVIEW_TIME,
    )
    print(f"  Sarah gate:  done={done}")
    return 0


def _apply_vandy(convex, vandy: dict) -> int:
    gate = _gate_module()
    # The gate's file is the load-bearing half of this one, not Convex:
    # `_with_stored_profile_fields` and `_setup_profile` both read the file,
    # and `_estimated_maintenance` builds the number from what they return. A
    # Convex-only write would leave the uncounted question loaded, which is the
    # lesson from Sarah's check-in time directly above.
    read_as = gate._find_activity([VANDY_ACTIVITY_SAID])
    if read_as != VANDY_ACTIVITY:
        print(
            f"  Vandy:       ABORTED — the gate reads {VANDY_ACTIVITY_SAID!r} as "
            f"{read_as!r}, not {VANDY_ACTIVITY!r}. Nothing written for her."
        )
        return 1

    field = str(vandy.get("currentField") or "confirmation")
    result = convex("onboarding", VANDY, currentField=field, profile={"sex": "female"})
    print(f"  Vandy sex:   {'ok' if result.get('success') else result.get('error')}")

    gate._update_onboarding(VANDY, sex="female", activity=VANDY_ACTIVITY)
    record = gate._onboarding(VANDY)
    print(
        f"  Vandy gate:  sex={record.get('sex')!r} "
        f"activity={record.get('activity')!r}"
    )
    print()
    print("RESTART THE GATEWAY, or the gate's copy is overwritten from memory:")
    print("  hermes gateway restart")

    print()
    print("Read back:")
    for who, key in (("Pallavi", PALLAVI), ("Sarah", SARAH), ("Vandy", VANDY)):
        row = _audit_row(convex, key)
        print(f"  {who:9} status={row.get('derivedStatus')!r} missing={row.get('missing')}")
    print()
    print("No message was sent to anybody. They still need a human reply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
