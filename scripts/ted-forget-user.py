#!/usr/bin/env python3
"""
Erase one user's gateway-held data: the half "delete my data" cannot reach.

    python3 scripts/ted-forget-user.py --who 918882688533
    python3 scripts/ted-forget-user.py --who Shreya
    python3 scripts/ted-forget-user.py --who Shreya --apply

WHY. `src/app/privacy/page.tsx` promises that sending "delete my data" erases
the profile, facts, targets, reminders and logs, and then says plainly that two
things sit outside it: the photos and voice notes, and Ted's own record of the
conversation, both held on the machine that runs Ted. The page is honest. What
it leaves is a privacy commitment with a person in the loop, discharged by hand,
from memory, at whatever hour the request lands.

The gate's `_delete_user_data` already does the Convex half properly, behind
three guards, and this does not touch it. This is only the machine half.

WHAT IS ACTUALLY HELD, which is more than the page implies:

  * `messages` and `sessions` in ~/.hermes/state.db — the conversation.
  * `request_dump_*.json` in ~/.hermes/sessions — whole API requests, so the
    conversation again, in full, on disk.
  * `delivery_obligations` — carries a `content` column holding the text of
    replies queued for that chat. This is conversation record too, and nothing
    else deletes it.
  * `gateway_routing` — the session key, an identifier rather than content.
  * ~/.hermes/cache/images and ~/.hermes/cache/audio — the photos and voice
    notes themselves, named by content hash, so the only way to know which
    belong to somebody is to read the messages that reference them. They must
    therefore be collected BEFORE the messages are deleted, which is the one
    ordering constraint in this file.

The first three are `hermes sessions delete`'s job and it is used rather than
reimplemented: it knows its own schema, cascades delegate children, orphans
branch children so a foreign key still holds, and removes the on-disk transcript
files. Hand-written SQL over seven tables would drift from that the first time
the gateway changed.

WHAT THIS CANNOT REACH, and says so every run rather than implying it is clean:
~/.hermes/logs/agent.log holds message text and rotates on its own schedule.
Editing a live log the gateway is writing to is a worse idea than leaving it,
and it ages out by itself.

Dry run by default. Nothing is deleted without --apply, and --apply prints the
name and the message count and asks, because the one thing worse than a
deletion nobody performed is a deletion performed on the wrong person.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERMES = Path.home() / ".hermes"
STATE_DB = HERMES / "state.db"
SESSIONS_DIR = HERMES / "sessions"
CACHE_DIRS = (HERMES / "cache" / "images", HERMES / "cache" / "audio")
AGENT_LOG = HERMES / "logs" / "agent.log"

# Only ever unlink inside these. A path scraped out of message text is
# attacker-adjacent input: it was written by whatever the gateway recorded, and
# a crafted filename must not be able to reach outside the cache.
DELETABLE_ROOTS = tuple(CACHE_DIRS)

MEDIA_PATH = re.compile(r"(/[^\s\"'<>|]+\.(?:jpg|jpeg|png|gif|webp|ogg|oga|opus|m4a|mp3|wav|pdf))")


def connect_ro() -> sqlite3.Connection:
    if not STATE_DB.exists():
        sys.exit(f"no gateway store at {STATE_DB}")
    return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)


def resolve(who: str) -> tuple[list[str], str]:
    """Find the sessions belonging to one person.

    `who` may be a WhatsApp `@lid`, a bare phone number, or a display name. A
    name is matched case-insensitively against `sessions.display_name`, which is
    what makes this usable from a WhatsApp request that says "delete my data"
    and gives you a person rather than an identifier.
    """
    con = connect_ro()
    try:
        rows = con.execute(
            "select id, coalesce(user_id,''), coalesce(chat_id,''), "
            "coalesce(display_name,''), coalesce(session_key,'') "
            "from sessions where source='whatsapp'"
        ).fetchall()
    finally:
        con.close()

    needle = who.strip().lower()
    hits = [
        r for r in rows
        if needle in r[1].lower() or needle in r[2].lower()
        or needle == r[3].strip().lower() or needle in r[4].lower()
    ]
    if not hits:
        sys.exit(f"no whatsapp session matches {who!r}")

    names = {r[3].strip() for r in hits if r[3].strip()}
    people = {r[1] or r[2] for r in hits}
    if len(people) > 1:
        sys.exit(
            f"{who!r} matches {len(people)} different people: "
            + ", ".join(sorted(names) or people)
            + ". Use the exact @lid or number."
        )
    return [r[0] for r in hits], (sorted(names)[0] if names else who)


def media_for(session_ids: list[str]) -> list[Path]:
    """Every cached file this person's messages point at.

    Collected before anything is deleted: the filenames are content hashes, so
    once the messages are gone there is no way left to tell whose a file was.
    """
    con = connect_ro()
    found: set[Path] = set()
    try:
        for sid in session_ids:
            for (content,) in con.execute(
                "select content from messages where session_id=? and content is not null",
                (sid,),
            ):
                for raw in MEDIA_PATH.findall(content):
                    path = Path(raw)
                    if any(path.is_relative_to(root) for root in DELETABLE_ROOTS) and path.exists():
                        found.add(path)
    finally:
        con.close()
    return sorted(found)


def counts_for(session_ids: list[str]) -> dict:
    con = connect_ro()
    marks = ",".join("?" * len(session_ids))
    try:
        msgs = con.execute(
            f"select count(*) from messages where session_id in ({marks})", session_ids
        ).fetchone()[0]
        keys = [
            r[0] for r in con.execute(
                f"select distinct coalesce(session_key,'') from sessions where id in ({marks})",
                session_ids,
            ) if r[0]
        ]
        chats = [
            r[0] for r in con.execute(
                f"select distinct coalesce(chat_id,'') from sessions where id in ({marks})",
                session_ids,
            ) if r[0]
        ]
        obligations = 0
        if chats:
            m2 = ",".join("?" * len(chats))
            obligations = con.execute(
                f"select count(*) from delivery_obligations where chat_id in ({m2})", chats
            ).fetchone()[0]
        routing = 0
        if keys:
            m3 = ",".join("?" * len(keys))
            routing = con.execute(
                f"select count(*) from gateway_routing where session_key in ({m3})", keys
            ).fetchone()[0]
    finally:
        con.close()
    dumps = [
        p for sid in session_ids
        for p in SESSIONS_DIR.glob(f"request_dump_{sid}_*.json")
    ] if SESSIONS_DIR.exists() else []
    return {
        "messages": msgs, "obligations": obligations, "routing": routing,
        "dumps": dumps, "chats": chats, "keys": keys,
    }


def delete_rows(table: str, column: str, values: list[str]) -> int:
    """The two tables `hermes sessions delete` does not touch."""
    if not values:
        return 0
    con = sqlite3.connect(STATE_DB)
    try:
        marks = ",".join("?" * len(values))
        cur = con.execute(f"delete from {table} where {column} in ({marks})", values)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--who", required=True, help="@lid, phone number, or display name")
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args()

    session_ids, name = resolve(args.who)
    media = media_for(session_ids)
    c = counts_for(session_ids)

    print(f"\n{name} — {len(session_ids)} whatsapp session(s)\n")
    print(f"  {c['messages']:>5}  messages in the gateway store")
    print(f"  {len(c['dumps']):>5}  request dumps on disk")
    print(f"  {c['obligations']:>5}  delivery obligations (these carry reply text)")
    print(f"  {c['routing']:>5}  routing entries")
    print(f"  {len(media):>5}  photos and voice notes")
    for p in media[:8]:
        print(f"         {p}")
    if len(media) > 8:
        print(f"         ... and {len(media) - 8} more")

    print(f"\n  not reachable: {AGENT_LOG} holds message text and rotates on its")
    print( "  own. Editing a log the gateway is writing to is worse than leaving it.")

    if not args.apply:
        print("\nDry run. Nothing was deleted. Re-run with --apply.\n")
        return 0

    print(f"\nThis permanently erases the above for {name}. It cannot be undone.")
    if input("Type the name to confirm: ").strip().lower() != name.strip().lower():
        print("Not confirmed. Nothing deleted.")
        return 1

    # Media first: once the messages are gone nothing links a hashed filename
    # to a person, so a failure here must not be able to strand a file.
    removed_media = 0
    for path in media:
        if not any(path.is_relative_to(root) for root in DELETABLE_ROOTS):
            continue
        try:
            path.unlink()
            removed_media += 1
        except OSError as error:
            print(f"  could not remove {path}: {error}")

    rows = delete_rows("delivery_obligations", "chat_id", c["chats"])
    rows += delete_rows("gateway_routing", "session_key", c["keys"])

    deleted_sessions = 0
    for sid in session_ids:
        result = subprocess.run(
            ["hermes", "sessions", "delete", sid, "--yes"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            deleted_sessions += 1
        else:
            print(f"  session {sid} failed: {(result.stderr or result.stdout).strip()[:120]}")

    print(f"\n  {deleted_sessions}/{len(session_ids)} sessions deleted, "
          f"{removed_media} media files removed, {rows} other rows removed.")
    print("  Convex is a separate half and is untouched: the user's own "
          "\"delete my data\" does that.\n")
    return 0 if deleted_sessions == len(session_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
