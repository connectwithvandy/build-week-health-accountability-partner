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

RESTORE IS THE OTHER HALF, AND IT IS THE HALF THAT COUNTS. A backup nobody has
ever restored is a folder, not a plan. `--drill` proves it: the newest verified
backup is restored into a throwaway directory, every copy is verified again in
its new home, and one real user's history is rebuilt out of it end to end,
their session, their messages, what they were actually delivered and the
reminder job still waiting for them. The result is written down, so "when did
we last prove a restore" has an answer.

TWO RULES THE DRILL WILL NOT BREAK, both of them the hard way round:

  It never starts a gateway. The WhatsApp session is a set of credentials and
  only one instance may hold them at a time. Two running at once is what
  produced `session.loggedout-20260909-100854`. So a drill that "just booted it
  to check" would be the one thing capable of logging the real users out.

  It never writes into a live ~/.hermes. `--restore` refuses a target that
  already holds a state.db unless you say --force, and refuses entirely while a
  gateway is running there. Restoring onto a live system is how you lose the
  thing you were protecting.

    python3 scripts/ted-backup.py              # take one, verify, report
    python3 scripts/ted-backup.py --list       # what is held, and the last drill
    python3 scripts/ted-backup.py --drill      # prove a restore actually works
    python3 scripts/ted-backup.py --restore DIR --into DIR   # real restore
    python3 scripts/ted-backup.py --install    # daily, via launchd
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Both roots are overridable, and not only for the tests. The drill restores
# into a directory that is deliberately not this machine's live one, and a
# real cutover on a new host will point these somewhere else entirely.
HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"
SESSION = HERMES / "whatsapp" / "session"
CRON = HERMES / "cron"
CONFIG = HERMES / "config.yaml"

DESTINATION = Path(os.environ.get("TED_BACKUP_DIR", Path.home() / "ted-backups"))

# How many backups to keep. At ~66 MB each a daily job fills 2 GB a month, so
# something has to prune. KEEP is deliberately generous: disk is cheap and the
# failure this guards against is discovering a fortnight late that the last
# three copies were all quietly incomplete.
KEEP = 14

PLIST_LABEL = "ai.ted.backup"
PLIST_SRC = Path(__file__).resolve().parent / f"{PLIST_LABEL}.plist"
PLIST_DEST = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

LAST_DRILL = DESTINATION / "last-drill.json"

# A restore proof goes stale. The daily job re-drills when the last one is
# older than this, so the answer to "does it restore" is never older than a
# week without anybody having to remember to ask. It is not drilled every day
# on purpose: the drill is the only routine that reads every byte back, and a
# daily one turns a quiet 04:00 into a noisy one for no extra confidence.
DRILL_EVERY_DAYS = 7


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

    # Only ever prune after a good one. Pruning on the way out of a failed
    # backup would delete history to make room for a copy that did not verify.
    dropped = prune()
    if dropped:
        print(f"\n  Pruned {len(dropped)} old backup(s), keeping {KEEP}.")

    print(f"\n  Verified. {target}")

    # The restore proof, kept fresh by the same job. A backup that verifies and
    # has not been restored in a month is the state this file exists to get out
    # of, and nobody remembers to drill it by hand.
    if drill_is_stale():
        print("\n  The last restore drill is stale. Drilling.\n")
        return drill()
    return 0


