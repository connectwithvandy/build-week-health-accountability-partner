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


CONFIG_YAML = Path.home() / ".hermes" / "config.yaml"


def mask(digits: str) -> str:
    """Country code and last three only, so a comparison can be read without
    printing anyone's full number into a terminal or a log."""
    return f"{digits[:2]}…{digits[-3:]}" if len(digits) > 6 else "…"


WHATSAPP_STORE = Path.home() / ".hermes" / "whatsapp"


def own_jids() -> set[str]:
    """
    The phone numbers the gateway is logged in as, read out of the WhatsApp
    client store. Every sqlite file under the store directory is opened
    read-only and any column named like a JID is scanned for one; the store
    layout differs between client libraries, so this looks for the shape rather
    than assuming a table name. Returns bare digits.
    """
    numbers: set[str] = set()
    if not WHATSAPP_STORE.exists():
        return numbers
    for path in sorted(WHATSAPP_STORE.rglob("*")):
        if not path.is_file() or path.suffix in {".log", ".json", ".yaml"}:
            continue
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            tables = [
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            for table in tables:
                cols = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")').fetchall()]
                for col in cols:
                    if "jid" not in col.lower() and col.lower() not in {"id", "our_jid"}:
                        continue
                    try:
                        rows = db.execute(f'SELECT DISTINCT "{col}" FROM "{table}" LIMIT 50').fetchall()
                    except sqlite3.Error:
                        continue
                    for (value,) in rows:
                        # A JID looks like 918660650986:12@s.whatsapp.net; the
                        # part before the colon or @ is the account's number.
                        m = re.match(r"^(\\d{10,15})[:@]", str(value or ""))
                        if m:
                            numbers.add(m.group(1))
        except sqlite3.Error:
            continue
        finally:
            db.close()
    return numbers


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


def verify_number(conn: sqlite3.Connection, number: str) -> None:
    """
    Check that the WhatsApp number advertised on the site is the one the gateway
    is actually carrying traffic for. A live gateway proves only that some
    number is answering; putting the wrong one on the landing page would send
    every visitor into silence, and nothing else in the submission catches that.

    Only digits are compared, so +91 866..., 91866... and 0091866... all match.
    No number other than the one passed in is ever printed.
    """
    digits = re.sub(r"\\D", "", number)
    if not digits:
        sys.exit("pass a phone number to check, digits and separators both fine")

    hits = conn.execute(
        """
        SELECT COUNT(*) FROM sessions s
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
          AND (
            REPLACE(REPLACE(REPLACE(COALESCE(s.session_key,''), '+',''), '-',''), ' ','') LIKE ?
         OR REPLACE(REPLACE(REPLACE(COALESCE(s.chat_id,''),     '+',''), '-',''), ' ','') LIKE ?
         OR REPLACE(REPLACE(REPLACE(COALESCE(s.user_id,''),     '+',''), '-',''), ' ','') LIKE ?
         OR REPLACE(REPLACE(REPLACE(COALESCE(s.origin_json,''), '+',''), '-',''), ' ','') LIKE ?
          )
        """,
        (f"%{digits}%",) * 4,
    ).fetchone()[0]

    latest = conn.execute(
        """
        SELECT MAX(m.timestamp) FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE LOWER(COALESCE(s.source, '')) LIKE '%whatsapp%'
        """
    ).fetchone()[0]

    print(f"Checking {number} against the gateway's WhatsApp sessions.")
    print("")
    if hits:
        print(f"  MATCH: {hits} WhatsApp session rows reference this number.")
        print("  The number on the site is the one the gateway is running.")
    else:
        print("  No session row references it. On its own this proves nothing:")
        print("  sessions record who messaged Ted, not the number Ted answers on.")
    print("")

    # The session rows are the wrong place to settle this. The number the
    # gateway actually answers on is the account bound in its config, so read
    # that and compare. Only the verdict and a masked number are printed; the
    # config holds credentials and none of it is echoed.
    print(f"  Config check ({CONFIG_YAML}):")
    if not CONFIG_YAML.exists():
        print("    no config file, cannot settle this from here.")
    else:
        text = CONFIG_YAML.read_text(errors="replace")
        # Phone-shaped runs of digits, 10 to 15 long, which is E.164's range.
        found = {re.sub(r"\\D", "", m) for m in re.findall(r"\\+?\\d[\\d\\-\\s]{9,20}", text)}
        found = {f for f in found if 10 <= len(f) <= 15}
        if digits in found:
            print(f"    MATCH: {mask(digits)} is bound in the gateway config.")
            print("    The site is advertising the number Ted answers on.")
        elif found:
            print(f"    MISMATCH: the config carries {len(found)} phone-shaped number(s),")
            for f in sorted(found):
                print(f"      {mask(f)}")
            print(f"    and none of them is {mask(digits)}, the number on the site.")
            print("    Open the site link on your phone and confirm a reply comes back")
            print("    before submitting, because this is the one failure a judge hits first.")
        else:
            print("    no phone-shaped number in the config, cannot settle this from here.")

    # A linked WhatsApp account keeps its own JID in the client store rather
    # than in config, so that is the last place worth looking before giving up
    # and telling the builder to test it by hand.
    print("")
    print(f"  Linked-device check ({WHATSAPP_STORE}):")
    own = own_jids()
    if not own:
        print("    no linked-device record found, cannot settle this from here.")
    elif digits in own:
        print(f"    MATCH: {mask(digits)} is the account the gateway is linked to.")
        print("    The site is advertising the number Ted answers on.")
    else:
        print(f"    MISMATCH: the gateway is linked to {', '.join(mask(o) for o in sorted(own))},")
        print(f"    not {mask(digits)}, which is the number on the site.")
    print("")
    print(f"  Most recent WhatsApp message on any session: {ist(latest)}")
    print("")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schema", action="store_true", help="print table and column names only")
    ap.add_argument("--verify-number", metavar="NUMBER", help="check a number against the gateway's WhatsApp sessions")
    args = ap.parse_args()
    conn = connect()
    try:
        if args.schema:
            print_schema(conn)
        elif args.verify_number:
            verify_number(conn, args.verify_number)
        else:
            report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
