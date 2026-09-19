"""Keep the failed-call count after the log that held it is gone.

T12's one stated gap. `docs/T12_BASELINE.md` §3 opens with it:

    The error rate has no durable source. A failed API call is retried and
    the retry succeeds, so nothing in the database records that it happened.
    The number comes from `agent.log`, which rotates.

A retried-and-succeeded call is invisible everywhere else by design — that is
what a successful retry means — so the log line is the only evidence that Ted
nearly failed. `npm run baseline` reads it and says so when the log does not
reach the start of its window, which was the honest thing to do about a
column that quietly reads low.

WHY NOW. `ai.ted.logs` began pruning rotated logs at 30 days on 19 Sep 2026.
That is the right retention rule and it turns "the log might have rotated"
into "the evidence is deleted on a schedule". Adding the timer without
keeping the number would have made a stated gap into a widening one.

WHY NOT A NEW TIMER. The roll-up runs inside `ted-log-retention.py`, before
it prunes. The thing that destroys the evidence is the right thing to
preserve the summary first: they cannot drift apart, and there is no fourth
job to install, forget, or find un-loaded three days later.

WHAT IS KEPT, AND WHAT IS DELIBERATELY NOT. A date and a count. Not the line,
not the model, not the session, not the error text — a failure line can carry
a prompt fragment, and `docs/T35` exists because logs turned out to be a
second health store. A count per day is what the baseline actually reads.

THE COUNT ONLY EVER GOES UP. Re-reading a log that has since rotated finds
fewer lines for the same day, and writing that back would quietly revise
history downward — the column would keep reading low, just from a file that
looks authoritative instead of from one that admits it rotates. So a day
already recorded keeps the larger number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# The same line the baseline counts. Kept here and imported there, so the two
# can never come to disagree about what a failure is.
FAILURE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2},\d+ .*API call failed")

# Oldest first: a day appearing in both files is counted from whichever holds
# more of it, which `_merge` settles.
LOG_NAMES = ("agent.log.1", "agent.log")


def scan(logs_dir: Path) -> dict[str, int]:
    """Failed calls per day, from whatever the logs still hold."""
    counts: dict[str, int] = {}
    for name in LOG_NAMES:
        path = logs_dir / name
        if not path.is_file():
            continue
        seen: dict[str, int] = {}
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            match = FAILURE.match(line)
            if match:
                seen[match.group(1)] = seen.get(match.group(1), 0) + 1
        counts = _merge(counts, seen)
    return counts


def _merge(kept: dict[str, int], seen: dict[str, int]) -> dict[str, int]:
    """Day by day, the larger count wins. See the docstring."""
    merged = dict(kept)
    for day, count in seen.items():
        merged[day] = max(merged.get(day, 0), count)
    return merged


def read(ledger_path: Path) -> dict[str, int]:
    """What has been recorded so far, or nothing."""
    if not ledger_path.is_file():
        return {}
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # An unreadable ledger is not zero failures. Returning {} here lets
        # the caller fall back to the live log, which is the same answer it
        # had before this file existed.
        return {}
    days = payload.get("days")
    if not isinstance(days, dict):
        return {}
    return {
        str(day): int(count)
        for day, count in days.items()
        if isinstance(count, int) or (isinstance(count, float) and count.is_integer())
    }


def update(logs_dir: Path, ledger_path: Path) -> dict[str, Any]:
    """Fold today's readable log into the ledger. Returns what changed."""
    before = read(ledger_path)
    after = _merge(before, scan(logs_dir))

    added = sorted(day for day in after if day not in before)
    raised = sorted(
        day for day in after if day in before and after[day] > before[day]
    )

    if after != before:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = ledger_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"days": dict(sorted(after.items()))}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(ledger_path)

    return {"days": after, "new_days": added, "raised_days": raised}
