#!/usr/bin/env python3
"""Take a verified copy of everything that cannot be rebuilt.

Roadmap task T05's smallest honest version. T05 wants backup, restore drills
and a record of the last good one; this is the part that had to exist before
T04 moves the runtime, because a migration is exactly when data is lost and on
18 Sep 2026 nothing anywhere held a copy of any of it.

WHAT IS IRREPLACEABLE, and why each one is here:

  state.db              6258 messages, 824 sessions, 265 delivery obligations.
                        `delivery_obligations` is the only record of what users
                        were actually sent; `messages` is the model's raw text
                        and is not the same thing.
  whatsapp/session      the linked device itself. Baileys multi-file auth. Lose
                        it and every user re-pairs by QR, which means explaining
                        yourself to fifty-six people.
  cron/                 60 jobs, 25 enabled. Every reminder a real person is
                        waiting for.
  config.yaml           the model, the fallback, the cache TTL. Not version
                        controlled and it keeps no history, which `ttl_caution`
                        in ted-api-spend.py already complains about.

WHY NOT `cp` FOR THE DATABASE. The gateway is writing to state.db right now. A
plain copy of a live SQLite file can catch a half-written page and produce a
backup that looks fine and restores broken, which is the worst kind. SQLite's
own online backup API takes a consistent snapshot of a database being written,
so that is what runs here.

NOTHING IN ~/.hermes IS EVER WRITTEN. Opening the database read-only is not
decoration: a backup tool that can modify the thing it is backing up is a
backup tool that can lose it.

VERIFICATION IS THE POINT. An unverified backup is a belief, not a backup. Every
copy is checked after it lands: the database against `PRAGMA integrity_check`,
the session by parsing `creds.json` and confirming the device identity is
present, the jobs by parsing the JSON. A failure here exits non-zero and says
which file, because finding out at restore time is finding out too late.

    python3 scripts/ted-backup.py              # take one, verify, report
    python3 scripts/ted-backup.py --list       # what is already held
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

HERMES = Path.home() / ".hermes"
STATE_DB = HERMES / "state.db"
SESSION = HERMES / "whatsapp" / "session"
CRON = HERMES / "cron"
CONFIG = HERMES / "config.yaml"

DESTINATION = Path.home() / "ted-backups"


def snapshot_database(source: Path, target: Path) -> tuple[bool, str]:
    """A consistent copy of a database that is being written to.

    `backup()` is SQLite's online backup: it reads through the same locking the
    gateway uses, so a page cannot be caught half written. The source is opened
    with mode=ro so this can never be the thing that damages state.db.
    """
    if not source.exists():
        return False, f"{source} does not exist"
    try:
        live = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            copy = sqlite3.connect(target)
            try:
                live.backup(copy)
            finally:
                copy.close()
        finally:
            live.close()
    except sqlite3.Error as exc:
        return False, f"snapshot failed: {exc}"
    return True, f"{target.stat().st_size / 1_048_576:.1f} MB"


def verify_database(path: Path) -> tuple[bool, str]:
    """Integrity plus the two tables whose loss would be silent.

    `integrity_check` catches a corrupt file. It does not catch a file that is
    intact and empty, which is why the row counts are read back as well: a
    backup of zero delivery obligations restores cleanly and tells you nothing
    about what anyone was sent.
    """
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                return False, f"integrity_check said {result!r}"
            counts = {}
            for table in ("messages", "delivery_obligations", "sessions"):
                try:
                    counts[table] = connection.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = "missing"
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return False, f"cannot read the copy: {exc}"
    described = ", ".join(f"{name} {value}" for name, value in counts.items())
    return True, described


def verify_session(path: Path) -> tuple[bool, str]:
    """That the copied folder is still a linked device.

    A session directory is only worth having if `creds.json` parses and still
    carries the device identity. Checking the file exists proves nothing: a
    truncated copy exists too, and would be discovered at the worst moment.
    """
    creds = path / "creds.json"
    if not creds.exists():
        return False, "creds.json is missing, this is not a usable session"
    try:
        payload = json.loads(creds.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"creds.json does not parse: {exc}"
    for key in ("noiseKey", "signedIdentityKey", "registrationId", "me"):
        if key not in payload:
            return False, f"creds.json has no {key}, the device identity is incomplete"
    files = sum(1 for _ in path.iterdir())
    return True, f"{files} files, device identity present"


def verify_cron(path: Path) -> tuple[bool, str]:
    """That jobs.json parses and still holds jobs."""
    jobs = path / "jobs.json"
    if not jobs.exists():
        return True, "no jobs.json in this copy"
    try:
        payload = json.loads(jobs.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"jobs.json does not parse: {exc}"
    if isinstance(payload, dict):
        total = len(payload.get("jobs", payload))
    else:
        total = len(payload)
    return True, f"{total} job(s)"


def take_backup() -> int:
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    target = DESTINATION / stamp
    target.mkdir(parents=True, exist_ok=True)
    print(f"Backing up to {target}\n")

    failures: list[str] = []

    ok, detail = snapshot_database(STATE_DB, target / "state.db")
    print(f"  state.db      {'copied ' + detail if ok else 'FAILED: ' + detail}")
    if ok:
        ok, detail = verify_database(target / "state.db")
        print(f"                {'verified, ' + detail if ok else 'VERIFY FAILED: ' + detail}")
    if not ok:
        failures.append("state.db")

    if SESSION.exists():
        shutil.copytree(SESSION, target / "session", dirs_exist_ok=True)
        ok, detail = verify_session(target / "session")
        print(f"  session       {'verified, ' + detail if ok else 'VERIFY FAILED: ' + detail}")
        if not ok:
            failures.append("session")
    else:
        print("  session       FAILED: not found")
        failures.append("session")

    if CRON.exists():
        shutil.copytree(CRON, target / "cron", dirs_exist_ok=True)
        ok, detail = verify_cron(target / "cron")
        print(f"  cron          {'verified, ' + detail if ok else 'VERIFY FAILED: ' + detail}")
        if not ok:
            failures.append("cron")
    else:
        print("  cron          FAILED: not found")
        failures.append("cron")

    if CONFIG.exists():
        shutil.copyfile(CONFIG, target / "config.yaml")
        print(f"  config.yaml   copied {CONFIG.stat().st_size} bytes")
    else:
        print("  config.yaml   FAILED: not found")
        failures.append("config.yaml")

    # The record of the last good one. T05 asks for it by name, and without it
    # "when did we last back up" is answered by looking at folder names and
    # hoping.
    receipt = {
        "taken_at": time.time(),
        "taken_at_readable": stamp,
        "verified": not failures,
        "failures": failures,
    }
    (target / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    if failures:
        print(f"\n  INCOMPLETE. Failed: {', '.join(failures)}")
        print("  Do not move hosts on this backup.")
        return 1
    print(f"\n  Verified. {target}")
    return 0


def list_backups() -> int:
    if not DESTINATION.exists():
        print("No backups have ever been taken.")
        return 1
    rows = sorted(p for p in DESTINATION.iterdir() if p.is_dir())
    if not rows:
        print("No backups have ever been taken.")
        return 1
    for path in rows:
        try:
            receipt = json.loads((path / "receipt.json").read_text(encoding="utf-8"))
            mark = "verified" if receipt.get("verified") else "INCOMPLETE"
        except (OSError, ValueError):
            mark = "no receipt, treat as unverified"
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"  {path.name}  {size / 1_048_576:>7.1f} MB  {mark}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    return list_backups() if args.list else take_backup()


if __name__ == "__main__":
    sys.exit(main())
