#!/usr/bin/env python3
"""Find reminders that are switched on and will never arrive, and restart them.

    ~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-repair-ghost-jobs.py
    ~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-repair-ghost-jobs.py --apply

WHAT A GHOST JOB IS.

A cron job with `enabled: true`, `state: "scheduled"` and `next_run_at: null`.
The scheduler fires jobs by their next run, so a job without one is never
picked up. Everything else about it looks healthy: it lists, it says enabled,
`hermes cron list` shows it, and the user is told their reminder is set. It
simply never arrives, and nothing anywhere says so.

HOW ONE GETS MADE.

`compute_next_run` needs `croniter`. Where it is missing, `update_job` logs one
line to stderr and stores `next_run_at: None` anyway. So any tool that edits a
schedule from an interpreter without croniter silently converts a working
reminder into a ghost.

That is not hypothetical. On 17 Sep 2026 `ted-spread-reminder-times.py` was run
under the repo's own .venv, which has PyYAML but not croniter, and turned four
of one user's reminders — meals, water twice and movement — into ghosts while
printing "Updated 15 of 15". Hermes carries a guard against this for one-shot
jobs (#59395) and none for recurring ones.

WHY THIS IS A SEPARATE SCRIPT.

The spread script now refuses to run without croniter, which stops new ghosts.
It cannot see the ones already made: once a job is on its new expression it is
no longer "sitting on a menu default" and no longer selected. And the cause is
not specific to that script — anything calling `update_job` on a schedule can
do it. So the check belongs where it can find a ghost whatever made it.

Re-running is safe and idempotent: a job that already has a next run is left
alone, and the repair only ever recomputes from the expression already stored.
It changes no times, no prompts and no recipients.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
JOBS_FILE = Path.home() / ".hermes" / "cron" / "jobs.json"


def is_ghost(job: dict) -> bool:
    """Switched on, not paused, and with nothing telling the scheduler when.

    `state` is checked as well as `enabled` because a paused job legitimately
    keeps a stale next run until it is resumed; resuming is what recomputes it.
    """
    if not job.get("enabled"):
        return False
    if job.get("state") == "paused":
        return False
    return not job.get("next_run_at")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the repair")
    args = parser.parse_args()

    try:
        import croniter  # noqa: F401
    except ImportError:
        raise SystemExit(
            "This interpreter has no `croniter`, so it cannot compute the next "
            "run it is\nhere to restore — it would rewrite each ghost as a "
            "ghost.\n\nUse the Hermes runtime:\n"
            "    ~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-repair-ghost-jobs.py"
        )

    sys.path.insert(0, str(HERMES_AGENT))
    try:
        from cron.jobs import load_jobs, update_job, compute_next_run
    except ImportError as exc:
        raise SystemExit(f"Could not import Hermes cron jobs from {HERMES_AGENT}: {exc}")

    jobs = load_jobs()
    ghosts = [job for job in jobs if is_ghost(job)]
    print(f"{len(jobs)} jobs, {len(ghosts)} switched on with no next run:\n")
    for job in ghosts:
        expr = job.get("schedule", {}).get("expr")
        would = compute_next_run(job.get("schedule"))
        print(f"   {job['id']}  {str(job.get('name'))[:38]:40} {str(expr):14} -> {would}")
        if would is None:
            print("        cannot be computed from that expression — not repairable here")

    repairable = [j for j in ghosts if compute_next_run(j.get("schedule")) is not None]
    if not repairable:
        print("\nNothing to repair.")
        return 0
    if not args.apply:
        print(f"\n{len(repairable)} repairable. Dry run — re-run with --apply.")
        return 0

    backup = JOBS_FILE.with_suffix(f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(JOBS_FILE, backup)
    print(f"\nBacked up jobs.json to {backup.name}")

    done = 0
    for job in repairable:
        try:
            # Re-sending the schedule it already has is what makes update_job
            # recompute the next run. Nothing about the reminder changes.
            update_job(job["id"], {"schedule": job["schedule"]})
            done += 1
        except Exception as exc:
            print(f"   FAILED {job['id']}: {exc}")
            if done == 0:
                print("   stopping after the first failure — nothing has changed")
                break
    print(f"Repaired {done} of {len(repairable)}.")

    # Read back rather than trust the return. The whole failure this repairs is
    # a write that reported success and stored nothing usable.
    still = [j for j in load_jobs() if is_ghost(j)]
    if still:
        print(f"\nSTILL GHOSTS: {len(still)} — {[j['id'] for j in still]}")
        return 1
    print("Every switched-on job now has a next run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
