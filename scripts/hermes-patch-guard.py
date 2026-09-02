#!/usr/bin/env python3
"""Notice when a Hermes upgrade has quietly removed Ted's gateway patches.

Two of Ted's fixes live in `~/.hermes/hermes-agent`, not in this repo, because
Hermes emits the text below the plugin and `VALID_HOOKS` has no hook for
outbound gateway status messages. See scripts/hermes-patches/README.md.

`hermes update` stashes local changes, pulls, then tries to re-apply them. When
that re-apply conflicts it runs `git reset --hard` and leaves the work in a
stash — so nothing is destroyed, but the running gateway silently goes back to
leaking model names into WhatsApp and charging laptop sleep to the provider.
Nothing in the chat or the log says so. That is the same failure shape as the
gates loading silently, so it gets the same treatment: an outside check.

    python3 scripts/hermes-patch-guard.py            # report
    python3 scripts/hermes-patch-guard.py --apply    # re-apply what is missing

Reported as a warning, never a stop: an unpatched Ted is noisy and mismeasures
stalls, but he still refuses under-18s, still never returns a deficit, and
still keeps users' memories apart. That is a different severity from ungated.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
PATCH_DIR = Path(__file__).resolve().parent / "hermes-patches"

# A patch counts as applied when every `present` string is in the live file and
# no `absent` string survives. Strings are chosen to be the load-bearing part of
# the change, so a partially-restored file still reads as missing.
PATCHES = (
    {
        "file": "01-sleep-aware-stall-detection.patch",
        "what": "sleep-aware stall detection",
        "checks": (
            {
                "path": "agent/chat_completion_helpers.py",
                "present": ("last_chunk_mono",),
                "absent": ('_stale_elapsed = time.time() - last_chunk_time["t"]',),
            },
            {
                "path": "agent/codex_runtime.py",
                "present": ("_codex_stream_last_event_ts = time.monotonic()",),
                "absent": ("_codex_stream_last_event_ts = time.time()",),
            },
        ),
    },
    {
        "file": "03-voice-listening-ack.patch",
        "what": "the voice-note 'Listening…' acknowledgement",
        "checks": (
            {
                "path": "gateway/run.py",
                "present": ("_gateway_voice_listening_sent",),
                "absent": (),
            },
        ),
    },
    {
        "file": "02-plain-language-provider-errors.patch",
        "what": "plain-language provider errors",
        "checks": (
            {
                "path": "gateway/run.py",
                "present": ("_GATEWAY_PROVIDER_STALL_RE", "_gateway_provider_message"),
                "absent": (
                    '    return "⏱️ The model provider is rate-limiting requests.'
                    ' Please wait a moment and try again."',
                ),
            },
        ),
    },
)


def _ok(message: str) -> str:
    return f"  ok    {message}"


def _fail(message: str) -> str:
    return f"  FAIL  {message}"


def patch_state(patch: dict) -> str | None:
    """None when applied, else why it is not."""
    for check in patch["checks"]:
        target = HERMES_AGENT / check["path"]
        if not target.exists():
            return f"{check['path']} is missing from {HERMES_AGENT}"
        source = target.read_text(encoding="utf-8", errors="replace")
        for marker in check["present"]:
            if marker not in source:
                return f"{check['path']} no longer contains {marker!r}"
        for marker in check["absent"]:
            if marker in source:
                return f"{check['path']} has the pre-patch code back"
    return None


def _clean_rejects(patch: dict) -> None:
    """Drop the .rej/.orig litter `patch` leaves next to a skipped hunk.

    A stray .rej in the Hermes tree becomes an untracked file that the next
    `hermes update` has to stash, which is exactly the mess this guard exists
    to prevent.
    """
    for check in patch["checks"]:
        target = HERMES_AGENT / check["path"]
        for suffix in (".rej", ".orig"):
            litter = target.with_name(target.name + suffix)
            if litter.exists():
                litter.unlink()


def missing() -> list[tuple[dict, str]]:
    return [(p, why) for p in PATCHES if (why := patch_state(p)) is not None]


def report() -> list[str]:
    """Lines for the gate guard to print alongside its own checks."""
    if not HERMES_AGENT.exists():
        return [_fail(f"no Hermes checkout at {HERMES_AGENT}")]
    lines = []
    for patch, why in missing():
        lines.append(
            _fail(
                f"Hermes patch NOT applied — {patch['what']}: {why}. "
                "Re-apply: npm run hermes:patch"
            )
        )
    if not lines:
        lines.append(
            _ok(
                f"all {len(PATCHES)} Hermes gateway patches are applied in {HERMES_AGENT}"
            )
        )
    return lines


def apply_missing() -> int:
    outstanding = missing()
    if not outstanding:
        print("\n".join(report()))
        print("\nNothing to do.")
        return 0

    failed = []
    for patch, why in outstanding:
        path = PATCH_DIR / patch["file"]
        print(f"  applying {patch['file']} — {why}")
        if not path.exists():
            print(_fail(f"the patch file itself is missing: {path}"))
            failed.append(patch["what"])
            continue
        # --batch never prompts (an interactive prompt here would hang a guard
        # run); --forward skips hunks that are already in place, which is the
        # normal case when an upgrade clobbered only one file of a two-file
        # patch. That combination exits non-zero on the skipped file, so the
        # return code cannot be the verdict — re-run the real check instead.
        result = subprocess.run(
            ["patch", "-p1", "--forward", "--batch"],
            cwd=HERMES_AGENT,
            stdin=path.open("rb"),
            capture_output=True,
            text=True,
        )
        still_missing = patch_state(patch)
        if still_missing is not None:
            detail = (result.stdout + result.stderr).strip()
            print(_fail(f"patch failed: {still_missing}"))
            if detail:
                print("        " + detail.replace("\n", "\n        "))
            failed.append(patch["what"])
        _clean_rejects(patch)

    print()
    print("\n".join(report()))
    if failed:
        print(
            "\nCould not re-apply: "
            + ", ".join(failed)
            + f".\nThe upstream file probably moved. Re-do the change by hand in "
            f"{HERMES_AGENT},\nthen re-export the patch — see "
            "scripts/hermes-patches/README.md."
        )
        return 1
    print("\nRe-applied. The gateway must restart to pick this up:")
    print("  hermes gateway restart && npm run gates:guard")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="re-apply any patch that is missing",
    )
    args = parser.parse_args()

    if args.apply:
        return apply_missing()

    print("\n".join(report()))
    if missing():
        print("\nRe-apply them with: npm run hermes:patch")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
