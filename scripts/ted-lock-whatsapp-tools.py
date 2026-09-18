#!/usr/bin/env python3
"""Restrict Hermes' live WhatsApp toolset to Ted's required capabilities.

Two lists, not one. ``platform_toolsets.whatsapp`` decides which *built-in*
toolsets WhatsApp carries. Plugin toolsets are resolved in a separate pass
(`hermes_cli/tools_config.py`, `_get_platform_tools`) that the explicit list
does not reach: a plugin toolset is enabled unless the platform has seen it,
and "seen" means its name appears under ``known_plugin_toolsets.<platform>``.
WhatsApp has no entry, so `spotify` is off it only because of
`_DEFAULT_OFF_TOOLSETS`, a list inside Hermes that an upgrade may rewrite.

Recording the installed plugins makes that our decision rather than Hermes'.
**It does not close the case for a plugin installed later** — that one is
unseen by definition, on every platform, and arrives enabled. Measured, not
assumed: a config with this entry and one without resolve identically for a
plugin toolset neither has heard of. Noticing a new plugin is the gate guard's
job, not this script's.

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

# Every plugin toolset installed here, as of 19 Sep 2026. Listing one marks it
# *seen* by WhatsApp, which is what turns Hermes' "new plugin, default on" rule
# off for it. `ted` is listed and still arrives, because it is in TOOLSETS and
# an explicit entry wins; `spotify` is listed and does not, which is the point.
# A plugin installed after this date is unseen again by definition — that case
# belongs to the guard, which watches for a plugin appearing at all.
PLUGIN_TOOLSETS = ("spotify", "ted")


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


def close_plugin_door(
    text: str,
    platform: str = PLATFORM,
    toolsets: tuple[str, ...] = PLUGIN_TOOLSETS,
) -> str:
    """Record every installed plugin toolset as seen by one platform.

    Rewrites the platform's block under ``known_plugin_toolsets`` if it exists
    and appends it if it does not. The parent key is never invented: Hermes
    writes it itself the first time ``hermes tools`` is saved, and a version
    that has never written it may not read it either.
    """
    lines = text.splitlines(keepends=True)
    try:
        top = next(
            i
            for i, line in enumerate(lines)
            if line.rstrip("\n") == "known_plugin_toolsets:"
        )
    except StopIteration as error:
        raise ValueError("No known_plugin_toolsets block in config.yaml") from error

    # The end of the parent block: the next line at column zero.
    end_of_parent = len(lines)
    for index in range(top + 1, len(lines)):
        if lines[index].strip() and not lines[index][0].isspace():
            end_of_parent = index
            break

    replacement = [f"  {platform}:\n", *(f"    - {name}\n" for name in toolsets)]

    header = f"  {platform}:"
    start = None
    for index in range(top + 1, end_of_parent):
        if lines[index].rstrip("\n") == header:
            start = index
            break

    if start is None:
        return "".join([*lines[:end_of_parent], *replacement, *lines[end_of_parent:]])

    stop = start + 1
    while stop < end_of_parent:
        line = lines[stop]
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        stop += 1
    return "".join([*lines[:start], *replacement, *lines[stop:]])


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
        scoped = replace_platform_toolsets(before)
        after = close_plugin_door(scoped)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1

    tools_change = scoped != before
    door_change = after != scoped

    if not tools_change and not door_change:
        print("WhatsApp is already limited to cronjob, ted, and vision,")
        print("and the plugins installed here are already recorded against it.")
        return 0

    if not args.apply:
        if tools_change:
            print("Would remove broad WhatsApp tools and keep: cronjob, ted, vision.")
        if door_change:
            print(
                "Would record "
                + ", ".join(PLUGIN_TOOLSETS)
                + " as seen by WhatsApp, so those two stop"
            )
            print("depending on a Hermes default. Only `ted` keeps its tools.")
            print("A plugin installed later is still unseen, and still arrives on.")
        print("Dry run. Re-run with --apply.")
        return 0

    atomic_write(args.config, after)
    if tools_change:
        print("WhatsApp is now limited to cronjob, ted, and vision.")
    if door_change:
        print("WhatsApp has recorded the plugins installed here; spotify is off it")
        print("by decision now rather than by a Hermes default.")
    print("Restart the gateway before serving another message.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
