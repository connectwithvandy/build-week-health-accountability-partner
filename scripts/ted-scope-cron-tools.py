#!/usr/bin/env python3
"""Stop sending a browser, a terminal and a smart-home remote to write "water time".

    python3 scripts/ted-scope-cron-tools.py            # show what would change
    python3 scripts/ted-scope-cron-tools.py --apply    # write it
    python3 scripts/ted-scope-cron-tools.py --revert   # take it back out

Reverting removes the two lines and nothing else, so it is safe to run even if
the config has been edited for other reasons since. It does not restore a
backup, because a backup taken before this change also predates anything else
that happened today.

WHAT THIS IS FOR.

Every scheduled reminder Ted sends is a fresh agent run, and every fresh run
carries the whole tool schema block in its prompt. `platform_toolsets` in
`~/.hermes/config.yaml` is what narrows that block per platform, and somebody
already narrowed `whatsapp` to four toolsets. `cron` was never added to the
same list, so it falls through to `hermes-cron`, which is all 52 core tools:
twelve browser-automation tools, a terminal, file read and write, image
generation, Home Assistant, eleven kanban tools and computer use.

Measured over 14 days on 17 Sep 2026: a scoped WhatsApp turn writes a median
26,210-token prompt. An unscoped cron firing writes 44,110. That difference is
carried on every single firing, forever, to produce one lowercase sentence.

It buys nothing. Across the same 14 days cron sessions called exactly two
tools: `ted_day_summary` 192 times and `ted_set_reminder` once. Both are in the
`ted` toolset, which is where the plugin registers all nine of its tools
(`register()` in `hermes/ted_safety_gates/__init__.py`). Nothing else was
touched, so nothing else needs to be offered.

WHY `ted` ALONE, AND NOT WHATSAPP'S FOUR.

`whatsapp` also carries `cronjob`, `file` and `vision`, and it needs them: a
person in a chat sends a photo of a plate, and asks for a reminder in words
that `ted_set_reminder` cannot express. A cron firing does none of that. It is
handed a prompt and writes one line.

Leaving `cronjob` out has a second effect worth having on its own: a scheduled
job can no longer create scheduled jobs. That is the loop behind the duplicate
supplement reminders of 4 Sep, closed from the other end.

WHY THIS FILE, RATHER THAN EDITING THE CONFIG BY HAND.

`~/.hermes/config.yaml` is not version controlled. A hand edit is one reinstall
away from being gone with nothing to notice it, which is how `cron` came to be
missing from a list that already had nine other platforms in it. So the change
is written here, where it is reviewed and tested, and `scripts/ted-gate-guard.py`
asserts it afterwards — `npm run gates:guard` fails loudly if it ever reverts.

The edit is a surgical text insert rather than a YAML round-trip on purpose:
this runs under the system python, which has no PyYAML, and a reserialised
config would rewrite 270 lines of unrelated settings to change two.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

CONFIG = Path.home() / ".hermes" / "config.yaml"

# The platform whose tool block is unscoped, and the toolset it should get.
PLATFORM = "cron"
TOOLSETS = ["ted"]


def platform_block(text: str, platform: str) -> list[str] | None:
    """The toolsets listed under `platform_toolsets: <platform>:`, or None.

    None means the key is absent, which is the state this script exists to
    fix. An empty list means the key is present but lists nothing, which is a
    different and deliberate thing, so it is reported rather than overwritten.
    """
    lines = text.splitlines()
    try:
        top = lines.index("platform_toolsets:")
    except ValueError:
        return None
    for i in range(top + 1, len(lines)):
        line = lines[i]
        if line and not line[0].isspace():
            return None  # ran off the end of the block
        if line.strip() == f"{platform}:":
            found: list[str] = []
            for entry in lines[i + 1 :]:
                stripped = entry.strip()
                if stripped.startswith("- "):
                    found.append(stripped[2:].strip())
                    continue
                break
            return found
    return None


def insert_platform(text: str, platform: str, toolsets: list[str]) -> str:
    """Add the platform block directly under `platform_toolsets:`."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == "platform_toolsets:":
            block = [f"  {platform}:\n"] + [f"    - {t}\n" for t in toolsets]
            return "".join(lines[: i + 1] + block + lines[i + 1 :])
    raise SystemExit(
        "No `platform_toolsets:` key in config.yaml. Refusing to invent the "
        "whole block: that would silently narrow every platform at once."
    )


