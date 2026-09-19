#!/usr/bin/env python3
"""The product-level checks, run together, saying nothing until something moves.

`ted-watch.py` watches the machine: gates, link, model, power, credit. Every
one of those was written after an outage, and they run every fifteen minutes
whether or not anybody is thinking about them.

The checks in *this* file are the other half, and they have never run unless
somebody remembered: whether anyone went unanswered, whether a deletion
request was honoured, whether onboarding is still losing people, what the
model costs. That difference has a cost with a number on it. On 3 Sep 2026 a
user asked to be forgotten, `npm run deletion:audit` would have said so on any
day since, and nobody ran it for sixteen days.

WHY IT REPORTS DIFFERENCES RATHER THAN STATE.

A daily mail that says "30 users stuck, 0 unanswered, 1 deletion outstanding"
is read twice and filtered on the third day. The number that matters is not
30, it is that yesterday it was 29. So every check is reduced to a handful of
named facts, this compares them to the last run, and it is silent unless one
of them moved.

Volume is deliberately not a fact. "272 messages delivered in the last 7 days"
changes every single day and means nothing on its own, so it is printed and
never alerted on. What is a fact is somebody unanswered, a deletion not
honoured, a user stuck, a collision in memory.

WHEN A CHECK'S OUTPUT CHANGES SHAPE.

These are read out of each script's own printed words, because only three of
the seven can emit JSON. That is brittle, and the brittleness is pointed in
the safe direction: an extractor that no longer matches raises rather than
returning zero, and "I can no longer read this check" is reported as loudly as
a finding. A check that goes quiet because somebody reworded a line is exactly
how a watcher dies without anybody noticing.

    npm run sweep                # the table, and what moved
    npm run sweep -- --dry-run   # the same, without saving or sending
    npm run sweep -- --force     # send the alert even if nothing moved
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE = HERMES / "state" / "ted-sweep-state.json"
# Long enough for the 30-day ordering scan and a Convex round trip, short
# enough that a hung check cannot hold the whole sweep open all night.
TIMEOUT_SECONDS = 300

LABEL = "ai.ted.sweep"
PLIST_SRC = REPO / "scripts" / f"{LABEL}.plist"
PLIST_DEST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SWEEP_LOG = HERMES / "logs" / "ted-sweep.log"


class ShapeChanged(Exception):
    """A check printed something this can no longer read.

    Raised rather than returning an empty result, because a watcher that
    silently reports "nothing wrong" when it has stopped understanding the
    answer is worse than no watcher: it actively buys silence.
    """


def _json(text: str) -> dict:
    """A check's JSON, or a shape change rather than a traceback.

    A script that fails prints its reason to stdout like any other, so what
    arrives here is regularly not JSON at all. That is a check this can no
    longer read, which is a thing to report, not a crash.
    """
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ShapeChanged(f"did not print JSON: {str(exc)[:60]}") from exc


def _one(pattern: str, text: str, name: str) -> int:
    """The single integer this pattern names, or a shape change."""
    found = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    if not found:
        raise ShapeChanged(f"could not find {name}")
    return int(found.group(1))


def ordering(text: str) -> dict:
    """T08. Somebody who wrote to Ted and got nothing, or got it out of order."""
    if "FAIL" not in text and "ok  every message was answered" not in text:
        raise ShapeChanged("neither the pass line nor a FAIL")
    unanswered = 0
    if "got no reply at all" in text:
        unanswered = _one(r"(\d+) message\(s\) got no reply at all", text, "unanswered")
    dropped = 0
    if "could not be delivered" in text:
        dropped = _one(
            r"(\d+) message\(s\) got a reply that could not be delivered",
            text,
            "dropped",
        )
    return {"unanswered": unanswered, "written but not delivered": dropped}


def deletion(text: str) -> dict:
    """T09. A person asked to be forgotten and something kept them."""
    if "live finding" in text:
        return {"stores still holding a forgotten user": _one(
            r"(\d+) live finding\(s\)", text, "live findings"
        )}
    if "person/people marked forgotten" in text:
        return {"stores still holding a forgotten user": 0}
    raise ShapeChanged("no verdict line")


def memory(text: str) -> dict:
    """T14. Two spellings of one key, both going into the next prompt."""
    payload = _json(text)
    if "key_collisions" not in payload:
        raise ShapeChanged("no key_collisions in the audit")
    return {"keys stored under two spellings": len(payload["key_collisions"])}


def onboarding(text: str) -> dict:
    """The biggest number in the product, and the one nothing watched.

    Read from the plans rather than from the printed totals, because the
    totals are a summary of these and one more thing to keep in step.
    """
    plans = _json(text).get("plans")
    if plans is None:
        raise ShapeChanged("no plans in the reconcile output")
    return {
        "users stuck in onboarding": sum(1 for p in plans if p.get("missing")),
        "of those, missing a check-in time": sum(
            1 for p in plans if "checkInTime" in (p.get("missing") or [])
        ),
        "records that disagree with themselves": sum(
            1 for p in plans if p.get("disagrees")
        ),
    }


def concurrency(text: str) -> dict:
    """T02. Two people at once, and whether either saw the other."""
    if "all of them are clean" in text:
        return {"episodes where users crossed": 0}
    found = re.search(r"(\d+) episode\(s\) (?:are|is) NOT clean", text)
    if found:
        return {"episodes where users crossed": int(found.group(1))}
    raise ShapeChanged("no clean verdict")


def window(text: str) -> dict:
    """T06. What share of Ted's sending needs a paid template."""
    return {
        "% of sends needing a template": _one(
            r"outside it, needs a template\s+\d+\s+(\d+)", text, "template share"
        )
    }


