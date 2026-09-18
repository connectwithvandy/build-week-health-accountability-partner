#!/usr/bin/env python3
"""One place that knows every data repair, and whether it has been run.

Roadmap task T05: "introduce explicit schema/data migrations instead of ad-hoc
edits". There are eight repair scripts in this directory. Each one exists
because two stores hold the same fact and drifted apart, each was run by hand
once, and **nothing anywhere recorded that it had been run**.

That was survivable while the data only moved forward. It stopped being
survivable on 18 Sep 2026, when restore started working: restoring a backup
from before a repair silently undoes it, and without a record there is no way
to know which repairs the restored data still needs. A ledger that lives
anywhere but beside the data would be no use, so it lives in the gate's state
directory, which the backup now carries.

WHAT THIS IS NOT. It does not run repairs on a schedule and it does not run
them all at once. Several are one-off historical fixes tied to a specific
incident, and re-running one against data it was never meant for is exactly the
ad-hoc edit T05 is trying to end. Every run is asked for by name.

HOW "DOES THIS STILL NEED RUNNING" IS ANSWERED. Every repair script already
defaults to a dry run and needs --apply to write, so the dry run is the
question. Where a script prints an unambiguous "nothing to do", this reads it.
Where it does not, this says `read it yourself` rather than guessing, because a
migration runner that reports a clean system it cannot actually see is worse
than one that admits the gap.

    python3 scripts/ted-migrate.py             # the ledger and what is pending
    python3 scripts/ted-migrate.py --run 003   # run one, and record it
    python3 scripts/ted-migrate.py --record 003 --why "ran by hand on the VM"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
# Beside the data it describes, and inside what ted-backup.py copies, so a
# restored home arrives knowing its own history.
LEDGER = HERMES / "state" / "ted-migrations.json"
SCRIPTS = Path(__file__).resolve().parent

SYSTEM_PYTHON = sys.executable
# Anything that reads or rewrites jobs.json needs croniter, or update_job
# stores next_run_at: null and the reminder silently never fires again.
HERMES_PYTHON = str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3")


@dataclass(frozen=True)
class Migration:
    id: str
    script: str
    what: str
    store: str
    # The phrase this script prints when there is nothing outstanding. None
    # means it has no unambiguous one and the output has to be read by a
    # person. Saying so is the point; guessing would be the bug.
    clean_when: str | None = None
    interpreter: str = field(default=SYSTEM_PYTHON)
    note: str = ""


MIGRATIONS = (
    Migration(
        "001", "ted-reconcile-setup.py",
        "one definition of 'set up' for every user", "convex",
        clean_when=None,
        note="prints counts rather than a verdict; read the plan",
    ),
    Migration(
        "002", "ted-backfill-timezone.py",
        "a timezone on every check-in time", "convex",
        clean_when=None,
        note="prints how many are protected, not whether any are missing",
    ),
    Migration(
        "003", "ted-repair-language-preference.py",
        "the language each user already asked for", "gate",
        clean_when="Nothing to do.",
    ),
    Migration(
        "004", "ted-repair-missing-answers.py",
        "three answers no store kept", "gate",
        clean_when="Nothing to write.",
    ),
    Migration(
        "005", "ted-repair-swallowed-weights.py",
        "weights the 4 Sep anchoring bug swallowed", "gate",
        clean_when="nothing to repair.",
    ),
    Migration(
        "006", "ted-repair-profile-drift.py",
        "the gate's profile copy against Convex, safer answer wins", "both",
        clean_when="Nothing to repair.",
    ),
    Migration(
        "007", "ted-repair-goal-drift.py",
        "the gate's goal and calories against the user's real goal", "both",
        clean_when=None,
        note="Gourav at 1550 and Vandy at 1350 are deliberate and flag every "
             "run. This one never reads clean and that is correct.",
    ),
    Migration(
        "008", "ted-repair-ghost-jobs.py",
        "reminders switched on that will never arrive", "cron",
        clean_when="Nothing to repair.",
        interpreter=HERMES_PYTHON,
    ),
)


def load_ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"applied": {}}


def save_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def find(identifier: str) -> Migration | None:
    for migration in MIGRATIONS:
        if migration.id == identifier or migration.script.startswith(identifier):
            return migration
    return None


def dry_run(migration: Migration, timeout: float = 180.0) -> tuple[str, str]:
    """(verdict, detail) where verdict is clean, pending, or unknown.

    `unknown` is a real answer and appears whenever this cannot prove
    otherwise: no marker to look for, a script that failed, an interpreter that
    is missing. It is never rounded to clean.
    """
    script = SCRIPTS / migration.script
    if not script.exists():
        return "unknown", "the script is gone"
    if not Path(migration.interpreter).exists():
        return "unknown", f"needs {migration.interpreter}, which is not here"
    try:
        result = subprocess.run(
            [migration.interpreter, str(script)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "unknown", f"dry run did not finish in {timeout:.0f}s"
    except OSError as exc:
        return "unknown", f"could not run it: {exc}"
    if result.returncode != 0:
        first = (result.stderr or result.stdout).strip().splitlines()
        return "unknown", f"exited {result.returncode}: {first[0] if first else 'no output'}"
    if migration.clean_when is None:
        return "unknown", "no clean marker; read the dry run yourself"
    if migration.clean_when in result.stdout:
        return "clean", "nothing outstanding"
    tail = [line for line in result.stdout.strip().splitlines() if line.strip()]
    return "pending", tail[-1] if tail else "the dry run reported work"


def status(check: bool) -> int:
    ledger = load_ledger().get("applied", {})
    print(f"ledger: {LEDGER}")
    print(f"        {'travels with the backup' if LEDGER.exists() else 'not written yet'}\n")
    pending = 0
    for migration in MIGRATIONS:
        record = ledger.get(migration.id)
        when = record.get("at_readable", "never") if record else "never"
        line = f"  {migration.id}  {migration.script:<34} {migration.store:<7} last run: {when}"
        print(line)
        print(f"        {migration.what}")
        if migration.note:
            print(f"        note: {migration.note}")
        if check:
            verdict, detail = dry_run(migration)
            mark = {"clean": "clean", "pending": "PENDING", "unknown": "unknown"}[verdict]
            print(f"        {mark}: {detail}")
            if verdict == "pending":
                pending += 1
        print()
    if check:
        print(f"  {pending} migration(s) report outstanding work.")
        print("  Run one with: python3 scripts/ted-migrate.py --run <id>")
    else:
        print("  Add --check to run every dry run and see what is outstanding.")
    return 0


def run(identifier: str) -> int:
    migration = find(identifier)
    if migration is None:
        print(f"No migration {identifier!r}. Try --status.", file=sys.stderr)
        return 2
    script = SCRIPTS / migration.script
    print(f"Running {migration.script} --apply\n")
    result = subprocess.run(
        [migration.interpreter, str(script), "--apply"], text=True
    )
    if result.returncode != 0:
        print(f"\n  exited {result.returncode}. Nothing recorded.", file=sys.stderr)
        return result.returncode
    record(migration, why="run by ted-migrate.py")
    print(f"\n  Recorded {migration.id} in {LEDGER}")
    return 0


def record(migration: Migration, why: str) -> None:
    ledger = load_ledger()
    ledger.setdefault("applied", {})[migration.id] = {
        "script": migration.script,
        "what": migration.what,
        "store": migration.store,
        "at": time.time(),
        "at_readable": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "why": why,
    }
    save_ledger(ledger)


def main() -> int:
    parser = argparse.ArgumentParser(description="Every data repair, and whether it has run.")
    parser.add_argument("--check", action="store_true", help="run every dry run too")
    parser.add_argument("--run", metavar="ID", help="apply one migration and record it")
    parser.add_argument("--record", metavar="ID", help="record one as applied without running it")
    parser.add_argument("--why", default="recorded by hand", help="why, for --record")
    args = parser.parse_args()

    if args.run:
        return run(args.run)
    if args.record:
        migration = find(args.record)
        if migration is None:
            print(f"No migration {args.record!r}.", file=sys.stderr)
            return 2
        record(migration, why=args.why)
        print(f"Recorded {migration.id}: {args.why}")
        return 0
    return status(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
