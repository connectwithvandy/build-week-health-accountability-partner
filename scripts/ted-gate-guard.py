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
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
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
WHATSAPP_ALLOWED_TOOLSETS = frozenset({"cronjob", "ted", "vision"})

# Every plugin that ships with Hermes or is installed here, as of 19 Sep 2026.
# This is a pinned inventory, not a permission list: a plugin appearing that is
# not here is the exact event that can widen WhatsApp's tool surface without
# anyone editing config.yaml, so the guard's job is to notice it, not to judge
# it. Add a name here once its toolset has been placed deliberately.
KNOWN_PLUGINS = frozenset({
    "browser",
    "context_engine",
    "cron_providers",
    "dashboard_auth",
    "disk-cleanup",
    "google_meet",
    "hermes-achievements",
    "image_gen",
    "kanban",
    "memory",
    "model-providers",
    "observability",
    "platforms",
    "security-guidance",
    "spotify",
    "teams_pipeline",
    "ted-safety-gates",
    "video_gen",
    "web",
})
PLUGIN_DIRS = (
    HERMES / "hermes-agent" / "plugins",
    HERMES / "plugins",
)


def _fail(message: str) -> str:
    return f"  FAIL  {message}"


def patch_guard_report() -> tuple[list[str], bool]:
    """Lines from the Hermes-patch check, and whether anything is missing.

    Two of Ted's fixes live in the Hermes checkout rather than this repo, and a
    `hermes update` can silently drop them (it stashes, pulls, and on a
    conflicting re-apply resets the tree). Folded in here because this is the
    script that already gets run after every restart. Fail-soft: a missing or
    broken patch guard must never stop this one from reporting on the gates.
    """
    import importlib.util

    module_path = Path(__file__).resolve().parent / "hermes-patch-guard.py"
    if not module_path.exists():
        return [], False
    try:
        spec = importlib.util.spec_from_file_location("ted_hermes_patch_guard", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.report(), bool(module.missing())
    except Exception as error:  # noqa: BLE001 - never break the gate report
        return [_fail(f"could not run the Hermes patch check: {error}")], False


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


def _rotation_index(path: Path) -> int:
    """Sort key for a rotated log: agent.log.1 before agent.log.2.

    Anything without a numeric suffix sorts last, so an oddly named sibling
    can never be read ahead of a real rotation.
    """
    suffix = path.name[len(AGENT_LOG.name) + 1 :]
    return int(suffix) if suffix.isdigit() else sys.maxsize


def registration_logs() -> list[Path]:
    """The live agent.log first, then its rotated copies, newest to oldest.

    Rotation is the whole reason this is a list. On 11 Sep 2026 agent.log
    rolled over at 00:23 and carried the only ted_safety_gates_registered
    line with it into agent.log.1. The gateway had not restarted since 9 Sep,
    so no replacement line was ever written, and reading the live file alone
    made the gates look like they had never loaded. This check then reported
    Ted as serving ungated every fifteen minutes for two and a half days,
    158 times, while the gates were demonstrably running and rewriting
    replies. A line that scrolled out of the current file is not a missing
    line, and the most serious alarm this script can raise must not fire on
    log housekeeping.
    """
    try:
        rotated = sorted(AGENT_LOG.parent.glob(AGENT_LOG.name + ".*"), key=_rotation_index)
    except OSError:
        rotated = []
    return [AGENT_LOG, *rotated]


def last_registration() -> float | None:
    """When register() last announced itself, as an epoch second.

    Files are searched newest first and the search stops at the first one
    that has the line, because a rotated copy is always older than the live
    log by construction.
    """
    for path in registration_logs():
        try:
            handle = path.open("r", errors="replace")
        except OSError:
            continue
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
        if stamp is not None:
            return stamp
    return None


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


def _platform_toolsets(platform: str) -> list[str] | None:
    """The explicitly scoped toolsets for one platform.

    ``None`` means the config could not prove a scope. Hermes' default in that
    case is broad, so security callers must treat it as unsafe rather than as
    an empty set.
    """
    try:
        lines = (HERMES / "config.yaml").read_text().splitlines()
    except OSError:
        return None

    try:
        top = lines.index("platform_toolsets:")
    except ValueError:
        return None

    header = f"  {platform}:"
    for index, line in enumerate(lines[top + 1 :], start=top + 1):
        if line and not line[0].isspace():
            break
        if line == header:
            toolsets: list[str] = []
            for child in lines[index + 1 :]:
                if child and not child[0].isspace():
                    break
                if child.startswith("  ") and not child.startswith("    "):
                    break
                match = re.fullmatch(r"\s{4}-\s+([^\s#]+)\s*(?:#.*)?", child)
                if match:
                    toolsets.append(match.group(1))
            return toolsets
    return None


def _env_set(name: str) -> bool:
    """Whether one variable is set, in the environment or in ~/.hermes/.env."""
    if os.environ.get(name):
        return True
    try:
        text = HERMES_ENV.read_text()
    except OSError:
        return False
    return bool(re.search(rf"^\s*{name}\s*=\s*\S", text, re.MULTILINE))


def whatsapp_platforms() -> list[str]:
    """Every platform carrying public WhatsApp traffic that is actually live.

    Checking ``whatsapp`` alone was the hole this function exists to close. The
    Cloud API adapter is a second WhatsApp, with its own platform key and its
    own toolset scope, and `gateway/config.py` switches it on the moment a
    phone id and an access token are both present — there is no enable flag to
    read. So mirror that same test rather than trusting a hand-kept list: a
    channel that can reach users is in scope for the guard by definition.
    """
    platforms = ["whatsapp"]
    if _env_set("WHATSAPP_CLOUD_PHONE_NUMBER_ID") and _env_set(
        "WHATSAPP_CLOUD_ACCESS_TOKEN"
    ):
        platforms.append("whatsapp_cloud")
    return platforms


def unsafe_whatsapp_toolsets(platform: str = "whatsapp") -> list[str]:
    """Anything beyond Ted, reminders, and image understanding is unsafe.

    WhatsApp is untrusted public input. A general file, terminal, browser, or
    future power tool there turns a health conversation into access to the
    machine running it. An allowlist also makes a new Hermes tool fail closed.

    An absent platform is ``<unscoped>``, not empty: Hermes falls back to that
    platform's default toolset, and for every WhatsApp platform that default is
    ``hermes-whatsapp``, which is the full core tool set — terminal, files,
    patch and the browser. Silence in the config is the dangerous answer.
    """
    toolsets = _platform_toolsets(platform)
    if toolsets is None:
        config = HERMES / "config.yaml"
        return ["<unreadable>" if not config.is_file() else "<unscoped>"]
    return sorted(set(toolsets) - WHATSAPP_ALLOWED_TOOLSETS)


def startup_inputs() -> list[Path]:
    """Every file the gateway reads once, at startup, and then never again.

    The gate source was the first of these and for a long time the only one
    checked. It is not the only one. ``config.yaml`` holds `platform_toolsets`,
    which decides the tools a turn carries, and ``.env`` decides which
    platforms exist at all — `gateway/config.py` adds `whatsapp_cloud` from two
    variables in it. Editing either and not restarting leaves the report green
    over a process still serving the old answer.
    """
    paths = [HERMES / "config.yaml", HERMES_ENV]
    source = gate_source()
    if source is not None:
        paths.insert(0, source)
    return paths


def fingerprints_path() -> Path:
    """Where the trusted fingerprints live.

    A function rather than a constant because `HERMES` is redirected in tests,
    and a constant resolved at import would have had the suite writing into the
    real ~/.hermes/state — quietly, and only noticed later.
    """
    return HERMES / "state" / "ted-gate-guard-fingerprints.json"


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _trusted_fingerprints(registered: float) -> dict[str, str]:
    """What each startup input contained when the running gateway read it.

    A timestamp is the wrong question and this file learned that the hard way
    on 19 Sep 2026, twice in one afternoon. `git checkout` rewrites every file
    it touches, so switching branch or pulling makes mtime jump on files whose
    contents did not change at all, and the report then says the running
    gateway is stale when it is serving exactly what is on disk. A guard that
    cries wolf is on its way to not being read, which is the same ending as a
    guard that cannot see a stale process.

    Only a fingerprint taken while the file was still untouched since boot is
    trusted. That is the distinction that keeps this honest: if somebody edits
    a file and this runs afterwards, the hash it sees is the *edited* one, and
    recording that would bless the change instead of reporting it. Such an
    entry is refused, and the check falls back to the timestamp, which is
    wrong in the safe direction.
    """
    try:
        stored = json.loads(fingerprints_path().read_text())
    except (OSError, ValueError):
        stored = {}
    known = stored.get("hashes") or {}
    if stored.get("registered") != registered:
        known = {}

    fresh = dict(known)
    for path in startup_inputs():
        key = str(path)
        if key in fresh:
            continue
        try:
            edited = path.stat().st_mtime
        except OSError:
            continue
        # Untouched since the gateway read it, so what is on disk now is what
        # it loaded, and this is worth remembering for after the next pull.
        if edited <= registered + 5:
            fresh[key] = _digest(path)

    if fresh != known:
        try:
            target = fingerprints_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"registered": registered, "hashes": fresh}, indent=2)
            )
        except OSError:
            pass
    return fresh


