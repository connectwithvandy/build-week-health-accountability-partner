#!/usr/bin/env python3
"""
Land two answers people gave that no store ever recorded.

    ~/.hermes/hermes-agent/venv/bin/python scripts/ted-land-missed-answers.py
    ~/.hermes/hermes-agent/venv/bin/python scripts/ted-land-missed-answers.py --apply

Not a general tool. Two named users, two fields, each quoted from their own
messages in `~/.hermes/state.db`, because both were about to be asked a
question they had already answered — which is the thing that made a beta user
write "But you have this info already. I have answer this before already."

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

WHAT IT WRITES, and nothing else:

  * Pallavi  sex             -> "female"
  * Sarah    dailyReviewTime -> "21:00", then her `ted:<key>:daily_review`
                                cron job, which is what actually makes the
                                check-in happen

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
    args = parser.parse_args()

    recon = _convex_module()
    convex = recon.convex

    pallavi = _audit_row(convex, PALLAVI)
    sarah = _audit_row(convex, SARAH)
    if not pallavi or not sarah:
        print("could not read both users back from setupAudit; nothing written")
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

    if not args.apply:
        print("Dry run. Re-run with --apply.")
        return 0

    field = str(pallavi.get("currentField") or "confirmation")
    result = convex("onboarding", PALLAVI, currentField=field, profile={"sex": "female"})
    print(f"  Pallavi sex: {'ok' if result.get('success') else result.get('error')}")

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
    print()
    print("RESTART THE GATEWAY, or the gate's copy is overwritten from memory:")
    print("  hermes gateway restart")

    print()
    print("Read back:")
    for who, key in (("Pallavi", PALLAVI), ("Sarah", SARAH)):
        row = _audit_row(convex, key)
        print(f"  {who:9} status={row.get('derivedStatus')!r} missing={row.get('missing')}")
    print()
    print("No message was sent to either of them. Both still need a human reply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
