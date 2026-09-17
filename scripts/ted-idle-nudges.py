#!/usr/bin/env python3
"""Stop paying to write reminders the gate is already throwing away.

    python3 scripts/ted-idle-nudges.py            # show what would change
    python3 scripts/ted-idle-nudges.py --apply    # write it
    python3 scripts/ted-idle-nudges.py --install  # run it hourly, unattended

Needs an interpreter with PyYAML, because Hermes' cron module imports it. The
system python does not have one:

    ~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-idle-nudges.py

WHAT THIS IS FOR.

Ted decides whether a reminder may go out *after* the model has written it.
`_cron_reminder_gate` runs on the `transform_llm_output` hook, and Hermes has
no hook that can cancel a turn before the LLM call — `pre_llm_call` can only
inject context, and only `pre_tool_call` can block anything, and only a tool.
So a blocked reminder costs a full model turn and delivers nothing.

On 17 Sep 2026 that was 235 of 327 cron runs: 71% of scheduled firings
produced no message at all. At ~41,000 prompt tokens a firing, most of the
Anthropic bill was Ted writing nudges into the bin.

The largest single reason is the break offer working exactly as designed.
`NUDGES_BEFORE_BREAK_OFFER` is 4; after four unanswered nudges Ted asks "want
me to pause?", and an unanswered offer sets `awaitingBreakReply`, which makes
`gateReminderDelivery` return `allowed: false` for every send from then on.
Twelve users sit in that state. Nobody told the scheduler, so their 34 jobs
keep firing into a gate that has already said no.

WHY PAUSING IS SAFE HERE, AND ONLY HERE.

The only jobs this touches are ones whose every send is already refused. The
users concerned receive nothing today and receive nothing after. Their
experience does not change by one message; the bill does.

That is why the condition is the gate's own state and not "looks inactive".
Guessing at engagement would be a product decision. This is bookkeeping:
the scheduler is being told what the gate already knows.

COMING BACK.

A paused user who messages Ted resets `unansweredNudges` and clears
`awaitingBreakReply`, and the next run of this script resumes their jobs. That
is why it reconciles in both directions rather than only pausing, and why it
is safe to run on a schedule. It resumes only jobs carrying its own
`paused_reason`, so a job somebody paused by hand stays paused.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
JOBS_FILE = Path.home() / ".hermes" / "cron" / "jobs.json"
DEPLOYMENT = "hardy-scorpion-901"

# The tag that makes a resume safe. Only jobs whose `paused_reason` starts
# with this are ever resumed, so a hand-paused job is never woken by accident.
PAUSE_TAG = "ted-idle-nudges"

LABEL = "ai.ted.idle-nudges"
PLIST_SRC = REPO / "scripts" / f"{LABEL}.plist"
PLIST_DST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install() -> int:
    """Copy the plist in and load it. Idempotent, so re-running is safe.

    This exists because the same job was left half done once already: the
    gatewatch plist sat in `scripts/` for days without being copied into
    ~/Library/LaunchAgents, so a watcher that looked finished had never run. A
    reconciler nobody runs is the same as no reconciler, and the whole point of
    this one is that a returning user gets their reminders back without anybody
    remembering to do it.

    Mirrors `install()` in ted-watch.py deliberately, including the read-back
    from `launchctl list`: a load that silently fails leaves you believing a
    timer exists when it does not.
    """
    try:
        plistlib.loads(PLIST_SRC.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"refusing to install a plist that does not parse: {exc}", file=sys.stderr)
        return 1
    PLIST_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLIST_SRC, PLIST_DST)
    subprocess.run(["launchctl", "unload", str(PLIST_DST)], capture_output=True)
    done = subprocess.run(["launchctl", "load", str(PLIST_DST)], capture_output=True, text=True)
    if done.returncode != 0:
        print(f"launchctl load failed: {(done.stdout + done.stderr).strip()}", file=sys.stderr)
        return 1
    listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if LABEL not in listed.stdout:
        print(f"{LABEL} did not appear in launchctl list", file=sys.stderr)
        return 1
    print(f"installed and loaded {LABEL} -> {PLIST_DST}")
    print("Runs hourly. First run is in an hour, not now: installing a timer "
          "should not\nrewrite real schedules as a side effect.")
    print(f"Undo: launchctl unload {PLIST_DST} && rm {PLIST_DST}")
    return 0


def convex_rows(table: str) -> list[dict]:
    """Read a table, read-only, the same way the other repair scripts do."""
    done = subprocess.run(
        ["npx", "convex", "data", table, "--deployment", DEPLOYMENT,
         "--limit", "16000", "--format", "jsonl"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if done.returncode != 0:
        raise SystemExit(f"Could not read {table} from Convex:\n{done.stderr.strip()}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def chat_id_of(job: dict) -> str:
    """The WhatsApp thread this job delivers into, however it was created."""
    deliver = job.get("deliver") or ""
    if isinstance(deliver, str) and deliver.startswith("whatsapp:"):
        return deliver.split(":", 1)[1]
    origin = job.get("origin") or {}
    return str(origin.get("chat_id") or "")


def gate_blocks_every_send(policy: dict, now_ms: float) -> str:
    """Why `gateReminderDelivery` refuses this user right now, or ''.

    Mirrors the two checks in `remindersAllowed` that hold regardless of the
    hour, the daily cap, or which kind of reminder is asking. A cap or a quiet
    hour is a *this send* refusal and jobs must keep their schedule for those.
    These two are standing refusals, which is what makes them schedulable.
    """
    if policy.get("awaitingBreakReply") is True:
        return "awaitingBreakReply"
    paused_until = policy.get("pausedUntil")
    if isinstance(paused_until, (int, float)) and paused_until > now_ms:
        when = datetime.fromtimestamp(paused_until / 1000, timezone.utc).date()
        return f"pausedUntil:{when.isoformat()}"
    return ""


# How many jobs one unattended run may touch before it stops and asks.
#
# Running on a timer is what makes the resume real, and it is also what makes a
# mistake unattended. The failure that matters is pausing everybody: a bad read
# of `reminders`, or a schema change to `awaitingBreakReply`, would look exactly
# like every user going quiet at once.
#
# The read already fails safe — an unreachable Convex leaves `policy_by_key`
# empty, every job lands in `unresolved`, and nothing is paused — so this covers
# the other shape, where the data arrives and is wrong. Under an hourly timer a
# real delta is nought to a handful; twelve is two full users' worth of jobs
# changing at once. Above that a human should look, so it refuses rather than
# acting and reports what it would have done.
MAX_UNATTENDED_CHANGES = 12


def too_many_changes(total: int, limit: int) -> bool:
    """Whether one run is touching more than a human agreed to leave it alone for.

    `limit` of 0 means no limit, which is how somebody says "yes, that backlog
    is real" after reading the list.
    """
    return bool(limit) and total > limit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the change (default is a dry run)")
    parser.add_argument("--install", action="store_true",
                        help="load the launchd timer that runs this hourly, then exit")
    parser.add_argument(
        "--max-changes", type=int, default=MAX_UNATTENDED_CHANGES,
        help=f"refuse to apply more than this many changes at once "
             f"(default {MAX_UNATTENDED_CHANGES}; 0 means no limit)",
    )
    args = parser.parse_args()

    if args.install:
        return install()

    sys.path.insert(0, str(HERMES_AGENT))
    try:
        from cron.jobs import load_jobs, pause_job, resume_job
    except ImportError as exc:
        raise SystemExit(f"Could not import Hermes cron jobs from {HERMES_AGENT}: {exc}")

    sys.path.insert(0, str(REPO / "hermes"))
    try:
        import ted_safety_gates as gates
    except ImportError as exc:
        raise SystemExit(f"Could not import the Ted safety gates: {exc}")

    users = {u["_id"]: u for u in convex_rows("users")}
    # The gate's key and Convex's `whatsappUserId` are the same string. Built
    # with the gate's own function rather than rebuilt here, so a change to how
    # users are identified can never leave this script pausing the wrong
    # person's reminders.
    policy_by_key: dict[str, dict] = {}
    for row in convex_rows("reminders"):
        owner = users.get(row.get("userId"))
        if owner and owner.get("whatsappUserId"):
            policy_by_key[owner["whatsappUserId"]] = row
    name_by_key = {
        u["whatsappUserId"]: (u.get("name") or "(no name)")
        for u in users.values() if u.get("whatsappUserId")
    }

    now_ms = time.time() * 1000
    to_pause: list[tuple[dict, str, str]] = []
    to_resume: list[tuple[dict, str]] = []
    unresolved: list[dict] = []

    for job in load_jobs():
        chat_id = chat_id_of(job)
        if not chat_id:
            unresolved.append(job)
            continue
        key = gates._user_state_key("whatsapp", chat_id, "")
        policy = policy_by_key.get(key)
        who = name_by_key.get(key, "(unknown)")
        if policy is None:
            unresolved.append(job)
            continue
        blocked = gate_blocks_every_send(policy, now_ms)
        paused_by_us = str(job.get("paused_reason") or "").startswith(PAUSE_TAG)
        if blocked and job.get("enabled") and not paused_by_us:
            to_pause.append((job, who, blocked))
        elif not blocked and paused_by_us:
            to_resume.append((job, who))

    print(f"{len(to_pause)} job(s) to PAUSE — the gate already refuses every send:")
    for job, who, why in sorted(to_pause, key=lambda r: r[1]):
        print(f"   {job['id']}  {who:18} {str(job.get('name'))[:38]:40} {why}")
    print(f"\n{len(to_resume)} job(s) to RESUME — the user is back and the gate allows sends:")
    for job, who in sorted(to_resume, key=lambda r: r[1]):
        print(f"   {job['id']}  {who:18} {str(job.get('name'))[:38]}")
    if unresolved:
        print(f"\n{len(unresolved)} job(s) left alone — no reminder policy to read:")
        for job in unresolved:
            print(f"   {job['id']}  {str(job.get('name'))[:44]}")

    if not to_pause and not to_resume:
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write it.")
        return 0

    total = len(to_pause) + len(to_resume)
    if too_many_changes(total, args.max_changes):
        print(
            f"\nREFUSING: {total} changes in one run, limit {args.max_changes}.\n"
            "Nothing was written. This many at once is either a real backlog or\n"
            "a bad read of the reminders table, and the two look identical from\n"
            "here. Check the list above, then re-run with --max-changes 0 if it\n"
            "is right."
        )
        return 1

    backup = JOBS_FILE.with_suffix(f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(JOBS_FILE, backup)
    print(f"\nBacked up jobs.json to {backup.name}")

    stamp = datetime.now(timezone.utc).date().isoformat()
    paused = resumed = 0
    for job, who, why in to_pause:
        try:
            pause_job(job["id"], f"{PAUSE_TAG}: {why} as of {stamp}")
            paused += 1
        except Exception as exc:
            print(f"   FAILED to pause {job['id']}: {exc}")
    for job, who in to_resume:
        try:
            resume_job(job["id"])
            resumed += 1
        except Exception as exc:
            print(f"   FAILED to resume {job['id']}: {exc}")
    print(f"Paused {paused}, resumed {resumed}.")
    print("\nNo gateway restart needed — the scheduler re-reads jobs.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