def stale_startup_inputs(registered: float) -> list[tuple[Path, float]]:
    """Startup inputs whose contents differ from what the gateway read.

    Five seconds of slack, matching the registration check, because a restart
    triggered by an edit lands a moment after it.

    This exists because of 19 Sep 2026: `whatsapp_cloud` was scoped in
    `config.yaml` and still unscoped in the running process, and every line of
    this report said ok. A guard that cannot see a stale process is a guard
    that will eventually be believed at the wrong moment.

    The timestamp opens the question and the contents answer it. A file whose
    mtime moved but whose bytes are unchanged is not stale: that is a checkout,
    not an edit, and reporting it wakes somebody for nothing.
    """
    trusted = _trusted_fingerprints(registered)
    stale = []
    for path in startup_inputs():
        try:
            edited = path.stat().st_mtime
        except OSError:
            continue
        if edited <= registered + 5:
            continue
        known = trusted.get(str(path))
        # No trusted fingerprint means this has never been seen unmodified
        # since boot, so there is nothing to compare against and the timestamp
        # stands. Reporting a stale process that is not stale costs a restart;
        # missing one costs the thing this whole file exists to prevent.
        if known and known == _digest(path):
            continue
        stale.append((path, edited))
    return sorted(stale, key=lambda item: item[1], reverse=True)


