#!/usr/bin/env python3
"""Is Ted still sounding like Ted, and which way is it moving.

    python3 scripts/ted-voice-check.py              # four weeks, by week
    python3 scripts/ted-voice-check.py --days 7     # one window
    python3 scripts/ted-voice-check.py --voice-rules  # split by who holds one

WHY. Every other check in this repo answers whether Ted worked: the gates are
on, the link is up, the reminder fired, somebody got an answer. None of them
answers whether the answer sounded like him, and that is the thing the product
actually is. It came up when the 7 stored voice rules were about to be
deleted: the honest question was not "are they duplicates of SOUL.md" but
"does removing them make the replies worse", and nothing could answer it.

WHAT IT COUNTS. Only the SOUL.md rules that a machine can count without
judging taste. Each one is a line in that file, quoted at the rule below, so a
number here can be argued with by reading the source rather than by arguing
about vibes. It says nothing about whether a reply was warm, useful or
correct, and it must never be read as a quality score. A reply can pass all
seven and still be a bad reply.

WHOSE WORDS. Ted's own outgoing messages and nothing else. No user text is
read, counted or printed, which is not squeamishness: `ted-log-retention.py`
exists because 4,998 lines of users' own words ended up in a log file. What
prints here is counts.

WHICH COPY OF THEM. Two, side by side. **received** is the delivery ledger:
what a person read. **drafted** is the `messages` table: what the model wrote
before the gates edited, replaced or appended to it. This file measured
drafts alone until 19 Sep 2026 and was wrong in both directions — it missed
every fixed string the gates themselves write, which is where nine of that
week's twelve receipt openings came from, and it counted the meal card's own
calorie bar as Ted putting an emoji beside a metric. The card is cut before
counting; see `spoken_part`.

CRON IS EXCLUDED. A reminder is written to a different shape — it is allowed
to be a single line with no reaction — and mixing the two moves every number
without anything changing. `ted-window-check.py` learned the same lesson from
the other direction.

READ THE DIRECTION, NOT THE LEVEL. A single week's number means very little at
this traffic: four dashes in 298 replies is the whole difference between 1.3%
and 0%. Four weeks side by side is what shows a change.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

STATE_DB = Path.home() / ".hermes" / "state.db"

# Each rule is one countable sentence from ~/.hermes/SOUL.md, and the line it
# comes from is named so the check can be argued with.
#
# Deliberately not counted: warmth, usefulness, whether the reaction was fresh,
# whether the Hinglish landed. Those are the parts that matter most and none of
# them survives being turned into a regular expression.
RULES = (
    (
        "mid-sentence dash",
        'SOUL.md: "I never put a dash in the middle of a sentence"',
        re.compile(r"\w\s*[—–]\s*\w|\w\s+-\s+\w"),
    ),
    (
        "receipt opening",
        'SOUL.md: "I never open with logged, noted, got it or saved"',
        re.compile(r"^\s*(logged|noted|got it|saved|done)\b", re.IGNORECASE),
    ),
    (
        "bullets or bold",
        'SOUL.md: "Things that are never mine: bullet lists, bold headers"',
        re.compile(r"^\s*[-*•]\s|\*\*", re.MULTILINE),
    ),
    (
        "two or more questions",
        'SOUL.md: "contains no more than one question"',
        re.compile(r"\?[^?]*\?", re.DOTALL),
    ),
    (
        "emoji beside a number",
        'SOUL.md: "no emoji beside a metric, ever"',
        # The unit is part of the metric. "92g 💪" and "1850 kcal 🔥" are the
        # shape this rule is about, and requiring the digit itself to touch
        # the emoji missed both. Found by a test, not by reading.
        #
        # Spaces and tabs only, never a newline. `\s` crossed line breaks and
        # made the meal card fail its own rule: the block ends "Fiber: 6g" and
        # the next block opens "📊 Daily Overview:" two lines down, which
        # matched as "6g 📊". 44 of the 45 hits on the week to 19 Sep 2026
        # were that pair and the calorie bar's "⚪ 8". An emoji on its own
        # line, heading a block, is not an emoji beside a metric; it is the
        # card's layout, and counting it buried the two real ones.
        re.compile(
            r"[\U0001F300-\U0001FAFF☀-➿][ \t]*\d"
            r"|\d[ \t]*(?:g|kg|ml|l|kcal|cal|k|steps?)?[ \t]*"
            r"[\U0001F300-\U0001FAFF☀-➿]",
            re.IGNORECASE,
        ),
    ),
    (
        "capitalised opening",
        'SOUL.md: "Casual and lowercase, real, never formal"',
        re.compile(r"^\s*[A-Z][a-z]"),
    ),
)


def connect() -> sqlite3.Connection:
    if not STATE_DB.is_file():
        raise SystemExit(f"No message history at {STATE_DB}")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def replies(db: sqlite3.Connection, since: float, until: float) -> list[tuple[str, str]]:
    """(display name, Ted's text) for what the model *drafted* in the window.

    `session_id LIKE 'cron_%'` is how a scheduled send identifies itself, and
    those are left out for the reason at the top of this file.

    This is the draft, not the message. The gates rewrite, append to and
    replace the model's text on the way out, so this answers "how is the model
    writing" and never "what did somebody read". `delivered()` is the other
    half, and the two are printed side by side because the gap between them is
    the gate's own contribution to Ted's voice.
    """
    rows = db.execute(
        """
        SELECT s.display_name AS who, m.content AS text
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.role = 'assistant'
          AND s.source = 'whatsapp'
          AND m.timestamp > ? AND m.timestamp <= ?
          AND m.session_id NOT LIKE 'cron_%'
        """,
        (since, until),
    ).fetchall()
    return [(str(row["who"] or "?"), str(row["text"] or "")) for row in rows]


# What a person actually read.
#
# The first version of this file measured `messages` alone and called it "Ted's
# own replies". It is the model's draft. On the week to 19 Sep 2026 the draft
# broke the receipt rule 10 times in 352 and the delivered text broke it 12
# times in 165 — 2.8% against 7.3% — and nine of those twelve were fixed
# strings the gates themselves write, which appear in no draft at all and were
# therefore invisible to every number this file had ever printed.
#
# The memory rule that names this is "delivered text is not the messages
# table". It was written about reminders and is true of every gated reply.
#
# Two exclusions, both for the same reason the draft query has them:
#   * `session_key LIKE 'cron:%'` is a scheduled reminder, which patch 16 put
#     into this ledger. A reminder is written to a different shape.
#   * anything not `delivered` was composed and never read. The three
#     `abandoned` rows in that week are a delivery fault, not a voice one.
LEDGER_STARTS_NOTE = (
    "the delivery ledger only reaches back to 11 Sep 2026, so a window "
    "older than that has nothing to receive"
)


def delivered(
    db: sqlite3.Connection, since: float, until: float
) -> list[tuple[str, str]]:
    """(display name, Ted's text) for what was actually sent in the window."""
    try:
        rows = db.execute(
            """
            SELECT
              (SELECT s.display_name FROM sessions s
                WHERE s.chat_id = o.chat_id AND s.source = 'whatsapp'
                ORDER BY s.id DESC LIMIT 1) AS who,
              o.content AS text
            FROM delivery_obligations o
            WHERE o.platform = 'whatsapp'
              AND o.state = 'delivered'
              AND o.session_key NOT LIKE 'cron:%'
              AND o.created_at > ? AND o.created_at <= ?
            """,
            (since, until),
        ).fetchall()
    except sqlite3.OperationalError:
        # An older state.db with no ledger. Say nothing rather than zero.
        return []
    return [(str(row["who"] or "?"), str(row["text"] or "")) for row in rows]


# Where Ted stops writing and the gate starts printing.
#
# `_with_meal_breakdown` and `_daily_overview` append a fixed block to the end
# of a reply: the meal summary, the daily overview, and the six-circle calorie
# bar. That block is not prose and was never written by the model. It is a
# layout Vandy approved, and its bar is "🟢🟢⚪⚪⚪⚪ 31%" by design.
#
# Measured with the block in, the emoji rule read 45 hits in the week to 19
# Sep 2026 and 43 of them were that bar. The two real ones ("yup pakda 😄 1870
# pe lock karein") were buried under the card obeying its own spec. So the
# card is cut before counting, the same way cron is: not because it does not
# count, but because it is a different thing being counted.
#
# Both blocks are appended last, by construction in both call sites, so the
# cut runs from the first header line to the end.
_CARD_HEADER = re.compile(
    r"^\s*\W*\s*(?:daily\s+overview|meal(?:\s+\d+)?\s+summary)\s*:",
    re.IGNORECASE,
)


def spoken_part(text: str) -> str:
    """The reply with the gate's appended card removed."""
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if _CARD_HEADER.match(line):
            return "\n".join(lines[:index]).strip()
    return (text or "").strip()


def measure(texts: list[str]) -> dict:
    """Every rule as hits out of total. An empty sample measures nothing and
    says so rather than reporting a tidy 0%."""
    total = len(texts)
    result = {"replies": total}
    if not total:
        return result
    # The card is cut here rather than at the query, so "replies" still counts
    # every reply, including one that was nothing but a card.
    spoken = [spoken_part(text) for text in texts]
    result["avg chars"] = round(sum(len(t) for t in spoken) / total)
    for name, _why, pattern in RULES:
        result[name] = sum(1 for text in spoken if pattern.search(text))
    return result


def rule_holders() -> set[str]:
    """The people who still have a voice rule stored, by name.

    Read through the purge script so there is one answer to "who holds one",
    and returns an empty set if production cannot be reached: this is a
    comparison, and a comparison that cannot be drawn is not a failure.
    """
    import importlib.util

    source = Path(__file__).resolve().parent / "ted-purge-voice-rules.py"
    try:
        spec = importlib.util.spec_from_file_location("ted_purge_voice_rules", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = module.voice_rules(
            module.convex_rows("userFacts"),
            module.convex_rows("users"),
            module.voice_rule_test(),
        )
    except (OSError, SystemExit, AttributeError):
        return set()
    return {row["name"] for row in rows}


def show(label: str, stats: dict) -> None:
    if not stats["replies"]:
        print(f"  {label:16} no replies")
        return
    total = stats["replies"]
    parts = []
    for name, _why, _pattern in RULES:
        hits = stats[name]
        parts.append(f"{name} {hits}/{total} ({100 * hits / total:.1f}%)")
    print(f"  {label:16} {total} replies, {stats['avg chars']} chars avg")
    for part in parts:
        print(f"      {part}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="one window of this many days")
    parser.add_argument("--weeks", type=int, default=4, help="how many weeks to show")
    parser.add_argument(
        "--voice-rules",
        action="store_true",
        help="split the window by who has a stored voice rule",
    )
    args = parser.parse_args()

    db = connect()
    now = time.time()

    print("Ted's own replies against the countable SOUL.md rules.")
    print("Chat only, reminders excluded. No user text is read.")
    print("Measured on what was delivered, with the model's draft beside it.\n")
    for _name, why, _pattern in RULES:
        print(f"  {why}")
    print()

    # Two rows per window, always. "received" is the answer to the question
    # this file asks; "drafted" is kept beside it because the difference is
    # the gates' own writing, and a gate that breaks a SOUL rule shows up
    # nowhere else.
    def window(label: str, since: float, until: float) -> None:
        show(f"{label} received", measure([t for _w, t in delivered(db, since, until)]))
        show(f"{label} drafted", measure([t for _w, t in replies(db, since, until)]))

    if args.days:
        print(f"last {args.days} days")
        window("all", now - args.days * 86400, now)
    else:
        print(f"by week, newest first ({args.weeks} weeks)")
        for week in range(args.weeks):
            until = now - week * 7 * 86400
            window(f"week -{week}", until - 7 * 86400, until)
    print(f"\n  received = what was sent. drafted = what the model wrote before")
    print(f"  the gates touched it. Where received has no replies, {LEDGER_STARTS_NOTE}.")

    if args.voice_rules:
        holders = rule_holders()
        print()
        if not holders:
            print("Nobody has a voice rule stored, so there is nothing to split by.")
            return 0
        span = args.days or 7
        rows = delivered(db, now - span * 86400, now)
        print(f"last {span} days received, split by who holds a stored voice rule")
        show("with a rule", measure([t for who, t in rows if who in holders]))
        show("everyone else", measure([t for who, t in rows if who not in holders]))
        print(
            "\n  A gap here is not proof the rules caused it. These are the "
            "people\n  Ted happened to write one for, not a group anybody "
            "assigned."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