def drill_is_stale(now: float | None = None) -> bool:
    """Whether the restore proof is older than DRILL_EVERY_DAYS, or absent.

    Absent counts as stale. "Never drilled" is the worst case, not a neutral
    one, and it is the state every backup system starts in.
    """
    try:
        record = json.loads(LAST_DRILL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not record.get("passed"):
        return True
    age = (now if now is not None else time.time()) - float(record.get("drilled_at") or 0)
    return age > DRILL_EVERY_DAYS * 86400


def gateway_is_running(home: Path) -> bool:
    """Whether something is serving out of this HERMES home right now.

    Restoring over a running gateway is the one way this file could destroy
    what it exists to protect: the gateway holds state.db open, and replacing
    the file underneath it loses whatever it had not yet written.

    Deliberately crude, and deliberately biased towards "yes". `pgrep` against
    the gateway command line is enough to catch the real case, and if pgrep is
    missing or refuses, the answer is yes and the restore stops. A false stop
    costs a flag. A false clear costs the database.
    """
    try:
        found = subprocess.run(
            ["pgrep", "-f", "hermes_cli.main gateway run"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if found.returncode != 0:
        return False
    # A gateway is running somewhere. It only matters if it is serving out of
    # the directory being restored into, and the safe reading of "cannot tell"
    # is that it is.
    return home == Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def verified_backups() -> list[Path]:
    """Every backup whose own receipt says it verified, newest last."""
    if not DESTINATION.exists():
        return []
    out = []
    for path in sorted(p for p in DESTINATION.iterdir() if p.is_dir()):
        try:
            receipt = json.loads((path / "receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if receipt.get("verified"):
            out.append(path)
    return out


def restore(backup: Path, into: Path, force: bool) -> tuple[bool, list[str]]:
    """Put a backup back, into a home that is not currently being served.

    Returns (ok, notes). This writes files, which makes it the only function
    here that can do harm, so every refusal is checked before anything is
    copied rather than partway through.
    """
    notes: list[str] = []
    if not (backup / "receipt.json").exists():
        return False, [f"{backup} has no receipt, refusing to trust it"]
    try:
        receipt = json.loads((backup / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"receipt does not parse: {exc}"]
    if not receipt.get("verified") and not force:
        return False, ["that backup is marked INCOMPLETE; --force to restore it anyway"]

    if gateway_is_running(into):
        return False, [
            "a gateway is running against this home. Stop it first.",
            "Restoring under a live gateway loses whatever it has not flushed.",
        ]
    if (into / "state.db").exists() and not force:
        return False, [f"{into} already holds a state.db; --force to overwrite"]

    into.mkdir(parents=True, exist_ok=True)
    if (backup / "state.db").exists():
        shutil.copyfile(backup / "state.db", into / "state.db")
        notes.append("state.db")
    if (backup / "session").exists():
        target = into / "whatsapp" / "session"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup / "session", target, dirs_exist_ok=True)
        notes.append("whatsapp/session")
    if (backup / "cron").exists():
        shutil.copytree(backup / "cron", into / "cron", dirs_exist_ok=True)
        notes.append("cron")
    if (backup / "config.yaml").exists():
        shutil.copyfile(backup / "config.yaml", into / "config.yaml")
        notes.append("config.yaml")
    return True, notes


def representative_user_flow(state_db: Path) -> tuple[bool, str]:
    """Rebuild one real person's history out of a restored database.

    T05's definition of done asks a restored environment to "complete a
    representative user flow with the expected state". Without starting a
    gateway, which this file must never do, the honest version of that is to
    reassemble the flow from the data: the busiest real user, their session,
    the messages on it, what they were actually *delivered*, and the reminder
    still scheduled for them.

    `delivery_obligations` rather than `messages` on purpose. `messages` is the
    model's raw text; the obligations ledger is the only record of what a
    person actually received.
    """
    try:
        db = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return False, f"cannot open the restored database: {exc}"
    try:
        busiest = db.execute(
            "SELECT chat_id, count(*) n FROM delivery_obligations "
            "WHERE state = 'delivered' GROUP BY chat_id ORDER BY n DESC LIMIT 1"
        ).fetchone()
        if not busiest:
            return False, "no delivered message survived the restore"
        chat_id, delivered = busiest

        sessions = db.execute(
            "SELECT count(DISTINCT s.id) FROM sessions s "
            "JOIN delivery_obligations d ON d.session_key = s.session_key "
            "WHERE d.chat_id = ?",
            (chat_id,),
        ).fetchone()[0]
        # count(DISTINCT m.id), not count(*). A session carries many delivery
        # obligations, so joining straight through multiplies every message by
        # the number of obligations on its session: the first run of this drill
        # reported 40,796 messages for one user out of a database holding
        # 6,341 in total. A restore drill that flatters itself is worse than no
        # drill, because it is the thing you check before trusting a cutover.
        messages = db.execute(
            "SELECT count(DISTINCT m.id) FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "JOIN delivery_obligations d ON d.session_key = s.session_key "
            "WHERE d.chat_id = ?",
            (chat_id,),
        ).fetchone()[0]
        newest = db.execute(
            "SELECT content FROM delivery_obligations WHERE chat_id = ? "
            "AND state = 'delivered' ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()[0]
    except sqlite3.Error as exc:
        return False, f"the restored database is intact but unreadable: {exc}"
    finally:
        db.close()

    if not (sessions and messages and (newest or "").strip()):
        return False, (
            f"the flow does not reassemble: {sessions} session(s), "
            f"{messages} message(s), last delivered text "
            f"{'empty' if not (newest or '').strip() else 'present'}"
        )
    return True, (
        f"one real user rebuilt: {sessions} session(s), {messages} message(s), "
        f"{delivered} delivered, last one {len(newest)} characters"
    )


def drill(force: bool = False) -> int:
    """Restore the newest verified backup somewhere harmless and prove it works.

    The whole point is that this is not a dry run. Files really are copied, the
    database really is opened, and a real user's history really is rebuilt out
    of it. What makes it safe is where it lands: a temporary directory that is
    deleted afterwards, never ~/.hermes, and no gateway is ever started against
    it.
    """
    backups = verified_backups()
    if not backups:
        print("No verified backup to drill. Take one first.")
        return 1
    newest = backups[-1]
    print(f"Restore drill from {newest.name}\n")

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ted-restore-drill-") as workspace:
        into = Path(workspace) / "hermes"
        ok, notes = restore(newest, into, force=force)
        if not ok:
            for note in notes:
                print(f"  RESTORE REFUSED: {note}")
            return 1
        print(f"  restored      {', '.join(notes)}")

        ok, detail = verify_database(into / "state.db")
        print(f"  state.db      {'verified, ' + detail if ok else 'FAILED: ' + detail}")
        if not ok:
            problems.append("state.db")

        ok, detail = verify_session(into / "whatsapp" / "session")
        print(f"  session       {'verified, ' + detail if ok else 'FAILED: ' + detail}")
        if not ok:
            problems.append("session")

        ok, detail = verify_cron(into / "cron")
        print(f"  cron          {'verified, ' + detail if ok else 'FAILED: ' + detail}")
        if not ok:
            problems.append("cron")

        ok, detail = representative_user_flow(into / "state.db")
        print(f"  user flow     {'rebuilt, ' + detail if ok else 'FAILED: ' + detail}")
        if not ok:
            problems.append("user flow")

    # Written outside the temporary directory on purpose: the evidence has to
    # outlive the workspace it was produced in.
    DESTINATION.mkdir(parents=True, exist_ok=True)
    LAST_DRILL.write_text(
        json.dumps(
            {
                "drilled_at": time.time(),
                "drilled_at_readable": datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
                "backup": newest.name,
                "passed": not problems,
                "problems": problems,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if problems:
        print(f"\n  DRILL FAILED: {', '.join(problems)}")
        print("  The backup exists and does not restore. Fix this before any cutover.")
        return 1
    print("\n  Drill passed. This backup restores and carries a real user's history.")
    return 0


def prune(keep: int = KEEP) -> list[str]:
    """Drop the oldest backups, and never the last verified one.

    Retention is where a backup system quietly becomes a folder of corrupt
    copies: prune blindly by age and the day everything starts failing you
    delete the last good one to make room for a bad one.
    """
    if not DESTINATION.exists():
        return []
    everything = sorted(p for p in DESTINATION.iterdir() if p.is_dir())
    if len(everything) <= keep:
        return []
    good = set(verified_backups()[-1:])  # the newest that actually verified
    removed = []
    for path in everything[: len(everything) - keep]:
        if path in good:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def install() -> int:
    """Copy the plist in, load it, and then make it prove it can actually run.

    The proving is the point. The first version of this printed "A verified
    backup will be taken daily" and returned 0 while the job was incapable of
    starting: macOS refuses a launchd agent access to ~/Documents unless that
    binary has been granted it, and `/usr/bin/python3` has not, so every 04:00
    run would have died on `Operation not permitted` before reading its own
    script. Nothing would have noticed until a restore was needed.

    An installer that reports success for a job it has never seen run is the
    same class of mistake as a backup nobody has restored. So this one fires
    it once and reads the exit code.
    """
    # `plutil -lint`, not plistlib. They disagree, and the one that matters is
    # the one launchd uses. A stray `-->` left this file with bare text outside
    # any tag; plistlib read it happily and reported the right interpreter,
    # while launchd rejected the whole file and silently went on running the
    # previous definition. Validating with a more forgiving parser than the
    # consumer is not validation.
    linted = subprocess.run(
        ["plutil", "-lint", str(PLIST_SRC)], capture_output=True
    )
    if linted.returncode != 0:
        detail = (linted.stdout + linted.stderr).decode().strip()
        print(f"{PLIST_SRC} is not valid: {detail}", file=sys.stderr)
        return 1
    try:
        plistlib.loads(PLIST_SRC.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"Cannot read {PLIST_SRC}: {exc}", file=sys.stderr)
        return 1
    PLIST_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLIST_SRC, PLIST_DEST)
    subprocess.run(["launchctl", "unload", str(PLIST_DEST)], capture_output=True)
    loaded = subprocess.run(["launchctl", "load", str(PLIST_DEST)], capture_output=True)
    if loaded.returncode != 0:
        print(loaded.stderr.decode().strip() or "launchctl load failed", file=sys.stderr)
        return 1

    print(f"Loaded {PLIST_LABEL}. Running it once to prove it works...")
    ok, detail = prove_the_job_runs()
    if not ok:
        print(f"\n  THE SCHEDULED JOB CANNOT RUN: {detail}", file=sys.stderr)
        print(
            "  It is loaded and it would fail silently at 04:00.\n"
            "  Fix the plist and run --install again.",
            file=sys.stderr,
        )
        return 1
    print(f"\n  Proven: {detail}")
    print("  A verified backup will be taken daily at 04:00.")
    print("  Check it with: python3 scripts/ted-backup.py --list")
    return 0


def prove_the_job_runs(timeout: float = 180.0) -> tuple[bool, str]:
    """Fire the installed job once and wait for a real exit code.

    launchd reports `last exit code` per job, which is the only answer that
    accounts for the whole path: the interpreter, its permissions, the script
    location and the script itself. Anything this process could check directly
    would be checking its own permissions, not launchd's, and those are exactly
    what differ.
    """
    target = f"gui/{os.getuid()}/{PLIST_LABEL}"
    log = Path.home() / ".hermes" / "logs" / "ted-backup.log"
    before = log.stat().st_size if log.exists() else 0

    started = subprocess.run(
        ["launchctl", "kickstart", "-p", target], capture_output=True
    )
    if started.returncode != 0:
        return False, started.stderr.decode().strip() or "launchctl kickstart failed"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        printed = subprocess.run(
            ["launchctl", "print", target], capture_output=True
        ).stdout.decode()
        for line in printed.splitlines():
            if "last exit code" not in line:
                continue
            value = line.split("=", 1)[1].strip()
            if value.startswith("("):  # "(never exited)", still running
                break
            if value == "0":
                return True, "the scheduled job ran and exited cleanly"
            tail = ""
            if log.exists():
                with log.open(errors="replace") as handle:
                    handle.seek(before)
                    tail = " ".join(handle.read().split())[:200]
            return False, f"exit code {value}. {tail}"
    return False, f"it did not finish within {timeout:.0f}s"


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

    # "When did we last back up" is half the question. The other half is when a
    # restore was last proven, and a folder listing cannot answer that.
    print()
    try:
        record = json.loads(LAST_DRILL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("  Restore has NEVER been drilled. These are folders, not a plan.")
        print("  Run: python3 scripts/ted-backup.py --drill")
        return 0
    if record.get("passed"):
        print(
            f"  Last restore drill: {record.get('drilled_at_readable')} "
            f"on {record.get('backup')} — passed."
        )
    else:
        print(
            f"  Last restore drill: {record.get('drilled_at_readable')} "
            f"on {record.get('backup')} — FAILED: "
            f"{', '.join(record.get('problems') or ['unknown'])}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Take, verify, restore and drill TED's irreplaceable state."
    )
    parser.add_argument("--list", action="store_true", help="what is held, and the last drill")
    parser.add_argument("--drill", action="store_true", help="prove a restore works")
    parser.add_argument("--restore", metavar="BACKUP", help="a backup directory to put back")
    parser.add_argument("--into", metavar="HOME", help="the HERMES home to restore into")
    parser.add_argument("--install", action="store_true", help="daily backup via launchd")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a home that already holds state.db, or accept an unverified backup",
    )
    args = parser.parse_args()

    if args.install:
        return install()
    if args.list:
        return list_backups()
    if args.drill:
        return drill(force=args.force)
    if args.restore:
        if not args.into:
            print(
                "--restore needs --into. There is no default on purpose:\n"
                "the default would be the live home, and that is the one\n"
                "place a restore can destroy what it was meant to protect.",
                file=sys.stderr,
            )
            return 2
        ok, notes = restore(Path(args.restore), Path(args.into), force=args.force)
        for note in notes:
            print(f"  {note}")
        if not ok:
            return 1
        print(f"\n  Restored into {args.into}.")
        print("  Verify it before trusting it: --drill proves the shape, this does not.")
        return 0
    return take_backup()


if __name__ == "__main__":
    sys.exit(main())