def unsafe_whatsapp_toolsets_by_platform() -> dict[str, list[str]]:
    """The unsafe toolsets on each live WhatsApp platform, worst kept first."""
    found = {}
    for platform in whatsapp_platforms():
        unsafe = unsafe_whatsapp_toolsets(platform)
        if unsafe:
            found[platform] = unsafe
    return found


def _known_plugin_toolsets(platform: str) -> list[str] | None:
    """What ``hermes tools`` has recorded as seen for one platform.

    ``None`` means the key is absent, which is not the same as empty. See
    ``plugin_toolsets_open_on_whatsapp`` for why the difference decides
    whether a plugin arrives switched on.
    """
    try:
        lines = (HERMES / "config.yaml").read_text().splitlines()
    except OSError:
        return None

    try:
        top = lines.index("known_plugin_toolsets:")
    except ValueError:
        return None

    header = f"  {platform}:"
    for index, line in enumerate(lines[top + 1 :], start=top + 1):
        if line and not line[0].isspace():
            break
        if line == header:
            names: list[str] = []
            for child in lines[index + 1 :]:
                if child and not child[0].isspace():
                    break
                if child.startswith("  ") and not child.startswith("    "):
                    break
                match = re.fullmatch(r"\s{4}-\s+([^\s#]+)\s*(?:#.*)?", child)
                if match:
                    names.append(match.group(1))
            return names
    return None


def whatsapp_plugins_unrecorded() -> bool:
    """Whether WhatsApp has no record of the plugin toolsets installed here.

    ``platform_toolsets.whatsapp`` does not govern plugin toolsets at all.
    Hermes resolves those in a separate pass (`hermes_cli/tools_config.py`,
    `_get_platform_tools`): a plugin toolset is enabled unless the platform has
    *seen* it, and "seen" means its name appears under
    ``known_plugin_toolsets.<platform>``. WhatsApp has no entry, so the only
    thing keeping today's plugins off it is `_DEFAULT_OFF_TOOLSETS`, a list
    inside Hermes that an upgrade may rewrite.

    **This is a hardening, not a closed door, and the difference was measured.**
    Recording a plugin makes it our decision instead of Hermes'. It does
    nothing for a plugin installed afterwards: that one is unseen by
    definition, on every platform including `cli`, and arrives enabled. No
    config value prevents that. ``unpinned_plugins`` is the check that can,
    because a plugin appearing at all is the event.
    """
    return _known_plugin_toolsets("whatsapp") is None


def unpinned_plugins() -> list[str]:
    """Plugins present on this machine that nobody has placed deliberately.

    This does not read toolsets and cannot: a plugin declares its tools in
    `plugin.yaml` but names its *toolset* at registration, in Python. What it
    proves is narrower and is the thing worth watching — a plugin that was not
    here when the WhatsApp surface was last reasoned about is here now, most
    likely carried in by a Hermes upgrade.
    """
    found: set[str] = set()
    for directory in PLUGIN_DIRS:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            if not (entry / "plugin.yaml").is_file():
                continue
            found.add(entry.name)
    return sorted(found - KNOWN_PLUGINS)


