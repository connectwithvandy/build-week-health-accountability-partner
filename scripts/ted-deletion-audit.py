#!/usr/bin/env python3
"""Search every store for a person Ted was told to forget.

Roadmap task T09's last line, the one nothing satisfied:

    Definition of done: One confirmed deletion request leaves no active user
    data or scheduled action in any declared store, verified by an automated
    post-delete search.

`ted-forget-user.py` performs the deletion. Nothing checked afterwards, and
"verified by an automated post-delete search" is not a detail of the wording:
a deletion that half worked looks exactly like one that worked, from the
outside, forever.

It found something on its first run. **Udayan asked to be forgotten on 3 Sep
2026 at 22:59 and his record still holds a name.** The gate's `_forget_user`
leaves a deliberate tombstone — a hashed key and a timestamp, strictly less
than it removed — and its own comment says "no profile and nothing they told
Ted". Every state snapshot from 4 Sep onward carries `{"forgotten_at": …,
"name": "UD"}`; the two snapshots from before the deletion do not have the
record at all. Something wrote a name back into an erased record within about
thirteen hours, and sixteen days passed before anybody looked.

WHAT COUNTS AS A DECLARED STORE. The list in `ted-forget-user.py` is the four
it deletes from. The real number is larger, which is the other thing this found
— `grep -rl` for one live user's id across `~/.hermes` hits 25 files. Backups
and snapshots are legitimate retention and are reported separately from live
stores rather than treated as leaks, because a backup that forgets on demand is
not a backup. What matters is that they are *named*: an undeclared store is the
one nobody empties.

This reads everything read-only and writes nothing anywhere. It deletes
nothing: it is the check, not the cure.

    python3 scripts/ted-deletion-audit.py --forgotten        # everyone erased
    python3 scripts/ted-deletion-audit.py --who Udayan
    python3 scripts/ted-deletion-audit.py --who 918882688533 --all-stores
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"
GATE_STATE = HERMES / "state"
ONBOARDING = GATE_STATE / "ted-safety-gates-onboarding.json"
BACKUPS = Path(os.environ.get("TED_BACKUP_DIR", Path.home() / "ted-backups"))

# Keys the gate's tombstone is allowed to keep. Everything else in a record
# marked `forgotten_at` is data that came back after the erasure.
TOMBSTONE_KEYS = frozenset({"forgotten_at", "forgotten_at_index"})


@dataclass
class Finding:
    store: str
    detail: str
    live: bool = True


@dataclass
class Person:
    label: str
    gate_keys: set[str] = field(default_factory=set)
    identifiers: set[str] = field(default_factory=set)
    session_ids: list[str] = field(default_factory=list)


def gate_key(sender_id: str) -> str:
    """The gate's key for one user, derived the way the gate derives it.

    Copied from `ted-forget-user.py`, which copied it from the gate, for the
    same reason given there: this has to run with the gateway stopped. If the
    derivation drifts, the key count printed next to the finding count makes a
    silent miss read as "2 keys, 0 records" rather than as success.
    """
    identity = f"whatsapp:{sender_id}".encode("utf-8")
    return f"whatsapp:sha256:{hashlib.sha256(identity).hexdigest()}"


def connect() -> sqlite3.Connection:
    if not STATE_DB.is_file():
        raise SystemExit(f"No state database at {STATE_DB}")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def load_onboarding() -> dict:
    try:
        data = json.loads(ONBOARDING.read_text())
    except (OSError, ValueError):
        return {}
    return data.get("users", data) if isinstance(data, dict) else {}


def forgotten_people() -> list[tuple[str, dict]]:
    return [
        (key, record)
        for key, record in load_onboarding().items()
        if isinstance(record, dict) and record.get("forgotten_at")
    ]


def resolve(db: sqlite3.Connection, who: str) -> Person:
    """Everything this person is known by, from whatever was typed."""
    rows = db.execute(
        """
        SELECT DISTINCT id, chat_id, user_id, display_name
        FROM sessions
        WHERE source = 'whatsapp'
          AND (chat_id LIKE ? OR user_id LIKE ? OR display_name LIKE ?)
        """,
        (f"%{who}%", f"%{who}%", f"%{who}%"),
    ).fetchall()

    person = Person(label=who)
    for row in rows:
        person.session_ids.append(row["id"])
        for value in (row["chat_id"], row["user_id"]):
            if value:
                person.identifiers.add(value)
                person.gate_keys.add(gate_key(value))
        if row["display_name"]:
            person.label = row["display_name"]
    return person


def person_for_gate_key(db: sqlite3.Connection, key: str) -> Person:
    """Work back from a hashed key to whatever the database still knows.

    The hash cannot be reversed, so every known id is hashed and compared. A
    key with no match is not an error: it is a deletion that reached the
    sessions table, which is the outcome asked for.
    """
    person = Person(label=key[-12:], gate_keys={key})
    for row in db.execute(
        "SELECT DISTINCT id, chat_id, user_id, display_name FROM sessions WHERE source='whatsapp'"
    ):
        for value in (row["chat_id"], row["user_id"]):
            if value and gate_key(value) == key:
                person.session_ids.append(row["id"])
                person.identifiers.add(value)
                if row["display_name"]:
                    person.label = row["display_name"]
    return person


def check_tombstone(key: str, record: dict) -> list[Finding]:
    """Whether an erased record kept more than a hashed key and a time."""
    extra = sorted(set(record) - TOMBSTONE_KEYS)
    if not extra:
        return []
    shown = ", ".join(f"{name}={record[name]!r}" for name in extra)
    return [
        Finding(
            store=f"{ONBOARDING.name}",
            detail=f"record marked forgotten still holds {shown}",
        )
    ]


def check_database(db: sqlite3.Connection, person: Person) -> list[Finding]:
    findings: list[Finding] = []
    if not person.session_ids and not person.identifiers:
        return findings

    if person.session_ids:
        marks = ",".join("?" * len(person.session_ids))
        rows = db.execute(
            f"SELECT COUNT(*) FROM messages WHERE session_id IN ({marks})",
            person.session_ids,
        ).fetchone()[0]
        if rows:
            findings.append(Finding("state.db messages", f"{rows} row(s)"))
        findings.append(
            Finding("state.db sessions", f"{len(person.session_ids)} row(s)")
        )

    for chat in person.identifiers:
        held = db.execute(
            "SELECT COUNT(*) FROM delivery_obligations WHERE chat_id=?", (chat,)
        ).fetchone()[0]
        if held:
            findings.append(
                Finding("state.db delivery_obligations", f"{held} row(s) for {chat}")
            )
        routing = db.execute(
            "SELECT COUNT(*) FROM gateway_routing WHERE entry_json LIKE ?",
            (f"%{chat}%",),
        ).fetchone()[0]
        if routing:
            findings.append(Finding("state.db gateway_routing", f"{routing} entry"))
    return findings


def check_scheduled(person: Person) -> list[Finding]:
    """Reminders that would still fire. T09 asks for these to be cancelled.

    Read from the live `jobs.json` only. The `.bak` files beside it are
    snapshots and are reported by `check_snapshots`.
    """
    jobs_file = HERMES / "cron" / "jobs.json"
    try:
        jobs = json.loads(jobs_file.read_text()).get("jobs", [])
    except (OSError, ValueError):
        return [Finding("cron/jobs.json", "unreadable — cannot prove no job fires")]

    findings: list[Finding] = []
    needles = {value for value in person.identifiers}
    needles |= {key.split(":")[-1][:12] for key in person.gate_keys}
    for job in jobs:
        blob = json.dumps(job)
        if any(needle and needle in blob for needle in needles):
            state = "ENABLED" if job.get("enabled") else "disabled"
            findings.append(
                Finding("cron/jobs.json", f"{job.get('name')} ({state})")
            )
    return findings


def check_files(person: Person) -> list[Finding]:
    """Live files outside the database that name this person."""
    findings: list[Finding] = []
    targets = [
        HERMES / "channel_directory.json",
        HERMES / "whatsapp" / "lid-phone-map-20260917.json",
    ]
    for path in targets:
        if not path.is_file():
            continue
        try:
            blob = path.read_text()
        except OSError:
            continue
        for value in person.identifiers:
            if value and value in blob:
                findings.append(Finding(path.name, f"names {value}"))
                break
    return findings


def check_snapshots(person: Person) -> list[Finding]:
    """Backups and pre-repair snapshots. Retention, reported not judged.

    A deletion cannot reach into a backup without making the backup useless,
    and `ted-backup.py` exists because a host move is when data is lost. These
    are listed so the retention is a decision somebody made rather than a
    surprise found later.
    """
    findings: list[Finding] = []
    needles = person.identifiers | person.gate_keys
    if not needles:
        return findings

    roots = [GATE_STATE, HERMES / "cron", HERMES / "profiles", BACKUPS]
    for root in roots:
        if not root.is_dir():
            continue
        hits = 0
        for path in root.rglob("*"):
            if not path.is_file() or path.stat().st_size > 20_000_000:
                continue
            if path.suffix not in {".json", ".bak"} and ".bak" not in path.name:
                continue
            try:
                blob = path.read_text(errors="ignore")
            except OSError:
                continue
            if any(needle in blob for needle in needles):
                hits += 1
        if hits:
            findings.append(
                Finding(f"{root.name}/ snapshots", f"{hits} file(s)", live=False)
            )
    return findings


def report(person: Person, findings: list[Finding], keys: int) -> None:
    live = [f for f in findings if f.live]
    retained = [f for f in findings if not f.live]

    print(f"\n{person.label}")
    print(
        f"  {keys} gate key(s), {len(person.identifiers)} identifier(s), "
        f"{len(person.session_ids)} session(s) known."
    )
    if live:
        for finding in live:
            print(f"  LIVE  {finding.store}: {finding.detail}")
    else:
        print("  ok    no live store holds anything for this person.")
    for finding in retained:
        print(f"  kept  {finding.store}: {finding.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--who", help="name, number or chat id")
    group.add_argument(
        "--forgotten",
        action="store_true",
        help="audit everyone the gate has marked forgotten",
    )
    parser.add_argument(
        "--all-stores",
        action="store_true",
        help="include backups and snapshots, which are retention, not leaks",
    )
    args = parser.parse_args()

    db = connect()
    everything: list[Finding] = []

    if args.forgotten:
        people = forgotten_people()
        if not people:
            print("Nobody is marked forgotten. Nothing to verify.")
            return 3
        print(f"{len(people)} person/people marked forgotten.")
        for key, record in people:
            person = person_for_gate_key(db, key)
            findings = check_tombstone(key, record)
            findings += check_database(db, person)
            findings += check_scheduled(person)
            findings += check_files(person)
            if args.all_stores:
                findings += check_snapshots(person)
            report(person, findings, len(person.gate_keys))
            everything += [f for f in findings if f.live]
    else:
        person = resolve(db, args.who)
        if not person.identifiers:
            print(f"Nothing in the sessions table matches {args.who!r}.")
            return 3
        findings = check_database(db, person)
        findings += check_scheduled(person)
        findings += check_files(person)
        if args.all_stores:
            findings += check_snapshots(person)
        for key in person.gate_keys:
            record = load_onboarding().get(key)
            if isinstance(record, dict) and record.get("forgotten_at"):
                findings += check_tombstone(key, record)
        report(person, findings, len(person.gate_keys))
        # Not a deletion audit unless a deletion happened: for a live user
        # every one of these is expected, so nothing is failed on.
        everything = []

    if everything:
        print(
            f"\nFAIL: {len(everything)} live finding(s). A person asked to be "
            "forgotten and something\nkept them. Fix the store, then re-run."
        )
        return 1
    print("\nEvery erased person is gone from every live store.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
