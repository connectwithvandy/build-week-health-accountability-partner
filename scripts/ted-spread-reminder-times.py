#!/usr/bin/env python3
"""Move existing default nudges off the exact minute everybody shares.

    python3 scripts/ted-spread-reminder-times.py            # show what would change
    python3 scripts/ted-spread-reminder-times.py --apply    # write it
    python3 scripts/ted-spread-reminder-times.py --revert   # put them back on the menu minute

WHAT THIS IS FOR.

`REMINDER_MENU` hands every user the same four times, so everyone who picked
water is on 11:00 and 16:00 exactly. Dozens of agent runs then start in the
same second, and a run that starts before another has finished writing the
prompt cache cannot read it, so each one pays to write the whole prompt again.
Over the seven days to 17 Sep 2026: 40 such pile-ups and 3.66M duplicated
prompt tokens, about half the scheduled-reminder bill.

`_spread_default_time` in the gate fixes this at the source, so every nudge
created from now on is already spread. This is the other half: the jobs that
already exist keep their `:00` minute forever otherwise, including the 35
currently paused, which come back on their old times the moment their owner
returns.

WHAT IT WILL AND WILL NOT TOUCH.

Only a job whose firing time is *exactly* a REMINDER_MENU default for its
owner. That is checked by rebuilding the cron expression with the gate's own
`_cron_expression` and its own idea of the user's timezone, and comparing: a
job that does not match byte for byte is somebody's own time and is left alone.
It is never a minute of arithmetic done here, because a job for a London user
is stored in this laptop's time and an off-by-one timezone conversion would
move a real reminder by an hour.

The new time comes from the gate's `_spread_default_time`, given the same full
user key the gate would use. So a user who later re-picks their nudges gets the
identical minute back and `_sync_reminder_jobs` edits nothing.

Ted never says these four times out loud. `picks_gate` answers "meals, water
and supplements, done" and names no hour, so nothing anybody was told changes.
A time the user *named* reaches the schedule by another route entirely and
cannot appear here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
JOBS_FILE = Path.home() / ".hermes" / "cron" / "jobs.json"


def load_gate():
    """The gate itself, so the spread and the timezone maths have one home."""
    os.environ.setdefault("TED_GATES_DISABLE_CRON", "1")
    sys.path.insert(0, str(REPO / "hermes"))
    import ted_safety_gates as gates  # noqa: E402

    return gates


def menu_slots(gates) -> dict[str, str]:
    """reminderId -> the menu's unspread time, exactly as `picks_gate` builds them."""
    slots: dict[str, str] = {}
    for name, _, times in gates.REMINDER_MENU:
        for index, slot in enumerate(times):
            rid = name if len(times) == 1 else f"{name}_{index + 1}"
            slots[rid] = slot
    return slots


def user_keys_by_suffix(gates) -> dict[str, str]:
    """The last 12 characters of a user key -> the whole key.

    Job names carry only the suffix (`_reminder_job_name`), and the spread needs
    the whole key or it computes a different minute than the gate will.
    """
    state = gates._ONBOARDING_STATE
    return {key[-12:]: key for key in state if len(key) >= 12}


def planned_change(gates, job: dict, slots: dict[str, str], keys: dict[str, str]):
    """(old_expr, new_expr, who, reminder_id) if this job is an unspread menu
    default, else None."""
    name = str(job.get("name") or "")
    parts = name.split(":")
    if len(parts) != 3 or parts[0] != "ted":
        return None  # a free-form job, not one picks_gate made
    suffix, rid = parts[1], parts[2]
    if rid not in slots:
        return None  # daily_review, a supplement the user named, anything else
    user_key = keys.get(suffix)
    if not user_key:
        return None  # no gate record, so no way to compute the same minute

    zone = gates._user_time_zone(user_key)
    plain = gates._cron_expression(slots[rid], zone)
    if plain is None or str(job.get("schedule", {}).get("expr")) != plain:
        return None  # not sitting on the menu default — somebody moved it

    moved = gates._spread_default_time(slots[rid], user_key)
    new_expr = gates._cron_expression(moved, zone)
    if new_expr is None or new_expr == plain:
        return None
    return plain, new_expr, user_key, rid


def require_a_usable_interpreter() -> None:
    """Refuse to write a schedule this interpreter cannot compute a next run for.

    `croniter` is what `compute_next_run` uses. Without it `update_job` logs a
    line and stores `next_run_at: None`, and a job with no next run and state
    `scheduled` is simply never fired again. Nothing else reports it: the job
    still lists, still says enabled, and silently never arrives.

    That happened on 17 Sep 2026. The repo's own .venv has PyYAML but not
    croniter, so the script got far enough to write four real users' reminders
    into exactly that state and print "Updated 15 of 15".

    A missing PyYAML fails loudly at import. A missing croniter does not fail at
    all, which is why this is checked up front rather than left to be noticed.
    """
    try:
        import croniter  # noqa: F401
    except ImportError:
        raise SystemExit(
            "This interpreter has no `croniter`, so a rewritten schedule would "
            "be stored\nwith no next run and the reminder would silently never "
            "fire again.\n\nUse the Hermes runtime, which has it:\n"
            "    ~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-spread-reminder-times.py"
        )


