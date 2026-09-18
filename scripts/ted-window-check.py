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

WHY IT READS THE LEDGER. `messages` holds what the model wrote, including text
that was never sent. Only the obligations ledger records what a person
received, and only what was received would have cost anything.

WHAT IT CANNOT KNOW. Whether Meta would approve any particular template, and
what the rates are on the day. Rates are passed in rather than hardcoded, and
the default is the published India utility rate at the time of writing.

    python3 scripts/ted-window-check.py
    python3 scripts/ted-window-check.py --days 30 --utility-rate 0.115
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"

WINDOW_SECONDS = 24 * 3600
# Rupees per delivered template, India, read 18 Sep 2026. Utility is the
# category a reminder belongs in; marketing is roughly 7.5x and Ted should
# never be in it.
DEFAULT_UTILITY_RATE = 0.115
DEFAULT_MARKETING_RATE = 0.8631


def classify(db: sqlite3.Connection, days: int) -> dict:
    """Every delivered message, split by which side of the window it fell."""
    rows = db.execute(
        "SELECT d.chat_id, d.created_at, "
        "  (SELECT d.created_at - MAX(m.timestamp) "
        "   FROM messages m JOIN sessions s ON s.id = m.session_id "
        "   WHERE s.chat_id = d.chat_id AND m.role = 'user' "
        "     AND m.timestamp <= d.created_at) AS gap "
        "FROM delivery_obligations d "
        "WHERE d.state = 'delivered' AND d.created_at >= strftime('%s','now') - ?",
        (days * 86400,),
    ).fetchall()

    free = needs_template = unknown = 0
    for _chat, _when, gap in rows:
        if gap is None:
            unknown += 1
        elif gap <= WINDOW_SECONDS:
            free += 1
        else:
            needs_template += 1
    return {
        "delivered": len(rows),
        "free": free,
        "needs_template": needs_template,
        "unknown": unknown,
        "days": days,
    }


def report(counts: dict, utility: float, marketing: float) -> int:
    total = counts["delivered"]
    if not total:
        print("Nothing was delivered in this window, so there is nothing to price.")
        return 0

    days = counts["days"] or 1
    per_month = counts["needs_template"] / days * 30
    print(f"{total} message(s) delivered in the last {days} days\n")
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
            "  Nothing Ted currently sends would need a template, because he\n"
            "  only ever answers. That makes the migration cheap and it is not\n"
            "  good news: the reminders are the half of the product that would\n"
            "  need templates, and they are not going out."
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