def spend(text: str) -> dict:
    """The bill over the trailing week.

    Rounded to the nearest ten dollars on purpose. A rolling seven-day total
    moves a little every single day, and a line that appears in every report
    is a line nobody reads. At this resolution it speaks when the shape of the
    spend changes rather than when the window slides.
    """
    payload = _json(text)
    try:
        total = float(payload["windows"]["window"]["all"]["usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ShapeChanged(f"no total in the spend report: {exc}") from exc
    return {"$ in the last 7 days, to the nearest 10": round(total / 10) * 10}


# Order matters only for reading: the ones that are somebody's experience go
# first, the ones that are money go last.
#
# `alerts` is the whole design. A fact that moves and alerts wakes somebody. A
# fact that moves and does not is printed and left alone, because it moves
# every day on its own and would train the reader to ignore the ones that do
# not. Volume is never a fact at all.
CHECKS = (
    ("unanswered people", ["ted-ordering-check.py"], ordering, True),
    ("deletion requests", ["ted-deletion-audit.py", "--forgotten"], deletion, True),
    ("onboarding", ["ted-reconcile-setup.py", "--json"], onboarding, True),
    ("users crossing", ["ted-concurrency-check.py"], concurrency, True),
    ("memory keys", ["ted-memory-audit.py", "--json"], memory, True),
    ("template share", ["ted-window-check.py"], window, False),
    ("spend", ["ted-api-spend.py", "--json"], spend, False),
)


def run(argv: list[str]) -> str:
    """One check's own words. Its exit code is not the verdict; its output is.

    Several of these exit non-zero *because* they found something, which is
    correct for a person at a terminal and useless here: this needs to read
    what was found either way.
    """
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / argv[0]), *argv[1:]],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        cwd=REPO,
    )
    return done.stdout + done.stderr


def sweep() -> dict:
    """Every check, reduced to its facts, or to why it could not be read."""
    results: dict[str, dict] = {}
    for name, argv, extract, _alerts in CHECKS:
        try:
            results[name] = {"facts": extract(run(argv))}
        except ShapeChanged as exc:
            results[name] = {"unreadable": str(exc)}
        except subprocess.TimeoutExpired:
            results[name] = {"unreadable": f"took longer than {TIMEOUT_SECONDS}s"}
        except Exception as exc:  # noqa: BLE001 - one broken check is not seven
            results[name] = {"unreadable": f"{type(exc).__name__}: {exc}"}
    return results


def differences(before: dict, after: dict) -> list[tuple[str, str, bool]]:
    """What moved, in words, and whether it is worth waking somebody for."""
    alerting = {name: alerts for name, _, _, alerts in CHECKS}
    moved: list[tuple[str, str, bool]] = []
    for name, now in after.items():
        was = before.get(name, {})
        if "unreadable" in now:
            # Always worth saying, whatever the check is about: this is the
            # state where the sweep has quietly stopped being a sweep.
            if was.get("unreadable") != now["unreadable"]:
                moved.append((name, f"cannot be read: {now['unreadable']}", True))
            continue
        if "unreadable" in was:
            # One line, with the numbers in it. Saying "can be read again" and
            # then listing every fact as new says the same thing twice.
            facts = ", ".join(f"{k} {v}" for k, v in now["facts"].items())
            moved.append((name, f"can be read again: {facts}", alerting.get(name, True)))
            continue
        old_facts = was.get("facts") or {}
        for fact, value in now["facts"].items():
            if fact not in old_facts:
                if before:
                    moved.append((name, f"{fact}: {value} (new)", alerting.get(name, True)))
                continue
            if old_facts[fact] != value:
                moved.append((
                    name,
                    f"{fact}: {old_facts[fact]} → {value}",
                    alerting.get(name, True),
                ))
    return moved


