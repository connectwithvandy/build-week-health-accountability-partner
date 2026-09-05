#!/usr/bin/env python3
"""
Count the inbound WhatsApp messages Ted actually received.

    python3 scripts/gateway-message-count.py --schema
    python3 scripts/gateway-message-count.py

Convex cannot answer this. `convex/schema.ts` has no messages table and
`dailyEntries.externalMessageId` is written empty on every row, so the
submission report can only give a floor (one row per thing that produced a
log). The real turn count lives in the gateway's own store, ~/.hermes/state.db.

READ-ONLY BY CONSTRUCTION. The database is opened through a `mode=ro` URI, so
sqlite itself refuses any write, and the only statements here are SELECT and
PRAGMA. Nothing is copied out of the file except table names, column names,
counts and timestamps. Message bodies, phone numbers and any other content are
never read or printed, because this only ever needs to know how many.
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_DB = Path.home() / ".hermes" / "state.db"
IST = timezone(timedelta(hours=5, minutes=30))

# A table worth counting looks like a message log. Matched against table names.
MESSAGE_TABLE = re.compile(r"message|msg|inbox|inbound|turn|event", re.I)

# Columns that say which way a message went, and the values meaning "from user".
DIRECTION_COLUMNS = ("direction", "is_inbound", "inbound", "role", "sender", "kind", "type")
INBOUND_VALUES = {"in", "inbound", "incoming", "received", "user", "human", "from_user", "1", "true"}



def ist(ts: float | None) -> str:
    """Gateway timestamps are unix seconds as floats. Submission reads in IST."""
    if ts is None:
        return "unknown"
    return datetime.fromtimestamp(float(ts), IST).strftime("%Y-%m-%d %H:%M:%S IST")


def connect() -> sqlite3.Connection:
    if not STATE_DB.exists():
        sys.exit(f"no gateway database at {STATE_DB}")
    # mode=ro is the guarantee: sqlite rejects writes at the connection level.
    return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)


def tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def print_schema(conn: sqlite3.Connection) -> None:
    """Names and row counts only. No row is ever read."""
    print(f"gateway database: {STATE_DB}")
    print("")
    for t in tables(conn):
        marker = "  <-- looks like messages" if MESSAGE_TABLE.search(t) else ""
        print(f"{t}  ({count(conn, t)} rows){marker}")
        print(f"    columns: {', '.join(columns(conn, t))}")
    print("")


def report(conn: sqlite3.Connection) -> None:
    """
    The gateway database holds every Hermes session on this machine, including
    the operator's own CLI sessions. A bare COUNT(*) over `messages` is
    therefore not the product number and must never be quoted as one. Every
    count below is joined to `sessions` and split by platform, so the WhatsApp
    figure stands on its own.
    """
    print(f"gateway database: {STATE_DB}")
    print("(read-only; counts and timestamps only, no message content)")
    print("")

    total = count(conn, "messages")
    print(f"Every message row on this machine, all platforms: {total}")
    print("  Not the product number. Includes the operator's own CLI sessions.")
    print("")

    print("Split by platform and role:")
    rows = conn.execute(
        """
        SELECT COALESCE(s.source, '(no session)') AS platform,
               COALESCE(m.role, '(null)')        AS role,
               COUNT(*)
        FROM messages m
        LEFT JOIN sessions s ON s.id = m.session_id
        GROUP BY platform, role
        ORDER BY platform, 3 DESC
        """
    ).fetchall()
    for platform, role, n in rows:
        print(f"  {platform:<16} {role:<12} {n}")
    print("")

    whatsapp = [r for r in rows if "whatsapp" in str(r[0]).lower()]
    if not whatsapp:
        print("No WhatsApp sessions in this database.")
        return

    inbound = sum(n for _, role, n in whatsapp if str(role).lower() == "user")
    outbound = sum(n for _, role, n in whatsapp if str(role).lower() == "assistant")
    print("WhatsApp only:")
    print(f"  Inbound messages from users:  {inbound}   [messages.role = 'user', sessions.source = whatsapp]")
    print(f"  Replies Ted sent back:        {outbound}   [messages.role = 'assistant', sessions.source = whatsapp]")
    print("")

    people = conn.execute(
        """
        SELECT COUNT(DISTINCT COALESCE(s.user_id, s.chat_id))
        FROM sessions s
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
        """
    ).fetchone()[0]
    convos = conn.execute(
        """
        SELECT COUNT(*) FROM sessions s
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
        """
    ).fetchone()[0]
    print(f"  Distinct WhatsApp people:     {people}   [distinct sessions.user_id, falling back to chat_id]")
    print(f"  WhatsApp conversations:       {convos}   [rows in sessions where source is whatsapp]")
    print("")

    span = conn.execute(
        """
        SELECT MIN(m.timestamp), MAX(m.timestamp)
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
        """
    ).fetchone()
    print(f"  Covering: {ist(span[0])} → {ist(span[1])}")
    print("")

    # 34 people in the gateway against 24 user rows in Convex means the raw
    # inbound total also carries the builder's own testing. Showing how the
    # messages spread across people is what makes 522 quotable: a number
    # produced by one very busy sender is a different claim entirely.
    per_person = conn.execute(
        """
        SELECT COALESCE(s.user_id, s.chat_id) AS person, COUNT(*)
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
          AND LOWER(COALESCE(m.role, '')) = 'user'
          AND COALESCE(s.user_id, s.chat_id) IS NOT NULL
        GROUP BY person
        ORDER BY 2 DESC
        """
    ).fetchall()
    # Sessions carrying neither a user_id nor a chat_id cannot be attributed to
    # anyone, so they are held out of the headcount instead of silently
    # inflating it by one. They are still real inbound messages, and are
    # reported on their own line.
    unattributed = conn.execute(
        """
        SELECT COUNT(*)
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
          AND LOWER(COALESCE(m.role, '')) = 'user'
          AND COALESCE(s.user_id, s.chat_id) IS NULL
        """
    ).fetchone()[0]

    print("Inbound messages per person (identities withheld, busiest first):")
    for i, (_person, n) in enumerate(per_person, start=1):
        print(f"  person {i:>2}: {n}")
    print("")
    senders = len(per_person)
    attributed = sum(n for _, n in per_person)
    top = per_person[0][1] if per_person else 0
    rest = attributed - top
    print(f"  {senders} identifiable people sent at least one message ({attributed} messages).")
    if unattributed:
        print(f"  Plus {unattributed} inbound on sessions with no user_id or chat_id, attributable to nobody.")
    print(f"  Busiest single sender: {top} of {attributed} ({top * 100 // max(attributed, 1)}%).")
    print(f"  Everyone else combined: {rest}.")
    print("  The busiest sender is almost certainly the builder's own testing.")
    print(f"  Defensible claim excluding that account: {rest} inbound from {senders - 1} people.")
    print("")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schema", action="store_true", help="print table and column names only")
    args = ap.parse_args()
    conn = connect()
    try:
        print_schema(conn) if args.schema else report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
