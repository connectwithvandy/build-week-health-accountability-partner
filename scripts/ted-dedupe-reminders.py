#!/usr/bin/env python3
"""
Remove reminder jobs that duplicate another job for the same person.

    python3 scripts/ted-dedupe-reminders.py
    python3 scripts/ted-dedupe-reminders.py --apply

WHY THERE ARE DUPLICATES. `reminders.items` in convex/schema.ts stores a
`localTime` and nothing about which days. So a supplement taken on Mondays and
Wednesdays, or on the 17th of the month, cannot be written down: the only thing
the app can create is a daily job. When the owner asked for her supplements back
on 7 Sep 2026 at 11:03, Ted rebuilt five of them from that row and every one
came back daily, next to the originals which were already there on the right
days. CoQ10 went from weekdays to daily, B12 from Mon+Wed to daily, iron from
Tue+Thu to daily, and vitamin D from the 17th of the month to daily.

The result was ten scheduled messages on a Monday, five of them at 10:30, into a
`maxPerDay` of 3 that silently dropped the rest. That is the "Double reminder
Fix this" she sent at 09:05 the same morning.

WHAT COUNTS AS A DUPLICATE HERE. Two jobs for the same chat that nudge about the
same thing, where one is strictly worse: it fires on days the other does not, or
it carries a generic prompt where the other names the actual dose. The better
one is kept. A job with no counterpart is never touched, however odd its
schedule looks, because that is somebody's real preference.

Also removed:

  * a daily review that duplicates another daily review for the same chat, the
    one matching the user's stored `dailyReviewTime` being the one kept
  * a job whose delivery target is the literal string "owner", which cannot
    resolve to a WhatsApp address and has failed on every run since it was made

THE REAL FIX, which this is not. Until reminder items can carry the days they
apply to, the app can only ever create daily jobs, and this will happen again
the next time anybody asks for their reminders to be rebuilt. That is a schema
change and it is written up in PROGRESS.md.

Dry run by default. Deletions go through `hermes cron remove` so the running
scheduler notices, rather than by editing jobs.json underneath it.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CRON_JOBS = Path.home() / ".hermes" / "cron" / "jobs.json"

# The supplement each job is about, however it happens to be named.
SUPPLEMENTS = {
    "coq10": "coq10",
    "omega3": "omega3", "omega 3": "omega3", "omega-3": "omega3",
    "b12": "b12", "vitamin_b12": "b12", "vitamin b12": "b12",
    "iron": "iron", "chelated_iron": "iron", "chelated iron": "iron",
    "vitamin_d": "vitamin_d", "vitamin d": "vitamin_d", "vitd": "vitamin_d",
}


def load_jobs() -> list[dict]:
    def walk(node):
        if isinstance(node, dict):
            if "schedule" in node and "prompt" in node:
                yield node
                return
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
    return list(walk(json.loads(CRON_JOBS.read_text(encoding="utf-8"))))


def target(job: dict) -> str:
    deliver = str(job.get("deliver") or "")
    if deliver.startswith("whatsapp:"):
        return deliver.split(":", 1)[1]
    return str((job.get("origin") or {}).get("chat_id") or deliver)


def subject(job: dict) -> str | None:
    """Which supplement, from the name first and the prompt as a fallback."""
    haystack = f"{job.get('name') or ''} {job.get('prompt') or ''}".lower()
    for needle, canonical in SUPPLEMENTS.items():
        if needle in haystack:
            return canonical
    return None


def is_review(job: dict) -> bool:
    text = f"{job.get('name') or ''} {job.get('prompt') or ''}".lower()
    return "daily_review" in text or "day_summary" in text or "how their day went" in text


def days_covered(expr: str) -> int:
    """How many days a year this fires, roughly. Fewer is more specific."""
    parts = expr.split()
    if len(parts) < 5:
        return 365
    if parts[2] != "*":
        return 12  # a day of the month
    dow = parts[4]
    if dow == "*":
        return 365
    count = 0
    for chunk in dow.split(","):
        if "-" in chunk:
            a, b = chunk.split("-")
            count += int(b) - int(a) + 1
        else:
            count += 1
    return count * 52


def names_a_dose(job: dict) -> bool:
    """A prompt that carries mg/mcg/IU is telling the user something the
    generic one cannot."""
    return bool(re.search(r"\d+\s*(mg|mcg|iu)\b", str(job.get("prompt") or ""), re.I))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--chat", help="limit to one chat id")
    args = parser.parse_args()

    jobs = load_jobs()
    doomed: list[tuple[dict, str]] = []

    by_chat: dict[str, list[dict]] = defaultdict(list)
    for job in jobs:
        by_chat[target(job)].append(job)

    for chat, chat_jobs in by_chat.items():
        if args.chat and chat != args.chat:
            continue

        # A target that is not a real address. "owner" is a literal that was
        # never substituted; it has failed on every run it has ever had.
        for job in chat_jobs:
            deliver = str(job.get("deliver") or "")
            if "owner@" in deliver:
                doomed.append((job, "delivery target is the literal string \"owner\", never resolves"))

        # Supplements: keep the most specific schedule, and prefer the prompt
        # that names a dose.
        groups: dict[str, list[dict]] = defaultdict(list)
        for job in chat_jobs:
            name = subject(job)
            if name and not is_review(job):
                groups[name].append(job)
        for name, group in groups.items():
            if len(group) < 2:
                continue
            best = sorted(
                group,
                key=lambda j: (
                    days_covered(str((j.get("schedule") or {}).get("expr") or "")),
                    0 if names_a_dose(j) else 1,
                ),
            )[0]
            for job in group:
                if job is best:
                    continue
                doomed.append((
                    job,
                    f"duplicate {name}: '{best.get('name')}' fires on fewer days"
                    + (" and names the dose" if names_a_dose(best) and not names_a_dose(job) else ""),
                ))

        # Daily reviews: one per chat.
        reviews = [j for j in chat_jobs if is_review(j) and "owner@" not in str(j.get("deliver") or "")]
        if len(reviews) > 1:
            # Keep the one the app manages, which is the one that follows the
            # stored dailyReviewTime when the user changes it.
            keep = sorted(reviews, key=lambda j: 0 if str(j.get("name") or "").startswith("ted:") else 1)[0]
            for job in reviews:
                if job is not keep:
                    doomed.append((job, f"second daily review; '{keep.get('name')}' is the one the app updates"))

    seen, unique = set(), []
    for job, why in doomed:
        if job.get("id") in seen:
            continue
        seen.add(job["id"])
        unique.append((job, why))

    mode = "APPLY" if args.apply else "DRY RUN — nothing is removed"
    print("=" * 92)
    print(f"REMINDER DEDUPE   {datetime.now():%d %b %Y %H:%M}   {mode}")
    print("=" * 92)
    if not unique:
        print("\nNo duplicates found.")
        return 0

    print(f"\nWOULD REMOVE {len(unique)}:")
    for job, why in unique:
        expr = str((job.get("schedule") or {}).get("expr") or "")
        print(f"  {str(job.get('id')):<14}{str(job.get('name'))[:40]:<42}{expr:<18}{why}")

    kept = [j for j in jobs if j.get("id") not in seen]
    print(f"\nWOULD KEEP {len(kept)} of {len(jobs)}:")
    for job in sorted(kept, key=lambda j: str(j.get("name"))):
        if args.chat and target(job) != args.chat:
            continue
        expr = str((job.get("schedule") or {}).get("expr") or "")
        print(f"  {str(job.get('name'))[:44]:<46}{expr}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to remove them.")
        return 0

    backup = CRON_JOBS.with_suffix(f".json.bak.pre-dedupe-{datetime.now():%Y%m%dT%H%M%S}")
    shutil.copy2(CRON_JOBS, backup)
    print(f"\nbacked up to {backup.name}")

    for job, _ in unique:
        result = subprocess.run(
            ["hermes", "cron", "remove", str(job["id"])],
            capture_output=True, text=True,
        )
        ok = result.returncode == 0
        print(f"  {'removed ' if ok else 'FAILED  '}{str(job.get('name'))[:44]}"
              + ("" if ok else f"  {result.stderr.strip()[:70]}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