def cron_tools_unscoped() -> bool:
    """Whether scheduled runs are loading the whole 52-tool default set.

    `platform_toolsets` in config.yaml narrows the tool schemas a run carries.
    `whatsapp` has been scoped since early on; `cron` was simply never added to
    the same list, so every reminder carried a browser, a terminal, file write,
    Home Assistant and computer use in its prompt to produce one lowercase
    sentence. Measured 17 Sep 2026: 44,110 prompt tokens a firing against
    26,210 for a scoped one, on every firing, forever.

    It is checked here because config.yaml is NOT version controlled. The fix
    is two lines that a reinstall silently takes away again, which is exactly
    how `cron` came to be missing from a list that already had nine other
    platforms in it. A stale check is worse than none, so this reads the file
    rather than trusting that the fix was ever applied.

    Reported as a warning, never a stop: an unscoped cron is expensive, not
    ungated. Ted still refuses under-18s and still never returns a deficit.
    """
    try:
        lines = (HERMES / "config.yaml").read_text().splitlines()
    except OSError:
        return False  # nothing to read is a different problem, reported elsewhere
    try:
        top = lines.index("platform_toolsets:")
    except ValueError:
        return False
    for line in lines[top + 1 :]:
        if line and not line[0].isspace():
            break
        if line.strip() == "cron:":
            return False
    return True


def unpinned_enabled_jobs() -> list[str]:
    """Names of switched-on cron jobs with no provider or model of their own.

    Hermes skips an unpinned job whose global model changed since it was created
    (#44585), and since patch 08 that skip no longer reaches the user's chat. So
    the reminder they asked for stops arriving and nothing at all says why.

    `_pin_new_reminder_job` in the gate pins each new reminder as it is made,
    but it deliberately swallows its own errors — losing a reminder would be
    worse than leaving one unpinned — so a break there is silent by design. This
    is the thing that makes it not silent. It is also the only check that sees
    free-form jobs, which the model can still create from a chat.
    """
    try:
        raw = json.loads((HERMES / "cron" / "jobs.json").read_text())
    except (OSError, ValueError):
        return []
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    jobs = list(jobs.values()) if isinstance(jobs, dict) else jobs
    return [
        str(job.get("name") or job.get("id"))
        for job in jobs
        if isinstance(job, dict)
        and job.get("enabled")
        and not job.get("no_agent")
        and not (str(job.get("provider") or "").strip() and str(job.get("model") or "").strip())
    ]


GATEWAY_JOB = "ai.hermes.gateway"
RESTART_GRACE_SECONDS = 25.0


