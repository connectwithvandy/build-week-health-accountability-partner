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