def notifier():
    """ted-watch's alert channel, rather than a second one beside it.

    Two ways to send mail is two things to configure and one of them to be
    quietly broken. Returns None if the watcher cannot be loaded, and the
    caller says so rather than failing silently.
    """
    source = REPO / "scripts" / "ted-watch.py"
    try:
        spec = importlib.util.spec_from_file_location("ted_watch_for_sweep", source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.notify
    except Exception:  # noqa: BLE001 - a missing channel must not lose the report
        return None


def unreadable_checks(state: dict) -> list[str]:
    """The checks the last run could not read. Empty is the only good answer.

    Separate from the exit code on purpose, and this is the whole reason the
    installer exists in this shape. The sweep exits 0 when a check comes back
    unreadable, because one broken check must not take the other six down with
    it — so "the job ran and exited cleanly" is true and useless. The first
    scheduled run of this very file exited 0 with the memory audit reporting
    "did not print JSON", which was `npx` missing from launchd's PATH.

    An installer whose proof is an exit code would have called that a success.
    """
    return sorted(
        name for name, result in (state.get("checks") or {}).items()
        if "unreadable" in result
    )


def install() -> int:
    """Put the job on, then refuse to say it works until it has worked.

    Modelled on `ted-backup.py --install`, including its lesson: validate with
    `plutil`, which is what launchd uses, rather than only with plistlib. The
    two disagree, and a stray `-->` once left a plist that plistlib read
    happily and launchd rejected outright, silently going on running the
    previous definition.

    That failure has a sibling, met on 19 Sep 2026 and the reason this is a
    flag rather than a line in a README: `launchctl kickstart -k` restarts a
    job from launchd's in-memory copy and never re-reads the file. The plist
    on disk was correct, the running job was the old one, and the evidence was
    a fix that changed nothing twice. Unload, then load, then kickstart.
    """
    linted = subprocess.run(["plutil", "-lint", str(PLIST_SRC)], capture_output=True)
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

    print(f"Loaded {LABEL}. Running it once to prove it works...")
    ok, detail = prove_the_job_runs()
    if not ok:
        print(f"\n  THE SCHEDULED JOB CANNOT RUN: {detail}", file=sys.stderr)
        print("  It is loaded and it would fail silently at 09:00.", file=sys.stderr)
        return 1

    blind = unreadable_checks(read_state())
    if blind:
        print(f"\n  It ran, and it is blind in {len(blind)} place(s):", file=sys.stderr)
        for name in blind:
            print(f"    {name}", file=sys.stderr)
        print(
            "\n  The job works and those checks do not, which is the state that\n"
            "  looks healthiest and is worth least. Usually the environment:\n"
            "  launchd inherits almost nothing. Fix, then --install again.",
            file=sys.stderr,
        )
        return 1

    print(f"\n  Proven: {detail}, and all {len(CHECKS)} checks were readable.")
    print("  It runs daily at 09:00 and says nothing unless something moved.")
    return 0


def prove_the_job_runs(timeout: float = 420.0) -> tuple[bool, str]:
    """Fire the installed job once and wait for a real exit code.

    launchd reports `last exit code` per job, which is the only answer that
    accounts for the whole path: the interpreter, its permissions, the script
    location, the environment and the script itself. Anything this process
    checked directly would be checking its own permissions, and those are
    exactly the ones that differ.
    """
    target = f"gui/{os.getuid()}/{LABEL}"
    before = SWEEP_LOG.stat().st_size if SWEEP_LOG.exists() else 0
    started = subprocess.run(["launchctl", "kickstart", "-p", target], capture_output=True)
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
            if SWEEP_LOG.exists():
                with SWEEP_LOG.open(errors="replace") as handle:
                    handle.seek(before)
                    tail = " ".join(handle.read().split())[:200]
            return False, f"exit code {value}. {tail}"
        time.sleep(2)
    return False, f"it did not finish within {timeout:.0f}s"


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        print(f"could not save state: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="The product checks, together.")
    parser.add_argument("--dry-run", action="store_true", help="save nothing, send nothing")
    parser.add_argument("--force", action="store_true", help="send even if nothing moved")
    parser.add_argument("--install", action="store_true", help="run it daily at 09:00")
    args = parser.parse_args()

    if args.install:
        return install()

    before = read_state()
    after = sweep()

    for name, result in after.items():
        if "unreadable" in result:
            print(f"  {name:<22} CANNOT BE READ: {result['unreadable']}")
            continue
        facts = ", ".join(f"{k} {v}" for k, v in result["facts"].items())
        print(f"  {name:<22} {facts}")

    moved = differences(before.get("checks", {}), after)
    print()
    if not before:
        # The first run has nothing to compare against and must not send a
        # wall of "new" as though it were news.
        saving = "this run is the baseline" if not args.dry_run else "nothing saved, this was a dry run"
        print(f"  First run. Nothing to compare against yet; {saving}.")
    elif not moved:
        print("  Nothing moved since the last run.")
    else:
        for name, what, urgent in moved:
            print(f"  {'!' if urgent else ' '} {name}: {what}")

    worth_sending = [m for m in moved if m[2]] if before else []
    if (worth_sending or args.force) and not args.dry_run:
        send = notifier()
        if send is None:
            print("\n  Could not load ted-watch's alert channel; printed only.")
        else:
            body = "\n".join(f"{name}: {what}" for name, what, _ in (moved or [("sweep", "forced", True)]))
            send(f"⚠️ Ted's product checks moved", body, False)

    if not args.dry_run:
        write_state({"checks": after, "at": time.time()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
