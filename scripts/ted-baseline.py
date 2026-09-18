#!/usr/bin/env python3
"""Why a day was slow, expensive or broken, without reading anybody's chat.

Roadmap task T12. Its definition of done is a sentence about what a baseline
must be able to answer:

    At least one week/day baseline can answer why a request was
    slow/expensive/failed without reading the user's chat content.

Everything here comes from four sources that already exist. Nothing new is
recorded, because the recording was never the gap — Hermes has written all of
this down since the first day. What was missing is anybody reading it back in
one place, which is why "is Ted slow?" and "why did yesterday cost that?" have
been answered by opening a provider console by hand.

WHERE EACH NUMBER COMES FROM, so a wrong one can be chased:

  messages, latency   `messages` in state.db. Latency pairs each assistant row
                      with the user row before it by row id. Row id is
                      processing order and `timestamp` is arrival, so the
                      difference is how long that person waited. Pairing by id
                      rather than by time is deliberate: when somebody types
                      while Ted is composing, their message is persisted after
                      the reply and carries an earlier arrival time. Pairing by
                      time would read that as a negative wait. See
                      `docs/T08_ORDERING.md`.

  tokens, cost,       `session_model_usage`, one row per session and model.
  fallback rate       Input is counted as input + cache read + cache write,
                      because the three are separate columns and the first
                      alone is a sixth of the truth: 441 calls on the primary
                      model show 882 input tokens and 1.2M cache reads.

  delivery rate       `delivery_obligations`. Since Hermes patch 16 this holds
                      scheduled reminders as well as replies, so a delivery
                      rate here finally means all of Ted's outbound rather
                      than the 45% of it that replies represent.

  error rate          `agent.log`. The one number not in the database: a
                      failed API call is retried and the retry succeeds, so
                      nothing durable records that it happened. The log is
                      therefore load-bearing here and it rotates, which is
                      stated rather than worked around.

NO MESSAGE CONTENT IS READ OR PRINTED. Not as a precaution — as the point. A
baseline you cannot run without opening somebody's food diary is one that gets
run once. Every drill-down below identifies a turn by session, model, tokens
and seconds, which is enough to go and fix it.

    python3 scripts/ted-baseline.py              # 7 days, daily table
    python3 scripts/ted-baseline.py --days 14
    python3 scripts/ted-baseline.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"
LOGS = HERMES / "logs"

DEFAULT_DAYS = 7

# The model Ted is meant to answer on. Anything else carrying real traffic is
# the fallback road, and the share of calls on it is a health number: it is
# invisible to users, who get an answer either way, and it changes both the
# bill and the voice.
PRIMARY_MODEL = "claude-sonnet-5"

# `API call failed (attempt n/3)` — one line per failed attempt, retried or
# not. Counted per day against the calls that day.
_FAILURE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2},\d+ .*API call failed"
)

# A reply that took longer than this is worth a name. Chosen from the data
# rather than from taste: the median reply is a few seconds, so this is not a
# tail, it is a different experience.
SLOW_SECONDS = 60.0


def connect() -> sqlite3.Connection:
    if not STATE_DB.is_file():
        raise SystemExit(f"No state database at {STATE_DB}")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def day_of(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def latencies(db: sqlite3.Connection, cutoff: float) -> tuple[dict, list]:
    """How long each person waited, by day, plus the turns worth naming."""
    rows = db.execute(
        """
        SELECT m.id, m.role, m.timestamp, m.session_id, s.chat_id
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.timestamp > ? AND s.source = 'whatsapp'
          AND m.role IN ('user', 'assistant')
        ORDER BY m.id
        """,
        (cutoff,),
    ).fetchall()

    by_day: dict[str, list[float]] = defaultdict(list)
    slow: list[dict] = []
    pending: dict[str, sqlite3.Row] = {}

    for row in rows:
        if row["role"] == "user":
            pending[row["session_id"]] = row
            continue
        asked = pending.pop(row["session_id"], None)
        if asked is None:
            # A reply with no question before it in the window: a scheduled
            # reminder, or a turn whose question is older than the cutoff.
            # Not a latency, and counting it as one would flatter the number.
            continue
        waited = row["timestamp"] - asked["timestamp"]
        if waited < 0:
            continue
        by_day[day_of(asked["timestamp"])].append(waited)
        if waited >= SLOW_SECONDS:
            slow.append({
                "day": day_of(asked["timestamp"]),
                "session": row["session_id"],
                "seconds": round(waited, 1),
            })

    slow.sort(key=lambda item: item["seconds"], reverse=True)
    return by_day, slow


def usage(db: sqlite3.Connection, cutoff: float) -> dict:
    """Tokens, cost and which model answered, by day."""
    rows = db.execute(
        """
        SELECT model, billing_provider, api_call_count, input_tokens,
               output_tokens, cache_read_tokens, cache_write_tokens,
               estimated_cost_usd, last_seen
        FROM session_model_usage
        WHERE last_seen > ?
        """,
        (cutoff,),
    ).fetchall()

    by_day: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "input": 0, "output": 0, "cost": 0.0, "fallback_calls": 0}
    )
    for row in rows:
        day = by_day[day_of(row["last_seen"])]
        calls = row["api_call_count"] or 0
        day["calls"] += calls
        day["input"] += (
            (row["input_tokens"] or 0)
            + (row["cache_read_tokens"] or 0)
            + (row["cache_write_tokens"] or 0)
        )
        day["output"] += row["output_tokens"] or 0
        day["cost"] += row["estimated_cost_usd"] or 0.0
        if str(row["model"] or "") != PRIMARY_MODEL:
            day["fallback_calls"] += calls
    return by_day


def deliveries(db: sqlite3.Connection, cutoff: float) -> dict:
    by_day: dict[str, dict] = defaultdict(lambda: {"delivered": 0, "lost": 0})
    for row in db.execute(
        "SELECT state, created_at FROM delivery_obligations WHERE created_at > ?",
        (cutoff,),
    ):
        day = by_day[day_of(row["created_at"])]
        if row["state"] == "delivered":
            day["delivered"] += 1
        elif row["state"] in ("failed", "abandoned"):
            day["lost"] += 1
    return by_day


def people(db: sqlite3.Connection, cutoff: float) -> dict:
    by_day: dict[str, set] = defaultdict(set)
    for row in db.execute(
        """
        SELECT m.timestamp, s.chat_id
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE m.timestamp > ? AND s.source='whatsapp' AND m.role='user'
        """,
        (cutoff,),
    ):
        by_day[day_of(row["timestamp"])].add(row["chat_id"])
    return {day: len(chats) for day, chats in by_day.items()}


def failures(cutoff: float) -> tuple[dict, bool]:
    """Failed API attempts per day, and whether the log even covers the window."""
    by_day: dict[str, int] = defaultdict(int)
    first_day = day_of(cutoff)
    earliest = None
    for name in ("agent.log.1", "agent.log"):
        path = LOGS / name
        if not path.is_file():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            match = _FAILURE.match(line)
            if not match:
                continue
            day = match.group(1)
            earliest = min(earliest or day, day)
            # Outside the window is not zero traffic, it is a different
            # question. Letting it through added empty rows for days the rest
            # of the report knows nothing about.
            if day >= first_day:
                by_day[day] += 1
    covered = bool(earliest) and earliest <= first_day
    return by_day, covered


def build(days: int) -> dict:
    db = connect()
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()

    waits, slow = latencies(db, cutoff)
    spend = usage(db, cutoff)
    sent = deliveries(db, cutoff)
    active = people(db, cutoff)
    failed, log_covers = failures(cutoff)

    all_days = sorted(
        set(waits) | set(spend) | set(sent) | set(active) | set(failed)
    )
    table = []
    for day in all_days:
        # The window starts part way through its first day, so that day can
        # appear with nothing in it. An empty row is not a quiet day, it is a
        # day the window barely touched, and printing it as zeros invites the
        # wrong conclusion.
        if not (waits.get(day) or spend.get(day) or sent.get(day) or active.get(day)):
            continue
        seen = waits.get(day, [])
        money = spend.get(day, {})
        post = sent.get(day, {"delivered": 0, "lost": 0})
        calls = money.get("calls", 0)
        answered = len(seen)
        outbound = post["delivered"] + post["lost"]
        users = active.get(day, 0)
        table.append({
            "day": day,
            "people": users,
            "replies": answered,
            "median_seconds": round(statistics.median(seen), 1) if seen else None,
            "p90_seconds": (
                round(sorted(seen)[int(len(seen) * 0.9)], 1) if len(seen) >= 10 else None
            ),
            "calls": calls,
            # Per CALL, not per reply: a scheduled reminder is a call that
            # produces no reply, and dividing its tokens by replies made one
            # quiet day read as 654,716 tokens a message.
            "input_tokens_per_call": round(money.get("input", 0) / calls) if calls else None,
            "output_tokens_per_call": round(money.get("output", 0) / calls) if calls else None,
            "cost_usd": round(money.get("cost", 0.0), 2),
            "cost_per_person_usd": (
                round(money.get("cost", 0.0) / users, 2) if users else None
            ),
            "fallback_rate": (
                round(money.get("fallback_calls", 0) / calls, 3) if calls else None
            ),
            "error_rate": round(failed.get(day, 0) / calls, 3) if calls else None,
            "delivery_rate": round(post["delivered"] / outbound, 3) if outbound else None,
        })

    return {
        "days": days,
        "log_covers_window": log_covers,
        "table": table,
        "slowest": slow[:8],
    }


def render(report: dict) -> None:
    table = report["table"]
    if not table:
        print("No traffic in the window. Nothing to baseline.")
        return

    print(
        f"{'day':<11}{'ppl':>4}{'repl':>6}{'med s':>7}{'p90 s':>7}"
        f"{'calls':>7}{'in/call':>9}{'out/call':>9}{'cost':>8}{'$/ppl':>7}"
        f"{'fallbk':>8}{'err':>7}{'deliv':>7}"
    )
    for row in table:
        def show(key, fmt="{:.0f}"):
            value = row[key]
            return "-" if value is None else fmt.format(value)

        print(
            f"{row['day']:<11}{row['people']:>4}{row['replies']:>6}"
            f"{show('median_seconds', '{:.1f}'):>7}{show('p90_seconds', '{:.1f}'):>7}"
            f"{row['calls']:>7}{show('input_tokens_per_call'):>9}"
            f"{show('output_tokens_per_call'):>9}"
            f"{'$' + format(row['cost_usd'], '.2f'):>8}"
            f"{show('cost_per_person_usd', '{:.2f}'):>7}"
            f"{show('fallback_rate', '{:.0%}'):>8}{show('error_rate', '{:.0%}'):>7}"
            f"{show('delivery_rate', '{:.0%}'):>7}"
        )

    totals_cost = sum(row["cost_usd"] for row in table)
    replies = sum(row["replies"] for row in table)
    print(f"\n{replies} replies, ${totals_cost:.2f} over {len(table)} day(s).")

    if not report["log_covers_window"]:
        print(
            "\n  note: agent.log does not reach the start of this window, so the "
            "error rate\n  for the earliest day(s) reads low. The log is the only "
            "record of a failed\n  call that was retried successfully — nothing "
            "durable keeps it."
        )

    if report["slowest"]:
        print("\nSlowest replies in the window — session, not content:")
        for item in report["slowest"]:
            print(f"  {item['day']}  {item['seconds']:>7.1f}s  session {item['session'][-12:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args()

    report = build(args.days)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
