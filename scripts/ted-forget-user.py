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

WHAT THIS CANNOT REACH, and says so every run rather than implying it is clean.

The logs were on this list until 18 Sep 2026, when Hermes patch 14 stopped the
writing and `ted-log-retention.py` redacted the 4,998 lines already there. They
are no longer a store of user words. Two things took their place, both found by
`ted-deletion-audit.py` and neither fixed here:

  * `channel_directory.json` names every chat the gateway routes to, and
    nothing removes a deleted person from it.
  * Snapshots. Nine repair scripts write a `.bak` before touching a profile,
    `ted-backup.py` copies the state daily, and both are deliberate. A backup
    that forgets on demand is not a backup. They are retention rather than
    leakage, and the audit reports them separately so the distinction is
    somebody's decision instead of an accident.

Run `npm run deletion:audit` after this, which is the half T09 asks for and
this script never did: proof rather than an assumption.

Dry run by default. Nothing is deleted without --apply, and --apply prints the
name and the message count and asks, because the one thing worse than a
deletion nobody performed is a deletion performed on the wrong person.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
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

# The gate keeps its own copy of age, weight, goal and target, keyed by a hash
# rather than a number. `_forget_user` clears the live file when somebody is
# deleted. It does not clear the snapshots beside it, and nothing else does
# either: nine repair scripts write one before touching a profile and none of
# them ever comes back for it. On 17 Sep 2026 there were twenty, holding all
# 55 users. This reports them. It does not delete them yet.
GATE_STATE_DIR = HERMES / "state"
CRON_JOBS = HERMES / "cron" / "jobs.json"
CHANNEL_DIRECTORY = HERMES / "channel_directory.json"
LID_MAP_GLOB = "whatsapp/lid-phone-map-*.json"


# Voice notes are not findable the way photos are.
#
# `media_for` scrapes paths out of message text, which works for images: all 7
# on disk on 17 Sep 2026 were found that way. Not one of the 29 voice notes
# was. A voice note is transcribed on arrival, so the message holds the words
# and never the path, and nothing else in the database holds it either: not
# `api_content`, not `tool_calls`, not `delivery_obligations`, not the session
# dumps. Somebody's voice describing their meals therefore survived "delete my
# data" completely, and nothing could even say whose it was.
#
# Time is the only link left. A voice note is written when it arrives, and the
# message it produced lands seconds later. At +/-60s every one of the 29 real
# files resolved to exactly one person, none ambiguous, none unowned; the
# window only smears at 180s (2 ambiguous) and 600s (7).
#
# The rule is exactly-one-owner. Nobody matching, or two people matching, means
# the file is reported and left. Leaving one behind is visible and fixable by
# hand. Deleting somebody else's voice note is neither.
VOICE_WINDOW_SECONDS = 60


def _person_identifiers(session_ids: list[str]) -> set[str]:
    if not session_ids:
        return set()
    con = connect_ro()
    try:
        marks = ",".join("?" * len(session_ids))
        rows = con.execute(
            "select distinct coalesce(user_id,''), coalesce(chat_id,'') "
            f"from sessions where id in ({marks})",
            session_ids,
        ).fetchall()
    finally:
        con.close()
    return {value for row in rows for value in row if value}


