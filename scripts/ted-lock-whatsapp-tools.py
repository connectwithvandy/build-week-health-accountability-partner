#!/usr/bin/env python3
"""Restrict Hermes' live WhatsApp toolset to Ted's three required capabilities.

Dry run by default. ``--apply`` atomically updates ``~/.hermes/config.yaml``.
The repository snapshot is maintained separately and is checked by tests.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

CONFIG = Path.home() / ".hermes" / "config.yaml"
PLATFORM = "whatsapp"
TOOLSETS = ("cronjob", "ted", "vision")


def replace_platform_toolsets(
    text: str,
    platform: str = PLATFORM,
    toolsets: tuple[str, ...] = TOOLSETS,
) -> str:
    """Replace one explicit platform block without touching nearby YAML."""
    lines = text.splitlines(keepends=True)
    try:
        top = next(i for i, line in enumerate(lines) if line.rstrip("\n") == "platform_toolsets:")
    except StopIteration as error:
        raise ValueError("No platform_toolsets block in config.yaml") from error

    header = f"  {platform}:"
    try:
        start = next(
            i
            for i in range(top + 1, len(lines))
            if lines[i].rstrip("\n") == header
        )
    except StopIteration as error:
        raise ValueError(f"No {platform} block under platform_toolsets") from error

    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line and not line[0].isspace():
            break
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        end += 1

    replacement = [f"  {platform}:\n", *(f"    - {name}\n" for name in toolsets)]
    return "".join([*lines[:start], *replacement, *lines[end:]])


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
        temporary.chmod(path.stat().st_mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the safe toolset")
    parser.add_argument("--config", type=Path, default=CONFIG, help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        before = args.config.read_text()
        after = replace_platform_toolsets(before)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1

    if before == after:
        print("WhatsApp is already limited to cronjob, ted, and vision.")
        return 0
    if not args.apply:
        print("Would remove broad WhatsApp tools and keep: cronjob, ted, vision.")
        print("Dry run. Re-run with --apply.")
        return 0

    atomic_write(args.config, after)
    print("WhatsApp is now limited to cronjob, ted, and vision.")
    print("Restart the gateway before serving another message.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
