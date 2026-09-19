#!/usr/bin/env python3
"""Take users' words back out of the logs, and stop them piling up.

Roadmap task T35. Ted's logs recorded every inbound WhatsApp message in the
clear, next to the sender's name:

    inbound message: platform=whatsapp user=Ankiita chat=115650651500637@lid
    msg='Soya aur paneer ka koi combo hota he kya sabji me'

That is a health record in a text file with no retention and no access control.
`ted-forget-user.py` says plainly that it cannot reach it, so "delete my data"
was never true of the logs. Hermes patch 14 closes the tap; this drains what is
already in the bucket.

WHAT IT TOUCHES, AND WHAT IT WILL NOT.

A log the gateway has open is left alone. Rewriting a file another process is
appending to does not shorten it, it corrupts it: the writer keeps its old
offset and the next line lands past the end, leaving a hole. The live log is
reported and never edited, which is the same rule `ted-forget-user.py` already
states. Stop the gateway and the same command will clean it.

REDACTION, NOT DELETION, for anything still inside the retention window. The
line stays, its timestamp stays, the user and chat stay, and the words become
`<41 chars withheld>`. An operator can still see that a message arrived, from
whom and when, which is what the log is for. Deleting the lines outright would
destroy the ability to answer "was this person answered at all", which is a
question that has already mattered here.

    python3 scripts/ted-log-retention.py            # what is exposed
    python3 scripts/ted-log-retention.py --scrub    # redact what is safe to
    python3 scripts/ted-log-retention.py --days 30  # and delete older rotations
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
LOG_DIR = HERMES / "logs"

# Both halves of what Hermes logged: the gateway's inbound line and the agent's
# turn line both render the text with %r, so it arrives as a Python repr. The
# pattern matches a quoted repr including its escapes, and nothing past it.
_REPR = r"(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
FIELDS = ("msg", "reply_to_text")
_PATTERNS = tuple(
    (field, re.compile(rf"(?<![\w.]){field}=({_REPR})")) for field in FIELDS
)

# Already redacted, by this script or by patch 14. Counted separately so a
# second run does not report the same lines as exposure all over again.
_WITHHELD = re.compile(r"chars withheld")
# The same marker as a *value*, which is the whole bug this once had. This
# script writes `msg=<19 chars withheld>` bare, and patch 14 writes
# `msg='<19 chars withheld>'` through %r, because the gateway formats a string.
# The quoted one looks exactly like a user's words to the pattern above, so a
# fully redacted log reported itself as 62 exposed lines and told you to scrub
# what was already clean. An alarm that is always red is not an alarm.
_WITHHELD_VALUE = re.compile(r"^<\d+ chars withheld>$")

# A line in logfmt, which begins `key=value`. ~/.hermes/logs is not only
# Hermes': ngrok writes ngrok.log there and spells its own status messages
# `msg="starting web service"`, which is exactly what the patterns above look
# for. Every one of its 43 lines was reported as somebody's food diary, and
# `--scrub` with the gateway stopped would have replaced ngrok's own reasons
# with `<30 chars withheld>`, deleting the diagnostics that exist because the
# tunnel died silently on 19 Sep, to protect a user who was never in that file.
#
# Matched on the format rather than on a filename, so the next tool that drops
# a log in here is handled without an edit, and matched per line rather than
# per file, because a first attempt at this skipped whole files by shape and
# would have stopped reading gateway.error.log, which is ours and does hold
# lines worth checking. Python's logging never starts a line `key=value`: it
# starts with a timestamp, a level, or a bracketed session id.
_LOGFMT_LINE = re.compile(r"^\s*[a-z][\w.]*=[^\s=]")


def redact_line(line: str) -> tuple[str, int]:
    """One log line with the user's words removed. Returns (line, how many)."""
    if _LOGFMT_LINE.match(line):
        return line, 0
    removed = 0

    def swap(match: re.Match) -> str:
        nonlocal removed
        # The repr's own quotes are not content, so the count is what the
        # person actually typed rather than how Python spelled it.
        inner = match.group(1)[1:-1]
        if _WITHHELD_VALUE.match(inner):
            # Already withheld. Counting it would report exposure, and
            # rewriting it would replace the marker with a marker measuring
            # the marker.
            return match.group(0)
        removed += 1
        return f"{match.group(0).split('=')[0]}=<{len(inner)} chars withheld>"

    for _, pattern in _PATTERNS:
        line = pattern.sub(swap, line)
    return line, removed


