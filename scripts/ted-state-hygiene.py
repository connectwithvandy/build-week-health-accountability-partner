#!/usr/bin/env python3
"""
Find test fixture keys sitting in the live gate state, and say so every day.

    python3 scripts/ted-state-hygiene.py
    python3 scripts/ted-state-hygiene.py --json
    python3 scripts/ted-state-hygiene.py --apply

WHY. `conftest.py` redirects the whole test run out of ~/.hermes, and its own
docstring records why: three fixture keys were found in the live consent file,
cleaned by hand, and put straight back five weeks later by one `python3 -m
unittest` run that skipped conftest. `TestRunIsolationTest` guards the suite.
Nothing guards the other road in, which is somebody — me, on 19 Sep 2026 —
calling a gate function in an ad-hoc script to prove a point. That wrote
`proof-mealtime` into the live onboarding state, next to nine older `probe-*`
keys from earlier the same day.

Three times now this has been caught by a person happening to look. That is
the same shape as the logs, the backups and the sweep itself: a rule nobody
enforces is a good intention. So the count goes on the daily sweep, and the
removal is one command instead of a hand-edit.

WHY IT MATTERS, beyond tidiness. These keys are inert only while they stay
unique. `conftest.py` names the real hazard: a fixture key that ever collided
with a real user key would mark that user as already-disclosed and silently
skip a disclosure they are owed. The 18+ block and the data notice both hang
off that file.

WHAT COUNTS AS A PERSON, and this is the whole safety of the thing.

`_user_state_key` returns one of two shapes, and a cleanup that does not know
the second one is more dangerous than the mess it removes:

  * `whatsapp:sha256:<64 hex>` — the normal key, a hash of the sender id.
  * the raw session id, `20260901_214702_20e16f0e`, used when the platform
    hands over no sender id at all.

The disclosures file holds 113 keys and 52 of them are the second shape. A
first draft of this script called anything that was not a hash a fixture. It
would have deleted 52 real people's disclosure records, and the visible
symptom would have been Ted re-sending the data notice to half his users —
the failure this file exists to prevent, caused by the tool meant to prevent
it. Anything matching neither shape cannot be a person: a real key is machine
made and neither shape can contain a space, a "probe-" or a "proof-".

Dry run by default. `--apply` writes a timestamped `.bak` beside each file
first, the same convention the nine repair scripts use, and prints what it
removed rather than a count.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Honours the same redirect conftest.py uses, so this script's own tests never
# read the live state. Resolved at call time, not import, for the same reason.
def _state_dir() -> Path:
    override = os.environ.get("TED_GATES_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".hermes" / "state"


# The two shapes `_user_state_key` can return. See the docstring: getting this
# list short is what makes the script dangerous, not what makes it useful.
_A_PERSON = (
    re.compile(r"[a-z]+:sha256:[0-9a-f]{64}"),
    re.compile(r"\d{8}_\d{6}_[0-9a-f]{8}"),
)

# Each file, and where its user keys live inside it.
_FILES = (
    ("ted-safety-gates-onboarding.json", "users"),
    ("ted-safety-gates-disclosures.json", "user_keys"),
)


def is_a_person(key: str) -> bool:
    """Whether this key could have been made by the gateway for a real user."""
    return any(shape.fullmatch(key) for shape in _A_PERSON)


def _keys(payload: dict, field: str) -> list[str]:
    held = payload.get(field)
    if isinstance(held, dict):
        return list(held)
    if isinstance(held, list):
        return [k for k in held if isinstance(k, str)]
    return []


def scan(state_dir: Path | None = None) -> dict[str, list[str]]:
    """Every fixture key in the live gate state, by file.

    A file that is absent is not a finding. A file that is present and
    unreadable is, and it raises rather than reporting clean — an unreadable
    check that returns zero findings is the failure mode the sweep was
    written around.
    """
    directory = state_dir or _state_dir()
    found: dict[str, list[str]] = {}
    for name, field in _FILES:
        path = directory / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        strays = [key for key in _keys(payload, field) if not is_a_person(key)]
        if strays:
            found[name] = strays
    return found


def remove(state_dir: Path | None = None) -> dict[str, list[str]]:
    """Back each file up, then drop the keys that cannot be a person."""
    directory = state_dir or _state_dir()
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    removed: dict[str, list[str]] = {}
    for name, field in _FILES:
        path = directory / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        keys = _keys(payload, field)
        strays = [key for key in keys if not is_a_person(key)]
        if not strays:
            continue
        path.with_name(f"{name}.bak.pre-hygiene-{stamp}").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        held = payload[field]
        if isinstance(held, dict):
            payload[field] = {k: v for k, v in held.items() if is_a_person(k)}
        else:
            payload[field] = [k for k in held if is_a_person(k)]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        removed[name] = strays
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="remove them")
    parser.add_argument("--json", action="store_true", help="for the sweep")
    args = parser.parse_args(argv)

    found = remove() if args.apply else scan()
    total = sum(len(v) for v in found.values())

    if args.json:
        print(json.dumps({"fixture_keys": total, "by_file": found}, indent=2))
        return 0

    verb = "Removed" if args.apply else "Found"
    if not total:
        print("\n  No fixture keys in the live gate state.\n")
        return 0
    print()
    for name, keys in found.items():
        print(f"  {name}")
        for key in keys:
            print(f"      {key}")
    print(f"\n  {verb} {total} key(s) that cannot belong to a person.")
    if not args.apply:
        print("  Remove them with --apply, which backs each file up first.\n")
        # Non-zero so a person at a terminal notices. The sweep reads the
        # output rather than the exit code, deliberately.
        return 1
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