def write_schedule(update_job, job_id: str, expr: str):
    """Move one job to `expr`, in the shape `cron.jobs.update_job` actually takes.

    It takes a job id and a dict of updates, positionally — NOT keyword
    arguments. Passing `schedule=` raised `unexpected keyword argument` fifteen
    times in a row on 17 Sep 2026, which cost nothing because the run is
    per-job and the failure is total, but it should not have reached a real run:
    `ted-pin-cron-jobs.py` had the correct call in it the whole time.

    `update_job` owns everything derived from a schedule change — it refreshes
    `schedule_display` and recomputes `next_run_at` for any job that is not
    paused — so this passes the schedule and nothing else. A paused job keeps a
    stale `next_run_at` until it is resumed, which is what resume is for.
    """
    return update_job(job_id, {"schedule": {"kind": "cron", "expr": expr, "display": expr}})


def revert_change(gates, job: dict, slots: dict[str, str], keys: dict[str, str]):
    """The same pairing read the other way: a job sitting on its *spread* time
    goes back to the menu minute.

    Deliberately the mirror of `planned_change` rather than "restore a backup".
    A backup taken before this ran also predates everything else that has
    happened to jobs.json since, and restoring it wholesale would undo those too.
    """
    parts = str(job.get("name") or "").split(":")
    if len(parts) != 3 or parts[0] != "ted" or parts[2] not in slots:
        return None
    user_key = keys.get(parts[1])
    if not user_key:
        return None
    zone = gates._user_time_zone(user_key)
    moved = gates._spread_default_time(slots[parts[2]], user_key)
    spread_expr = gates._cron_expression(moved, zone)
    plain_expr = gates._cron_expression(slots[parts[2]], zone)
    if not spread_expr or spread_expr == plain_expr:
        return None
    if str(job.get("schedule", {}).get("expr")) != spread_expr:
        return None  # not on the time we wrote, so not ours to move back
    return spread_expr, plain_expr, user_key, parts[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the change")
    parser.add_argument("--revert", action="store_true",
                        help="put the menu default back")
    args = parser.parse_args()
    if args.apply and args.revert:
        raise SystemExit("Pick one: --apply or --revert.")

    # Before anything is read, let alone written. A dry run is harmless under a
    # bad interpreter, but finding out at the --apply step means finding out
    # after somebody has already decided to trust the plan.
    require_a_usable_interpreter()

    gates = load_gate()
    sys.path.insert(0, str(HERMES_AGENT))
    try:
        from cron.jobs import load_jobs, update_job
    except ImportError as exc:
        hint = ""
        if "yaml" in str(exc):
            # The system python has no PyYAML, and Hermes' cron module needs it.
            # Worth naming: the bare error sends you looking for a Hermes
            # problem when the answer is which interpreter you started with.
            hint = (
                "\n\nThe system python has no PyYAML. Use the repo's:\n"
                "    .venv/bin/python scripts/ted-spread-reminder-times.py"
            )
        raise SystemExit(f"Could not import Hermes cron jobs from {HERMES_AGENT}: {exc}{hint}")

    slots = menu_slots(gates)
    keys = user_keys_by_suffix(gates)
    print(f"menu defaults: {slots}")
    print(f"gate knows {len(keys)} users\n")

    changes = []
    for job in load_jobs():
        decide = revert_change if args.revert else planned_change
        plan = decide(gates, job, slots, keys)
        if plan:
            old, new, user_key, rid = plan
            changes.append((job, old, new, user_key, rid))

    verb = "REVERT" if args.revert else "SPREAD"
    print(f"{len(changes)} job(s) to {verb}:")
    for job, old, new, user_key, rid in sorted(changes, key=lambda r: r[0]["name"]):
        state = "enabled" if job.get("enabled") else "paused "
        print(f"   {job['id']}  {state}  {job['name']:34} {old:16} -> {new}")

    if not changes:
        print("\nNothing to do.")
        return 0
    if not (args.apply or args.revert):
        print("\nDry run. Re-run with --apply to write it.")
        return 0
    if args.revert and not changes:
        return 0

    backup = JOBS_FILE.with_suffix(f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(JOBS_FILE, backup)
    print(f"\nBacked up jobs.json to {backup.name}")

    done = 0
    failed = 0
    for job, _old, new, _user_key, _rid in changes:
        try:
            write_schedule(update_job, job["id"], new)
            done += 1
        except Exception as exc:
            failed += 1
            print(f"   FAILED {job['id']}: {exc}")
            if failed == 1 and done == 0:
                # The first one failing means the call itself is wrong, not that
                # one job is odd. Stop rather than printing the same error once
                # per job and leaving the set half applied.
                print("   stopping after the first failure — nothing has changed")
                break
    print(f"Updated {done} of {len(changes)}.")
    print("\nNo gateway restart needed — the scheduler re-reads jobs.json.")
    if not args.revert:
        print(f"Undo: python3 {Path(__file__).name} --revert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