def gateway_is_running() -> bool:
    """Whether a gateway is up, and therefore holding a log open.

    Biased towards yes, like the backup script's version: a false yes leaves a
    file uncleaned and says so, a false no corrupts a log that is being
    written.
    """
    try:
        found = subprocess.run(
            ["pgrep", "-f", "hermes_cli.main gateway run"], capture_output=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return found.returncode == 0


def is_live(path: Path) -> bool:
    """Whether this file is the one currently being appended to.

    A rotated log (`agent.log.1`) is finished and safe whatever is running.
    The unrotated one is only safe when nothing is up.
    """
    rotated = path.suffix.isdigit() or path.name.endswith(".1")
    return not rotated and gateway_is_running()


def survey() -> list[tuple[Path, int, int, float]]:
    """Every log, how many lines carry user words, and how old it is."""
    if not LOG_DIR.exists():
        return []
    rows = []
    for path in sorted(LOG_DIR.iterdir()):
        if not path.is_file() or ".log" not in path.name:
            continue
        age_days = (time.time() - path.stat().st_mtime) / 86400
        exposed = withheld = 0
        try:
            with path.open(errors="replace") as handle:
                for line in handle:
                    # One definition of exposure, shared with the scrubber, so
                    # the count can never promise a redaction that `--scrub`
                    # then declines to make.
                    if redact_line(line)[1]:
                        exposed += 1
                    elif _WITHHELD.search(line):
                        withheld += 1
        except OSError:
            continue
        rows.append((path, exposed, withheld, age_days))
    return rows


def scrub(path: Path) -> tuple[bool, str]:
    """Rewrite one log with the words removed, atomically.

    Written to a neighbouring temp file and moved into place, so an interrupted
    run leaves the original log intact rather than half a log. The replacement
    keeps the original file's permissions.
    """
    if is_live(path):
        return False, "the gateway is writing to it; stop the gateway to clean this one"
    temp = path.with_suffix(path.suffix + ".scrubbing")
    removed = 0
    try:
        mode = path.stat().st_mode
        with path.open(errors="replace") as source, temp.open("w") as target:
            for line in source:
                cleaned, count = redact_line(line)
                removed += count
                target.write(cleaned)
        os.chmod(temp, mode)
        temp.replace(path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        return False, f"could not rewrite: {exc}"
    return True, f"{removed} field(s) redacted"


def prune(days: int) -> list[str]:
    """Delete rotated logs past the retention window.

    Only rotated ones. The live log is the gateway's and deleting it out from
    under an open handle is the same mistake as rewriting it.
    """
    dropped = []
    cutoff = time.time() - days * 86400
    for path in sorted(LOG_DIR.iterdir()) if LOG_DIR.exists() else []:
        if not path.is_file() or ".log" not in path.name:
            continue
        rotated = path.suffix.isdigit() or path.name.endswith(".1")
        if rotated and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            dropped.append(path.name)
    return dropped


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep users' words out of the logs.")
    parser.add_argument("--scrub", action="store_true", help="redact what is safe to redact")
    parser.add_argument("--days", type=int, help="also delete rotated logs older than this")
    args = parser.parse_args()

    rows = survey()
    if not rows:
        print(f"No logs under {LOG_DIR}.")
        return 0

    total = sum(exposed for _, exposed, _, _ in rows)
    print(f"{LOG_DIR}\n")
    for path, exposed, withheld, age in rows:
        if not exposed and not withheld:
            continue
        state = f"{exposed} line(s) with user text" if exposed else "clean"
        if withheld:
            state += f", {withheld} already withheld"
        print(f"  {path.name:<28} {state}, {age:.1f} days old")

    if not args.scrub:
        print(f"\n  {total} line(s) hold a user's words.")
        if total:
            print("  Redact them with: python3 scripts/ted-log-retention.py --scrub")
        return 0

    print()
    skipped = []
    for path, exposed, _, _ in rows:
        if not exposed:
            continue
        ok, detail = scrub(path)
        print(f"  {path.name:<28} {detail if ok else 'SKIPPED: ' + detail}")
        if not ok:
            skipped.append(path.name)

    if args.days:
        dropped = prune(args.days)
        if dropped:
            print(f"\n  Deleted {len(dropped)} rotated log(s) older than {args.days} days.")

    if skipped:
        print(
            f"\n  {len(skipped)} log(s) still hold user text because the gateway is up.\n"
            "  Run this again after: hermes gateway stop"
        )
        return 1
    print("\n  No user text left in the logs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