def launchd_job_loaded() -> bool:
    """Whether launchd holds a definition for the gateway at all.

    The difference between "stopped on purpose" and "between two halves of a
    restart". Only the second is worth waiting for.
    """
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{GATEWAY_JOB}"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def settled_pid(grace: float = RESTART_GRACE_SECONDS) -> int | None:
    """The gateway pid, giving launchd a moment to finish putting it back.

    `hermes gateway restart` hands off to launchd and returns immediately, so
    for a second or two afterwards there is no pid file and this guard used to
    announce "gateway is not running". That is wrong twice over: it is untrue,
    and it exits non-zero, which on 18 Sep 2026 broke a `restart && guard &&
    migrate` chain and silently skipped the migration at the end of it.

    Only waits when launchd has a definition loaded. A gateway stopped on
    purpose answers immediately, as it should.
    """
    pid = running_pid()
    if pid is not None or not launchd_job_loaded():
        return pid
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        time.sleep(1.0)
        pid = running_pid()
        if pid is not None:
            return pid
    return None


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
    pid = settled_pid()

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

    # Loaded is not the same as current. Every startup input is read once, so
    # an edit after the last load means the running gateway is still serving
    # the previous answer — the gates, the tool scope, or the platform list.
    if pid is not None and registered is not None:
        for path, edited in stale_startup_inputs(registered):
            when = datetime.fromtimestamp(edited).strftime("%Y-%m-%d %H:%M:%S")
            report.append(
                _fail(
                    f"STALE — {path.name} changed at {when}, after the running "
                    "gateway read it. Restart to pick it up."
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

    unsafe_by_platform = unsafe_whatsapp_toolsets_by_platform()
    checked = whatsapp_platforms()
    if unsafe_by_platform:
        for platform, unsafe in unsafe_by_platform.items():
            names = ", ".join(unsafe)
            ungated.append(
                f"{platform} has unsafe or unscoped tool access: {names}"
            )
            report.append(
                _fail(
                    f"{platform} tool access is UNSAFE — "
                    + names
                    + ". Allowed: cronjob, ted, vision"
                )
            )
    else:
        report.append(
            _ok(
                "WhatsApp is scoped to cronjob, ted, and vision ("
                + ", ".join(checked)
                + ")"
            )
        )

    plugins_unrecorded = whatsapp_plugins_unrecorded()
    if plugins_unrecorded:
        report.append(
            _fail(
                "WhatsApp has no record of the installed plugins — "
                "known_plugin_toolsets has\n        no whatsapp entry, so "
                "spotify is off it only because a list inside Hermes\n"
                "        says so. platform_toolsets does not govern plugins. "
                "Record them: python3\n        "
                "scripts/ted-lock-whatsapp-tools.py --apply"
            )
        )
    else:
        report.append(_ok("WhatsApp has recorded the plugins installed here"))

    strangers = unpinned_plugins()
    if strangers:
        names = ", ".join(strangers)
        report.append(
            _fail(
                f"{len(strangers)} plugin(s) arrived unannounced: {names}\n"
                "        A plugin is how the WhatsApp tool surface widens "
                "without config.yaml changing.\n        Decide where each one "
                "belongs, then add it to KNOWN_PLUGINS in this file."
            )
        )
    else:
        report.append(_ok("no plugin has appeared since the surface was set"))

    cron_unscoped = cron_tools_unscoped()
    if cron_unscoped:
        report.append(
            _fail(
                "cron tools are UNSCOPED — every reminder carries all 52 tools "
                "(~44k prompt tokens\n        for one line). Fix: python3 "
                "scripts/ted-scope-cron-tools.py --apply"
            )
        )
    else:
        report.append(_ok("cron is scoped to the ted toolset"))

    unpinned = unpinned_enabled_jobs()
    if unpinned:
        shown = ", ".join(unpinned[:4]) + (" ..." if len(unpinned) > 4 else "")
        report.append(
            _fail(
                f"{len(unpinned)} enabled cron job(s) are UNPINNED — they stop "
                f"arriving, silently,\n        the next time the model changes. "
                f"{shown}\n        Fix: ~/.hermes/hermes-agent/venv/bin/python3 "
                "scripts/ted-pin-cron-jobs.py --apply"
            )
        )
    else:
        report.append(_ok("every enabled cron job is pinned to a model"))

    patch_lines, patches_missing = patch_guard_report()
    report.extend(patch_lines)

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
                "\nGates are on, but the running gateway is NOT reading what is on "
                "disk — see the\nSTALE line(s) above. Restart: "
                "launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway"
            )
            return 1
        if absent:
            print("\nGates are on. Memory is off — see the FAIL line above.")
            return 1
        if strangers:
            # Above the patches: a plugin that nobody put here is the one event
            # that can widen the WhatsApp surface without config.yaml moving.
            print(
                "\nGates are on. A plugin arrived that was not here when the "
                "WhatsApp tool surface\nwas last reasoned about — see above. "
                "Decide where it belongs before the next restart."
            )
            return 1
        if plugins_unrecorded:
            print(
                "\nGates are on. Which plugins WhatsApp may carry is Hermes' "
                "decision today, not\nours — see above. Nothing is through it. "
                "Record them: python3\nscripts/ted-lock-whatsapp-tools.py --apply"
            )
            return 1
        if patches_missing:
            # Not ungated. Ted still refuses under-18s, still never returns a
            # deficit, still keeps users apart. He is just noisy again and
            # mismeasures provider stalls, so this is a warning, not a stop.
            print(
                "\nGates are on. The Hermes gateway patches are NOT applied — "
                "Ted will leak\nprovider diagnostics into chat and charge laptop "
                "sleep to the provider.\nRe-apply: npm run hermes:patch"
            )
            return 1
        if unpinned:
            print(
                "\nGates are on. Some reminders will stop arriving silently at the "
                "next model change —\nsee above. Fix: "
                "~/.hermes/hermes-agent/venv/bin/python3 scripts/ted-pin-cron-jobs.py --apply"
            )
            return 1
        if cron_unscoped:
            # Last, because it is the cheapest to be wrong about: nothing a
            # user sees changes either way, only the bill.
            print(
                "\nGates are on. Scheduled runs are carrying every tool Hermes "
                "has — see above.\nApply: python3 scripts/ted-scope-cron-tools.py --apply"
            )
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
