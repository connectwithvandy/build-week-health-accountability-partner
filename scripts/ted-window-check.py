#!/usr/bin/env python3
"""What a move to the official WhatsApp API would cost, from real traffic.

Roadmap task T06. The official WhatsApp Business Platform divides everything
Ted says into two kinds, and the difference is the whole migration question:

  inside the 24-hour customer service window
      Anything, in Ted's own words, free. The window opens each time the user
      messages and stays open 24 hours.

  outside it
      A pre-approved template only. Fixed text with variable slots, submitted
      to Meta in advance, charged per delivered message. No improvising, and
      no "arre, you skipped yesterday yaar, what's the plan?" unless that exact
      sentence was approved weeks earlier.

So the cost of migrating is not a quote from a vendor. It is a property of how
Ted actually talks to people, and it is sitting in `delivery_obligations`. This
counts it.

WHERE IT READS FROM, AND THE MISTAKE THAT TAUGHT IT. `messages` holds what the
model wrote, including text that was never sent, so it is the wrong source.
The first version of this file read `delivery_obligations` alone and reported
that **100%** of Ted's traffic fell inside the free window.

That was wrong, and wrong in the direction that makes a migration look free.
**A scheduled reminder never touches the obligations ledger.** The cron
scheduler hands it to the adapter directly and writes one line to the log:

    Job '6e77ad1b48ab': delivered to whatsapp:115650651500637@lid via live adapter

Ted had been sending seven to twenty-one of those a day, every day, and this
file could not see any of them — which is precisely the traffic that would
need templates. Both sources are read now: the ledger for replies, the log for
reminders.

WHAT IT CANNOT KNOW. Whether Meta would approve any particular template, and
what the rates are on the day. Rates are passed in rather than hardcoded, and
the default is the published India utility rate at the time of writing.

    python3 scripts/ted-window-check.py
    python3 scripts/ted-window-check.py --days 30 --utility-rate 0.115
"""

from __future__ import annotations

import argparse
import bisect
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"

WINDOW_SECONDS = 24 * 3600
# Rupees per delivered template, India, read 18 Sep 2026. Utility is the
# category a reminder belongs in; marketing is roughly 7.5x and Ted should
# never be in it.
DEFAULT_UTILITY_RATE = 0.115
DEFAULT_MARKETING_RATE = 0.8631

LOG_DIR = HERMES / "logs"
# `cron.scheduler: Job 'x': delivered to whatsapp:<chat> via live adapter`.
# Rotation matters: agent.log holds days, agent.log.1 holds the weeks before.
_CRON_SENT = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*delivered to whatsapp:(\S+?) via"
)


def inbound_times(db: sqlite3.Connection) -> dict[str, list[float]]:
    """When each chat last wrote, sorted, so a window can be asked about."""
    times: dict[str, list[float]] = {}
    for chat, when in db.execute(
        "SELECT s.chat_id, m.timestamp FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE m.role = 'user' AND s.chat_id IS NOT NULL AND s.chat_id != ''"
    ):
        times.setdefault(chat, []).append(when)
    for series in times.values():
        series.sort()
    return times


def chat_deliveries(db: sqlite3.Connection, since: float) -> list[tuple[float, str]]:
    """Replies, from the obligations ledger."""
    return [
        (when, chat)
        for chat, when in db.execute(
            "SELECT chat_id, created_at FROM delivery_obligations "
            "WHERE state = 'delivered' AND created_at >= ?",
            (since,),
        )
    ]


def cron_deliveries(since: float) -> list[tuple[float, str]]:
    """Reminders, from the scheduler's own log line.

    There is no ledger for these. The only record that a reminder reached
    somebody is a line in agent.log, so that is what gets read.
    """
    sent: list[tuple[float, str]] = []
    for name in ("agent.log.1", "agent.log"):
        path = LOG_DIR / name
        if not path.exists():
            continue
        try:
            with path.open(errors="replace") as handle:
                for line in handle:
                    found = _CRON_SENT.match(line)
                    if not found:
                        continue
                    when = datetime.strptime(
                        found.group(1), "%Y-%m-%d %H:%M:%S"
                    ).timestamp()
                    if when >= since:
                        sent.append((when, found.group(2)))
        except OSError:
            continue
    return sent


def side_of_window(when: float, times: list[float] | None) -> str:
    """"free", "template" or "unknown" for one delivered message."""
    if not times:
        return "unknown"
    index = bisect.bisect_right(times, when)
    if index == 0:
        return "unknown"
    return "free" if when - times[index - 1] <= WINDOW_SECONDS else "template"


def classify(db: sqlite3.Connection, days: int) -> dict:
    """Every delivered message, both kinds, split by side of the window."""
    since = datetime.now().timestamp() - days * 86400
    times = inbound_times(db)
    counts = {
        "days": days,
        "reply": {"free": 0, "template": 0, "unknown": 0},
        "reminder": {"free": 0, "template": 0, "unknown": 0},
    }
    for kind, rows in (
        ("reply", chat_deliveries(db, since)),
        ("reminder", cron_deliveries(since)),
    ):
        for when, chat in rows:
            counts[kind][side_of_window(when, times.get(chat))] += 1
    totals = {
        key: counts["reply"][key] + counts["reminder"][key]
        for key in ("free", "template", "unknown")
    }
    counts["free"] = totals["free"]
    counts["needs_template"] = totals["template"]
    counts["unknown"] = totals["unknown"]
    counts["delivered"] = sum(totals.values())
    return counts


def report(counts: dict, utility: float, marketing: float) -> int:
    total = counts["delivered"]
    if not total:
        print("Nothing was delivered in this window, so there is nothing to price.")
        return 0

    days = counts["days"] or 1
    per_month = counts["needs_template"] / days * 30
    print(f"{total} message(s) delivered in the last {days} days\n")
    for kind, label in (("reply", "replies to a person"), ("reminder", "scheduled reminders")):
        part = counts[kind]
        n = sum(part.values())
        if n:
            print(f"  {label:<22} {n:>5}   {part['template']} outside the window")
    print()
    print(f"  inside the 24h window, free      {counts['free']:>5}"
          f"   {counts['free'] / total * 100:.1f}%")
    print(f"  outside it, needs a template     {counts['needs_template']:>5}"
          f"   {counts['needs_template'] / total * 100:.1f}%")
    if counts["unknown"]:
        print(f"  no inbound on record             {counts['unknown']:>5}"
              "   cannot tell, counted as neither")
    print()
    print(f"  At ₹{utility:.3f} per utility template, that is about "
          f"₹{per_month * utility:.0f} a month.")
    print(f"  In the marketing category it would be ₹{per_month * marketing:.0f}, "
          f"which is\n  the reason a reminder must never be filed as marketing.")
    print()
    if counts["needs_template"] == 0:
        print(
            "  Nothing Ted sent in this window would need a template. Check the\n"
            "  reminder count above before believing that: if it is zero, this\n"
            "  is reading the wrong thing, not finding good news."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="T06, priced from real traffic.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--utility-rate", type=float, default=DEFAULT_UTILITY_RATE)
    parser.add_argument("--marketing-rate", type=float, default=DEFAULT_MARKETING_RATE)
    args = parser.parse_args()

    if not STATE_DB.exists():
        raise SystemExit(f"No database at {STATE_DB}.")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        return report(classify(db, args.days), args.utility_rate, args.marketing_rate)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
