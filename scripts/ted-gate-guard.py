#!/usr/bin/env python3
"""Refuse to let Ted serve WhatsApp without its safety gates.

Hermes catches every exception a plugin raises at load time, logs one WARNING
and carries on (hermes_cli/plugins.py, `except Exception as exc:` in
`_load_plugin`). For an ordinary plugin that is the right call. For this one it
means a folder rename, a syntax error or a missing file leaves Ted answering
real messages with no 18+ check, no no-deficit rule, no forced disclosure and
no per-user memory isolation — and nothing in the chat or the log says so.

So the stop has to come from outside Hermes. Run this after every gateway
restart, rename or gate edit. By default it stops a gateway that is running
ungated; pass --check-only to report without touching anything.

    python3 scripts/ted-gate-guard.py
    python3 scripts/ted-gate-guard.py --check-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERMES = Path.home() / ".hermes"
SHIM = HERMES / "plugins" / "ted-safety-gates" / "__init__.py"
AGENT_LOG = HERMES / "logs" / "agent.log"
STARTS_LOG = HERMES / "gateway-starts.log"
PID_FILE = HERMES / "gateway.pid"
HERMES_ENV = HERMES / ".env"

REGISTERED = "ted_safety_gates_registered"
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")
LOG_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _fail(message: str) -> str:
    return f"  FAIL  {message}"


def _ok(message: str) -> str:
    return f"  ok    {message}"


def shim_imports() -> str | None:
    """Import the shim the way Hermes does, in a subprocess. None on success."""
    if not SHIM.exists():
        return f"no plugin shim at {SHIM}"
    probe = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('ted_gate_probe', {str(SHIM)!r});"
        "module = importlib.util.module_from_spec(spec);"
        "sys.modules['ted_gate_probe'] = module;"
        "spec.loader.exec_module(module);"
        "assert callable(module.register)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    if result.returncode == 0:
        return None
    tail = (result.stderr or "").strip().splitlines()
    return tail[-1] if tail else "plugin shim failed to import"


def gate_source() -> Path | None:
    """The repo file the shim loads, read straight out of the shim."""
    try:
        text = SHIM.read_text()
    except OSError:
        return None
    match = re.search(r'^SOURCE\s*=|_CANDIDATES\s*=', text, re.MULTILINE)
    if match is None:
        return None
    for candidate in re.findall(r'Path\.home\(\)\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"', text):
        source = Path.home() / candidate[0] / candidate[1] / "hermes" / "ted_safety_gates" / "__init__.py"
        if source.is_file():
            return source
    return None


def last_gateway_start() -> float | None:
    try:
        lines = [line for line in STARTS_LOG.read_text().splitlines() if line.strip()]
    except OSError:
        return None
    try:
        return float(lines[-1])
    except (IndexError, ValueError):
        return None


def last_registration() -> float | None:
    """When register() last announced itself, as an epoch second."""
    try:
        handle = AGENT_LOG.open("r", errors="replace")
    except OSError:
        return None
    stamp = None
    with handle:
        for line in handle:
            if REGISTERED not in line:
                continue
            matched = LOG_STAMP.match(line)
            if matched:
                stamp = datetime.strptime(
                    matched.group(1), "%Y-%m-%d %H:%M:%S"
                ).timestamp()
    return stamp


def missing_env() -> list[str]:
    present = {name for name in REQUIRED_ENV if os.environ.get(name)}
    try:
        text = HERMES_ENV.read_text()
    except OSError:
        text = ""
    for name in REQUIRED_ENV:
        if re.search(rf"^\s*{name}\s*=\s*\S", text, re.MULTILINE):
            present.add(name)
    return [name for name in REQUIRED_ENV if name not in present]


def running_pid() -> int | None:
    """The live gateway pid, or None.

    ~/.hermes/gateway.pid holds a JSON record, not a bare integer. Reading it
    as an int made this function answer "not running" for a gateway that was
    running — the guard's worst possible lie, since it reports nothing is
    serving while Ted answers real messages.
    """
    try:
        raw = PID_FILE.read_text().strip()
    except OSError:
        return None

    pid: int | None = None
    try:
        record = json.loads(raw)
    except ValueError:
        record = None
    if isinstance(record, dict):
        try:
            pid = int(record.get("pid"))
        except (TypeError, ValueError):
            pid = None
    if pid is None:
        try:
            pid = int(raw)
        except ValueError:
            return None

    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="report only; never stop the gateway",
    )
    args = parser.parse_args()

    report: list[str] = []
    ungated: list[str] = []
    stale = False

    import_error = shim_imports()
    if import_error:
        ungated.append(f"the plugin shim does not import: {import_error}")
        report.append(_fail(f"shim import — {import_error}"))
    else:
        report.append(_ok(f"shim imports and exposes register() — {SHIM}"))

    started = last_gateway_start()
    registered = last_registration()
    pid = running_pid()

    if pid is None:
        report.append(
            _ok("gateway is not running — nothing is serving ungated (not verified)")
        )
    elif registered is None:
        ungated.append("the gates have never announced themselves in agent.log")
        report.append(_fail(f"no {REGISTERED} line in {AGENT_LOG}"))
    elif started is not None and registered < started - 5:
        when = datetime.fromtimestamp(registered).strftime("%Y-%m-%d %H:%M:%S")
        ungated.append(
            f"the gateway restarted after the gates last loaded (last load {when})"
        )
        report.append(_fail(f"stale registration — last {REGISTERED} at {when}"))
    else:
        when = datetime.fromtimestamp(registered).strftime("%Y-%m-%d %H:%M:%S")
        report.append(_ok(f"gates loaded in the running gateway at {when}"))

    # Loaded is not the same as current. The gate source is the repo file, so
    # an edit after the last load means the running gateway is still serving
    # the previous version of every gate.
    if pid is not None and registered is not None:
        source = gate_source()
        if source is not None:
            edited = source.stat().st_mtime
            if edited > registered + 5:
                when = datetime.fromtimestamp(edited).strftime("%Y-%m-%d %H:%M:%S")
                report.append(
                    _fail(
                        f"STALE — the gate source changed at {when}, after the "
                        "running gateway loaded it. Restart to pick it up."
                    )
                )
                stale = True

    absent = missing_env()
    if absent:
        # Not ungated: Ted still refuses under-18s and never returns a deficit.
        # It just silently forgets everyone, so it is a warning, not a stop.
        report.append(
            _fail(
                "memory is OFF — "
                + " and ".join(absent)
                + f" is not set in the environment or {HERMES_ENV}"
            )
        )
    else:
        report.append(_ok("Convex memory variables are set"))

    print("\n".join(report))

    if not ungated:
        if pid is None:
            # Nothing is serving, so nothing is ungated - but the check that
            # matters has not run. Saying "gates are on" here reads as a green
            # light for a gateway that was never asked the question.
            print(
                "\nNothing is running, so nothing is ungated — but the gates have "
                "NOT been verified.\nStart the gateway (hermes gateway start), "
                "then run this again."
            )
            return 3
        if stale:
            print(
                "\nGates are on, but they are NOT the code in the repo — see the "
                "STALE line above.\nRestart: hermes gateway restart"
            )
            return 1
        if absent:
            print("\nGates are on. Memory is off — see the FAIL line above.")
            return 1
        print("\nGates are on.")
        return 0

    print("\nTed is UNGATED:")
    for reason in ungated:
        print(f"  - {reason}")

    if pid is None:
        print("\nThe gateway is not running, so nothing was stopped.")
        return 2
    if args.check_only:
        print(f"\n--check-only: gateway {pid} left running. Stop it yourself.")
        return 2
    os.kill(pid, signal.SIGTERM)
    print(f"\nStopped the gateway (pid {pid}). Fix the gates before restarting.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