def remove_platform(text: str, platform: str, toolsets: list[str]) -> str:
    """Take the block back out, leaving every other line exactly as it is.

    Only removes a block that matches what this script writes. A `cron:` entry
    somebody has since edited by hand is left alone and reported, because
    undoing a change is not a licence to discard a different one.
    """
    lines = text.splitlines(keepends=True)
    want = [f"  {platform}:\n"] + [f"    - {t}\n" for t in toolsets]
    for i, line in enumerate(lines):
        if line.rstrip("\n") == "platform_toolsets:":
            block = lines[i + 1 : i + 1 + len(want)]
            # The line after must not be another list item. Matching only the
            # prefix of a longer list would delete the head of it and leave the
            # tail orphaned under `platform_toolsets:`, which is a corrupt file
            # rather than a failed revert.
            after = lines[i + 1 + len(want) : i + 2 + len(want)]
            trailing_entry = bool(after) and after[0].strip().startswith("- ")
            if block == want and not trailing_entry:
                return "".join(lines[: i + 1] + lines[i + 1 + len(want) :])
            raise SystemExit(
                f"The `{platform}:` block under platform_toolsets is not the one "
                "this script wrote.\nLeaving it alone — remove it by hand if you "
                "meant to."
            )
    raise SystemExit("No `platform_toolsets:` key in config.yaml. Nothing to revert.")


def _backup_path() -> Path:
    """A name that cannot land on an existing backup.

    An apply and a revert in the same second produced the same second-resolution
    name, and the second copy silently overwrote the first — so the one backup
    you would actually want back was the one destroyed.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    candidate = CONFIG.with_suffix(f".yaml.bak.{stamp}")
    suffix = 2
    while candidate.exists():
        candidate = CONFIG.with_suffix(f".yaml.bak.{stamp}_{suffix}")
        suffix += 1
    return candidate


def _write(text: str, note: str) -> Path:
    """Back up, write, and say where the backup went."""
    backup = _backup_path()
    shutil.copy2(CONFIG, backup)
    CONFIG.write_text(text)
    print(f"\nBacked up to {backup.name}")
    print(note)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the change (default is a dry run)")
    parser.add_argument("--revert", action="store_true",
                        help="remove the change again")
    args = parser.parse_args()

    if args.apply and args.revert:
        raise SystemExit("Pick one: --apply or --revert.")

    if args.revert:
        text = CONFIG.read_text()
        if platform_block(text, PLATFORM) is None:
            print(f"{PLATFORM} is not scoped. Nothing to revert.")
            return 0
        updated = remove_platform(text, PLATFORM, TOOLSETS)
        if platform_block(updated, PLATFORM) is not None:
            raise SystemExit("Refusing to write: the block is still there afterwards.")
        _write(updated, f"Removed {PLATFORM} from platform_toolsets. "
                        "Scheduled runs load the full default set again.")
        return 0

    if not CONFIG.exists():
        raise SystemExit(f"No config at {CONFIG}")
    text = CONFIG.read_text()

    current = platform_block(text, PLATFORM)
    other = platform_block(text, "whatsapp")
    print(f"whatsapp is scoped to: {other if other is not None else '(not scoped)'}")
    print(f"{PLATFORM} is scoped to:    {current if current is not None else '(not scoped — loads all 52 core tools)'}")

    if current is not None:
        if sorted(current) == sorted(TOOLSETS):
            print("\nAlready scoped. Nothing to do.")
            return 0
        print(
            f"\n{PLATFORM} is already scoped, to something other than {TOOLSETS}.\n"
            "Leaving it alone: somebody chose that, and this script only fills "
            "in a missing key."
        )
        return 1

    print(f"\nWould add:\n\n  {PLATFORM}:")
    for t in TOOLSETS:
        print(f"    - {t}")
    print(
        "\nEffect: a scheduled firing stops carrying browser, terminal, file, "
        "\nvision, image, Home Assistant, kanban and computer-use schemas."
        "\nIt keeps all nine ted_* tools, which are the only ones cron has "
        "\never called."
    )

    if not args.apply:
        print("\nDry run. Re-run with --apply to write it.")
        return 0

    updated = insert_platform(text, PLATFORM, TOOLSETS)

    # Read back through the same parser that will read it in anger, before
    # trusting the write. A config this file has corrupted once already
    # (config.yaml.corrupt.20260831) is not one to write and walk away from.
    if sorted(platform_block(updated, PLATFORM) or []) != sorted(TOOLSETS):
        raise SystemExit("Refusing to write: the result does not parse back. Config untouched.")
    # Every other platform must survive byte for byte. The one thing that would
    # make this change dangerous is narrowing somebody else's tools by accident.
    for other_platform in ("cli", "whatsapp", "telegram", "discord", "slack"):
        if platform_block(updated, other_platform) != platform_block(text, other_platform):
            raise SystemExit(
                f"Refusing to write: `{other_platform}` changed too. Config untouched."
            )

    _write(updated, f"Wrote {PLATFORM}: {TOOLSETS} into platform_toolsets.")
    print(
        "\nThe scheduler reads the config per run, so the next firing picks it "
        "up.\nCheck it landed by watching the next cold firing's prompt size "
        "drop\nfrom ~44,000 tokens toward ~20,000."
        f"\n\nUndo: python3 {Path(__file__).name} --revert"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
