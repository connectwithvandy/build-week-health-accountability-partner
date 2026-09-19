#!/usr/bin/env python3
"""Restrict every live WhatsApp toolset to Ted's required capabilities.

**Every** WhatsApp, not the Baileys one. The Cloud API adapter is a second
platform key, `whatsapp_cloud`, with its own scope, and on 19 Sep 2026 it was
live and absent from `platform_toolsets` — so it was running on
`hermes-whatsapp`, which is the full core tool set: terminal, files, patch and
the browser, on a channel open to strangers. Scoping one key and not the other
is how that happened, so this script now walks the same platform list the gate
guard does.

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
import re
import tempfile
from pathlib import Path

CONFIG = Path.home() / ".hermes" / "config.yaml"
HERMES_ENV = Path.home() / ".hermes" / ".env"
PLATFORM = "whatsapp"
TOOLSETS = ("cronjob", "ted", "vision")


def _env_set(name: str, env_path: Path = HERMES_ENV) -> bool:
    """Whether one variable is set, in the environment or in ~/.hermes/.env."""
    if os.environ.get(name):
        return True
    try:
        text = env_path.read_text()
    except OSError:
        return False
    return bool(re.search(rf"^\s*{name}\s*=\s*\S", text, re.MULTILINE))


def live_whatsapp_platforms(env_path: Path = HERMES_ENV) -> list[str]:
    """Every WhatsApp platform that can actually reach a person right now.

    `gateway/config.py` adds `whatsapp_cloud` the moment a phone id and an
    access token are both set; there is no enable flag. Mirroring that test
    rather than keeping a list means a channel cannot go live unscoped, which
    is exactly what happened before this existed. `scripts/ted-gate-guard.py`
    asks the same question, and the two must agree.
    """
    platforms = [PLATFORM]
    if _env_set("WHATSAPP_CLOUD_PHONE_NUMBER_ID", env_path) and _env_set(
        "WHATSAPP_CLOUD_ACCESS_TOKEN", env_path
    ):
        platforms.append("whatsapp_cloud")
    return platforms

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
    start = next(
        (
            i
            for i in range(top + 1, len(lines))
            if lines[i].rstrip("\n") == header
        ),
        None,
    )

    if start is None:
        # An absent platform is not an absent scope. Hermes falls back to that
        # platform's default toolset, and for a WhatsApp that default is the
        # full core tool set, so adding the block *is* the fix rather than an
        # error to report. Insert it at the end of platform_toolsets.
        end_of_parent = len(lines)
        for index in range(top + 1, len(lines)):
            if lines[index].strip() and not lines[index][0].isspace():
                end_of_parent = index
                break
        block = [f"  {platform}:\n", *(f"    - {name}\n" for name in toolsets)]
        return "".join([*lines[:end_of_parent], *block, *lines[end_of_parent:]])

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

    platforms = live_whatsapp_platforms()

    try:
        before = args.config.read_text()
        text = before
        scoped_platforms = []
        recorded_platforms = []
        for platform in platforms:
            stepped = replace_platform_toolsets(text, platform)
            if stepped != text:
                scoped_platforms.append(platform)
            text = stepped
            stepped = close_plugin_door(text, platform)
            if stepped != text:
                recorded_platforms.append(platform)
            text = stepped
        after = text
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1

    tools_change = bool(scoped_platforms)
    door_change = bool(recorded_platforms)

    print("Checking: " + ", ".join(platforms))

    if not tools_change and not door_change:
        print("Every live WhatsApp is already limited to cronjob, ted, and vision,")
        print("and the plugins installed here are already recorded against each.")
        return 0

    if not args.apply:
        if tools_change:
            print(
                "Would scope "
                + ", ".join(scoped_platforms)
                + " to cronjob, ted, vision, removing broad tools."
            )
        if door_change:
            print(
                "Would record "
                + ", ".join(PLUGIN_TOOLSETS)
                + " as seen by "
                + ", ".join(recorded_platforms)
                + ", so those two stop"
            )
            print("depending on a Hermes default. Only `ted` keeps its tools.")
            print("A plugin installed later is still unseen, and still arrives on.")
        print("Dry run. Re-run with --apply.")
        return 0

    atomic_write(args.config, after)
    if tools_change:
        print(
            ", ".join(scoped_platforms)
            + " is now limited to cronjob, ted, and vision."
        )
        # Only this half changes what a live turn carries. The recording half
        # changes why a plugin is off, not which tools load, and telling
        # somebody to restart for it costs real people a real outage for a
        # resolved toolset list that is identical either way.
        print("Restart the gateway before serving another message.")
    if door_change:
        print(
            ", ".join(recorded_platforms)
            + " has recorded the plugins installed here; spotify is off it"
        )
        print("by decision now rather than by a Hermes default.")
        if not tools_change:
            print("No restart needed: the toolsets a turn carries are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
