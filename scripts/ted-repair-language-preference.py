#!/usr/bin/env python3
"""
Give the gate the language preference each user already asked for, out of the
messages they sent before anything was recording it.

    python3 scripts/ted-repair-language-preference.py
    python3 scripts/ted-repair-language-preference.py --apply \
      && HERMES_RESTART_DRAIN_TIMEOUT=30 hermes gateway restart

WHY. Ted now stores, per user, which language they write in, and reads it back
on every turn. Nothing wrote that field before 15 Sep 2026, so everyone who had
already asked starts again from nothing, and the one thing the whole change
exists to fix is somebody having to ask twice.

Two people had asked, and both kept getting Hindi afterwards:

  * Sarah, 9 Sep 2026, "Can we stick with englishhhh". She was told "yep,
    straight english it is". Her next message, thirty seconds later, got "arre
    this is full hug plus pink hearts energy".
  * Vandy, 31 Aug 2026, "No hindi please". She was still getting "sahi pakda
    yaar, potato meri side se assumption chala gaya tha" on 15 Sep.

It reads the requests out of the message history rather than taking a list of
keys, so anyone who asked and is not in that pair is picked up too, and so a
second run after somebody asks tomorrow does the right thing on its own.

THE INFERRED CASE IS LEFT ALONE ON PURPOSE. Somebody who has only ever written
English without asking will be recognised by the live gate within four of their
own messages. Only an explicit request is backfilled here, because that is the
one that is unfair to make twice.

THE RESTART MATTERS. The gateway holds this file in memory and rewrites the
whole thing on its next write, so an edit made while it is up is lost the
moment anybody sends a message. Run the restart in the same command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE_STATE = Path.home() / ".hermes" / "state" / "ted-safety-gates-onboarding.json"
STATE_DB = Path.home() / ".hermes" / "state.db"
IST = timezone(timedelta(hours=5, minutes=30))

sys.path.insert(0, str(REPO))
from hermes import ted_safety_gates as gates  # noqa: E402


def user_key(chat_id: str) -> str:
    """The gate's key for one WhatsApp sender. Must match _user_state_key."""
    identity = f"whatsapp:{chat_id}".encode("utf-8")
    return f"whatsapp:sha256:{hashlib.sha256(identity).hexdigest()}"


def requests_from_history() -> dict[str, tuple[str, str, str, str]]:
    """chat_id -> (choice, who, when, what they wrote). Last request wins."""
    if not STATE_DB.exists():
        return {}
    database = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = database.execute(
            """
            SELECT m.timestamp, s.chat_id, s.display_name, m.content
            FROM messages m JOIN sessions s ON s.id = m.session_id
            WHERE m.role = 'user' AND s.source = 'whatsapp'
              AND s.chat_id IS NOT NULL AND m.content IS NOT NULL AND m.content != ''
            ORDER BY m.timestamp
            """
        ).fetchall()
    finally:
        database.close()

    found: dict[str, tuple[str, str, str, str]] = {}
    for stamp, chat_id, name, content in rows:
        text = content or ""
        if gates._ASKS_FOR_ENGLISH.search(text):
            choice = "english"
        elif gates._ASKS_FOR_HINGLISH.search(text):
            choice = "english" if gates._NEGATOR.search(text) else "hinglish"
        else:
            continue
        when = datetime.fromtimestamp(stamp, IST).strftime("%d %b %Y %H:%M")
        found[chat_id] = (choice, str(name or chat_id), when, text.strip()[:60])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not GATE_STATE.exists():
        print(f"no gate state at {GATE_STATE}")
        return 1

    payload = json.loads(GATE_STATE.read_text(encoding="utf-8"))
    users = payload.get("users")
    if not isinstance(users, dict):
        print("gate state has no users object")
        return 1

    asked = requests_from_history()
    if not asked:
        print("nobody has asked for a language. Nothing to do.")
        return 0

    changes: list[tuple[str, str, str, str, str]] = []
    for chat_id, (choice, who, when, quote) in sorted(asked.items()):
        key = user_key(chat_id)
        current = users.get(key, {}).get("language")
        if current == choice:
            print(f"  ok      {who}: already {choice}")
            continue
        changes.append((key, choice, who, when, quote))

    if not changes:
        print("\nEvery request is already recorded. Nothing to do.")
        return 0

    print()
    for _, choice, who, when, quote in changes:
        print(f"  set     {who} -> {choice}")
        print(f"          asked {when}: \"{quote}\"")

    if not args.apply:
        print("\nDry run. Re-run with --apply, and restart the gateway in the")
        print("same command, or the gateway will write this file back over it.")
        return 0

    backup = GATE_STATE.with_suffix(f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(GATE_STATE, backup)
    for key, choice, _, _, _ in changes:
        users.setdefault(key, {})["language"] = choice
    temporary = GATE_STATE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(GATE_STATE)
    print(f"\nWrote {len(changes)} preference(s). Backup: {backup.name}")
    print("Restart the gateway now if you have not chained it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