def unreferenced_audio_for(
    session_ids: list[str], window: float = VOICE_WINDOW_SECONDS
) -> tuple[list[Path], list[Path]]:
    """(this person's voice notes, the ones too ambiguous to touch)."""
    mine = _person_identifiers(session_ids)
    if not mine:
        return [], []
    con = connect_ro()
    try:
        stamps = con.execute(
            "select m.timestamp, coalesce(s.user_id, s.chat_id, '') "
            "from messages m join sessions s on m.session_id = s.id "
            "where s.source='whatsapp' and m.role='user' and m.timestamp is not null"
        ).fetchall()
    finally:
        con.close()

    owned: list[Path] = []
    ambiguous: list[Path] = []
    audio_dir = HERMES / "cache" / "audio"
    if not audio_dir.is_dir():
        return owned, ambiguous
    for path in sorted(audio_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            when = path.stat().st_mtime
        except OSError:
            continue
        owners = {who for stamp, who in stamps if who and abs(stamp - when) <= window}
        if owners == mine or (len(owners) == 1 and owners <= mine):
            owned.append(path)
        elif owners & mine:
            ambiguous.append(path)
    return owned, ambiguous


def gate_key(sender_id: str) -> str:
    """The gate's key for one user, derived the way the gate derives it.

    Mirrors `_user_state_key` in hermes/ted_safety_gates/__init__.py. Copied
    rather than imported because this has to run with the gateway stopped and
    the plugin possibly uninstalled. If that function ever changes, this finds
    nothing and says so rather than reporting a clean result: the count of
    derived keys is printed next to the count of records found, so a silent
    miss reads as 2 keys, 0 records instead of looking like success.
    """
    identity = f"whatsapp:{sender_id}".encode("utf-8")
    return f"whatsapp:sha256:{hashlib.sha256(identity).hexdigest()}"


def gate_keys_for(session_ids: list[str]) -> set[str]:
    """Every gate key this person's sessions could be stored under."""
    if not session_ids:
        return set()
    con = connect_ro()
    try:
        marks = ",".join("?" * len(session_ids))
        rows = con.execute(
            "select distinct coalesce(user_id,''), coalesce(chat_id,'') "
            f"from sessions where id in ({marks})",
            session_ids,
        ).fetchall()
    finally:
        con.close()
    return {gate_key(value) for row in rows for value in row if value}


def scrub_gate_snapshots(keys: set[str]) -> tuple[int, int, list[str]]:
    """Remove these keys from the snapshots, leaving every other user intact.

    Snapshots only. The live files belong to the running gateway, which
    rewrites them wholesale from memory, so editing one from out here either
    loses to the gateway or clobbers state newer than what we read. The gate's
    own `_forget_user` already clears the live pair and leaves a tombstone;
    this is the half nothing owned.

    One key is removed, never the file. Nine repair scripts write these before
    touching a profile and they are the only undo those scripts have. Dropping
    a snapshot to erase one person would take the rollback away from the other
    fifty-four.
    """
    scrubbed_files = 0
    scrubbed_records = 0
    failures: list[str] = []
    if not keys or not GATE_STATE_DIR.is_dir():
        return 0, 0, failures

    for path in sorted(GATE_STATE_DIR.glob("ted-safety-gates-*.json*")):
        if path.name.endswith(".json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Already unreadable, so it is not a store anybody can restore
            # from. Left alone rather than rewritten into something that looks
            # repaired.
            continue
        if not isinstance(payload, dict):
            continue

        removed = 0
        listed = payload.get("user_keys")
        if isinstance(listed, list):
            kept = [k for k in listed if k not in keys]
            removed = len(listed) - len(kept)
            if removed:
                payload["user_keys"] = kept
        else:
            users = payload.get("users") if isinstance(payload.get("users"), dict) else payload
            for key in keys & set(users):
                del users[key]
                removed += 1
        if not removed:
            continue

        temporary = path.with_name(path.name + ".scrub.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            failures.append(f"{path.name}: {error}")
            continue
        scrubbed_files += 1
        scrubbed_records += removed

    return scrubbed_files, scrubbed_records, failures


def gate_records_for(keys: set[str]) -> list[tuple[Path, str, list[str]]]:
    """Gate state files still holding a record for these keys.

    A file whose name still ends in .json is the live one the gate maintains.
    Everything else is a snapshot somebody took by hand.
    """
    found: list[tuple[Path, str, list[str]]] = []
    if not keys or not GATE_STATE_DIR.is_dir():
        return found
    for path in sorted(GATE_STATE_DIR.glob("ted-safety-gates-*.json*")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        # the disclosure file is a list of keys, the onboarding file a map
        listed = payload.get("user_keys")
        if isinstance(listed, list):
            for key in sorted(keys & set(listed)):
                found.append((path, key, ["disclosure-sent"]))
            continue
        users = payload.get("users", payload)
        if not isinstance(users, dict):
            continue
        for key in sorted(keys & set(users)):
            record = users[key]
            found.append((path, key, sorted(record) if isinstance(record, dict) else []))
    return found


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


def cron_jobs_for(chats: list[str]) -> list[dict]:
    """Scheduled reminders that would still fire at somebody who left.

    T09 asks for future reminders to be cancelled and nothing did it. Udayan
    had none, so this has never actually happened — it was unexercised, not
    safe, and "the deleted person got a nudge" is the one failure here a real
    person would feel rather than read about in an audit.

    A job carries its target in `origin`, which holds `chat_id`, `user_id`
    **and `chat_name`** — so the job file is a store of their display name
    too, not only of an identifier.
    """
    if not CRON_JOBS.exists():
        return []
    wanted = {c for c in chats if c}
    found = []
    for job in json.loads(CRON_JOBS.read_text(encoding="utf-8")).get("jobs", []):
        origin = job.get("origin") or {}
        if not isinstance(origin, dict):
            continue
        if {origin.get("chat_id"), origin.get("user_id")} & wanted:
            found.append(job)
    return found


def channel_entries_for(chats: list[str]) -> list[tuple[str, dict]]:
    """Routing targets naming this person, by platform."""
    if not CHANNEL_DIRECTORY.exists():
        return []
    wanted = {c for c in chats if c}
    payload = json.loads(CHANNEL_DIRECTORY.read_text(encoding="utf-8"))
    found = []
    for platform, entries in (payload.get("platforms") or {}).items():
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("id") in wanted:
                found.append((platform, entry))
    return found


def lid_map_entries_for(chats: list[str]) -> list[tuple[Path, str]]:
    """The lid-to-phone mapping, which is the link between their two ids."""
    wanted = {c.split("@")[0] for c in chats if c} | {c for c in chats if c}
    found = []
    for path in sorted(HERMES.glob(LID_MAP_GLOB)):
        mapping = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if key in wanted or str(value) in wanted:
                found.append((path, key))
    return found


def _rewrite(path: Path, payload: object) -> None:
    """Back up beside the file, then replace it atomically."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    path.with_name(f"{path.name}.bak.pre-forget-{stamp}").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


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
    voice, voice_ambiguous = unreferenced_audio_for(session_ids)
    print(f"  {len(media):>5}  photos and voice notes found by path")
    print(f"  {len(voice):>5}  voice notes matched by arrival time "
          f"(+/-{VOICE_WINDOW_SECONDS:g}s, one owner only)")
    if voice_ambiguous:
        print(f"  {len(voice_ambiguous):>5}  voice note(s) LEFT: more than one person "
              f"was messaging at that moment")
        for path in voice_ambiguous[:4]:
            print(f"         {path}")
    for p in media[:8]:
        print(f"         {p}")
    if len(media) > 8:
        print(f"         ... and {len(media) - 8} more")

    keys = gate_keys_for(session_ids)
    records = gate_records_for(keys)
    live = [r for r in records if r[0].name.endswith(".json")]
    snapshots = [r for r in records if not r[0].name.endswith(".json")]
    print(f"\n  {len(records):>5}  gate state records, from {len(keys)} derived key(s)")
    for path, _key, fields in live:
        print(f"         live   {path.name}  [{', '.join(fields[:6])}]")
    for path, _key, fields in snapshots:
        print(f"         SNAP   {path.name}  [{', '.join(fields[:6])}]")
    if keys and not records:
        print("         none. Either this person never reached the gate, or the")
        print("         key derivation no longer matches the gate's. Check before")
        print("         treating this as clean.")
    if snapshots:
        print(f"\n  {len(snapshots)} snapshot(s) will have this one record removed.")
        print("  The files stay: they are the undo for the repair scripts, and the")
        print("  other users in them are untouched.")
    if live:
        print("\n  the live file(s) above are left to the gate's own _forget_user,")
        print("  which clears them and leaves a tombstone. Editing them from here")
        print("  would race the running gateway.")

    # The log was on this line until 18 Sep 2026. Patch 14 stopped Hermes
    # writing user text and ted-log-retention.py redacted what was there, so
    # naming it here now would send somebody to check a store that no longer
    # holds words. What replaced it is not reachable from here either, and
    # saying nothing would be the same mistake in the other direction.
    # Three stores that nothing reached until 19 Sep 2026. All three are
    # addressed by the same chat id the rest of this script resolves, so the
    # only reason they were left is that nobody had declared them.
    jobs = cron_jobs_for(c["chats"])
    channels = channel_entries_for(c["chats"])
    lid_rows = lid_map_entries_for(c["chats"])

    enabled = [j for j in jobs if j.get("enabled")]
    print(f"\n  {len(jobs):>5}  scheduled reminders, {len(enabled)} of them enabled")
    for job in jobs[:8]:
        state = "enabled" if job.get("enabled") else "disabled"
        print(f"         {job.get('id')}  {state:8}  {job.get('name')}")
    if enabled:
        print("         these would still fire at somebody who asked to be erased.")
    print(f"  {len(channels):>5}  routing entries in channel_directory.json")
    for platform, entry in channels[:4]:
        # The name, not only the id: this file stores both.
        print(f"         {platform}: {entry.get('name')}")
    print(f"  {len(lid_rows):>5}  rows in the lid-to-phone map, which links their two ids")

    print("\n  still not reachable from here: snapshots and ~/ted-backups keep a")
    print("  copy on purpose — a backup that forgets on demand is not a backup.")
    print("  Prove what is left rather than assuming: npm run deletion:audit")

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
    for path in list(media) + list(voice):
        if not any(path.is_relative_to(root) for root in DELETABLE_ROOTS):
            continue
        try:
            path.unlink()
            removed_media += 1
        except OSError as error:
            print(f"  could not remove {path}: {error}")

    rows = delete_rows("delivery_obligations", "chat_id", c["chats"])
    rows += delete_rows("gateway_routing", "session_key", c["keys"])

    # `keys` was derived above, before this block. It has to be: the derivation
    # reads the sessions table and `hermes sessions delete` below destroys it,
    # so deriving here would find nothing and report a clean scrub. Same class
    # of ordering constraint as the media collection.
    scrubbed_files, scrubbed_records, scrub_failures = scrub_gate_snapshots(keys)
    for failure in scrub_failures:
        print(f"  could not scrub {failure}")

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

    # Cron first, because it is the only one of the three that would reach
    # the person. `hermes cron remove` rather than an edit to jobs.json: the
    # CLI owns that schema, and a hand-written rewrite is how `next_run_at`
    # ends up null and a *different* person's reminder silently stops.
    removed_jobs = 0
    for job in jobs:
        result = subprocess.run(
            ["hermes", "cron", "remove", str(job.get("id"))],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            removed_jobs += 1
        else:
            print(f"  cron job {job.get('id')} failed: "
                  f"{(result.stderr or result.stdout).strip()[:120]}")

    # Re-read both files immediately before writing. The gateway appends to
    # the directory as it routes, so anything read at the top of this run is
    # already minutes stale, and writing that back would undo somebody else's
    # entry to remove this one.
    removed_channels = 0
    if channels and CHANNEL_DIRECTORY.exists():
        payload = json.loads(CHANNEL_DIRECTORY.read_text(encoding="utf-8"))
        wanted = {ch for ch in c["chats"] if ch}
        for platform, entries in (payload.get("platforms") or {}).items():
            kept = [e for e in entries or []
                    if not (isinstance(e, dict) and e.get("id") in wanted)]
            removed_channels += len(entries or []) - len(kept)
            payload["platforms"][platform] = kept
        if removed_channels:
            _rewrite(CHANNEL_DIRECTORY, payload)

    removed_lid = 0
    for path in sorted({path for path, _ in lid_map_entries_for(c["chats"])}):
        mapping = json.loads(path.read_text(encoding="utf-8"))
        wanted = {ch.split("@")[0] for ch in c["chats"] if ch} | {
            ch for ch in c["chats"] if ch
        }
        kept = {k: v for k, v in mapping.items()
                if k not in wanted and str(v) not in wanted}
        removed_lid += len(mapping) - len(kept)
        if len(kept) != len(mapping):
            _rewrite(path, kept)

    print(f"\n  {removed_jobs}/{len(jobs)} scheduled reminders cancelled, "
          f"{removed_channels} routing entr(ies) removed, "
          f"{removed_lid} lid-map row(s) removed.")
    print(f"  {deleted_sessions}/{len(session_ids)} sessions deleted, "
          f"{removed_media} media files removed, {rows} other rows removed.")
    print(f"  {scrubbed_records} gate record(s) scrubbed from "
          f"{scrubbed_files} snapshot(s).")
    if voice_ambiguous:
        print(f"  {len(voice_ambiguous)} voice note(s) deliberately left: one owner "
              "could not be established.")
    print("  Convex is a separate half and is untouched: the user's own "
          "\"delete my data\" does that.\n")
    return 0 if deleted_sessions == len(session_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
