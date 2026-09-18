from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parent / "ted-lock-whatsapp-tools.py"
SPEC = importlib.util.spec_from_file_location("ted_lock_whatsapp_tools", MODULE)
lock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lock)


CONFIG = """model:
  provider: anthropic
platform_toolsets:
  cli:
    - file
  whatsapp:
    - cronjob
    - file
    - ted
    - vision
  slack:
    - hermes-slack
fallback_model:
  provider: openrouter
"""

# The shape the live config was in when the second door was found: a plugin
# section that has seen `cli` and has never heard of `whatsapp`.
DOOR_OPEN = """platform_toolsets:
  whatsapp:
    - cronjob
    - ted
    - vision
known_plugin_toolsets:
  # spotify deliberately NOT offered on whatsapp.
  cli:
    - spotify
fallback_model:
  provider: openrouter
"""


def test_replaces_only_the_whatsapp_block():
    updated = lock.replace_platform_toolsets(CONFIG)
    assert "  cli:\n    - file\n" in updated
    assert "  whatsapp:\n    - cronjob\n    - ted\n    - vision\n" in updated
    assert "  slack:\n    - hermes-slack\n" in updated
    assert updated.count("    - file\n") == 1


def test_is_idempotent():
    once = lock.replace_platform_toolsets(CONFIG)
    assert lock.replace_platform_toolsets(once) == once


def test_refuses_to_invent_the_parent_block():
    try:
        lock.replace_platform_toolsets("model:\n  provider: anthropic\n")
    except ValueError as error:
        assert "platform_toolsets" in str(error)
    else:
        raise AssertionError("missing parent block should be refused")


def test_refuses_to_invent_whatsapp_scope():
    try:
        lock.replace_platform_toolsets("platform_toolsets:\n  cron:\n    - ted\n")
    except ValueError as error:
        assert "whatsapp" in str(error)
    else:
        raise AssertionError("missing WhatsApp block should be refused")


def test_marks_whatsapp_as_having_seen_every_plugin_toolset():
    updated = lock.close_plugin_door(DOOR_OPEN)
    assert "  whatsapp:\n    - spotify\n    - ted\n" in updated


def test_leaves_the_cli_entry_and_its_comment_alone():
    updated = lock.close_plugin_door(DOOR_OPEN)
    assert "  # spotify deliberately NOT offered on whatsapp.\n" in updated
    assert "  cli:\n    - spotify\n" in updated


def test_does_not_disturb_the_key_after_the_block():
    updated = lock.close_plugin_door(DOOR_OPEN)
    assert updated.endswith("fallback_model:\n  provider: openrouter\n")
    assert updated.count("fallback_model:") == 1


def test_closing_the_door_is_idempotent():
    once = lock.close_plugin_door(DOOR_OPEN)
    assert lock.close_plugin_door(once) == once


def test_replaces_a_stale_whatsapp_entry_rather_than_adding_a_second():
    stale = DOOR_OPEN.replace(
        "  cli:\n    - spotify\n",
        "  cli:\n    - spotify\n  whatsapp:\n    - spotify\n",
    )
    updated = lock.close_plugin_door(stale)
    plugin_block = updated.split("known_plugin_toolsets:\n", 1)[1]
    assert plugin_block.count("  whatsapp:\n") == 1
    assert "  whatsapp:\n    - spotify\n    - ted\n" in plugin_block


def test_refuses_to_invent_the_plugin_block():
    try:
        lock.close_plugin_door("platform_toolsets:\n  whatsapp:\n    - ted\n")
    except ValueError as error:
        assert "known_plugin_toolsets" in str(error)
    else:
        raise AssertionError("missing plugin block should be refused")


def test_the_two_doors_do_not_touch_each_other():
    both = lock.close_plugin_door(lock.replace_platform_toolsets(DOOR_OPEN))
    assert "platform_toolsets:\n  whatsapp:\n    - cronjob\n    - ted\n    - vision\n" in both
    assert "known_plugin_toolsets:" in both
    assert both.count("  whatsapp:\n") == 2
