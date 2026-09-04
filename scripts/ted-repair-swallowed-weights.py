#!/usr/bin/env python3
"""Clear the weights the 4 Sep anchoring bug swallowed, so 3/5 gets asked.

Between 13:57 and 14:18 on 4 Sep 2026 the gate read a counted answer out of
the transcript instead of out of what the person typed. Hermes writes the
*model's* text to the transcript, never the gate's, and the model — which is
not told the gate is asking anything — ran its own onboarding underneath. So
"33" answering "*1/5* how old are you?" landed on the model's "and your
weight?" and was filed as 33 kg; "175" answering "*2/5* how tall are you?"
was filed as both 175 cm and 175 kg.

`cf48119` stops it happening. It cannot undo what is already stored, and a
stored weight is exactly what makes `_next_setup_field` skip question three:
the field is not empty, so it is never asked. These users would go straight
to the read-back carrying a number nobody gave.

What this clears, and only this:

  * a weight equal to that user's recorded age, or
  * a weight equal to that user's recorded height in cm,

and only while their setup is still running, and only when they have not
already been through the weight confirmation (`confirm_asked`) — somebody who
has corrected their own weight, as two users did within minutes, keeps it.

A real 33 kg adult who is 33 would be cleared here and asked again. That is
the right way round: the cost is one repeated question, and the alternative is
a maintenance figure built from a body that does not exist.

The gateway holds this state in memory and rewrites the whole file on the next
turn, so a repair without a restart is lost. Run them together:

    python3 scripts/ted-repair-swallowed-weights.py --apply \\
      && HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart

Dry run by default: it prints what it would clear and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

STATE = Path.home() / ".hermes" / "state" / "ted-safety-gates-onboarding.json"


def suspect(record: dict) -> str | None:
    """Why this stored weight cannot be trusted, or None if it can."""
    weight = record.get("weight_kg")
    if weight is None or record.get("setup") != "running":
        return None
    if "weight_kg" in (record.get("confirm_asked") or ()):
        return None
    age = record.get("age")
    if age is not None and float(age) == float(weight):
        return f"equals their age ({age})"
    height = record.get("height_cm")
    if height is not None and float(height) == float(weight):
        return f"equals their height ({height:g} cm)"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the change (default: dry run)"
    )
    args = parser.parse_args()

    payload = json.loads(STATE.read_text(encoding="utf-8"))
    users = payload.get("users") or {}

    found = []
    for key, record in users.items():
        reason = suspect(record)
        if reason:
            found.append((key, record, reason))

    if not found:
        print("nothing to clear.")
        return 0

    for key, record, reason in found:
        name = record.get("name") or "(no name)"
        print(f"  {name:12} weight {record['weight_kg']:g} kg — {reason}")

    if not args.apply:
        print(f"\n{len(found)} to clear. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = STATE.with_suffix(f".json.bak.pre-weight-repair-{stamp}")
    shutil.copy2(STATE, backup)

    for _, record, _ in found:
        record.pop("weight_kg", None)
        record.pop("weight_kg_from", None)
        # So the next turn asks question three rather than resuming mid-count.
        record["setup_asking"] = "weight_kg"

    STATE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\ncleared {len(found)}. backup: {backup.name}")
    print("restart the gateway now, or the running process will write it back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
