"""Which stored facts count as Ted's voice, and which are the person's.

The whole risk in this script is one direction: deleting something a person
actually asked for. T14's first layer table made exactly that mistake on the
strength of key names, and `nudge_preferences` — "meals, water, supplements,
moving" — survived only because somebody read the values. So the selection is
pinned here against the real keys in the live table, both the four that go and
the ones that sound like they should and must not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-purge-voice-rules.py"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("ted_purge_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def is_voice_rule(script):
    return script.voice_rule_test()


USERS = [
    {"_id": "u1", "name": "GT", "whatsappUserId": "whatsapp:sha256:gt"},
    {"_id": "u2", "name": "Shreya", "whatsappUserId": "whatsapp:sha256:shreya"},
]


def fact(user: str, key: str, value: str = "something") -> dict:
    return {"userId": user, "key": key, "value": value}


class TestWhichKeysGo:
    """The four in the live table, and the near misses that stay."""

    @pytest.mark.parametrize("key", [
        "tone_preference",
        "chat_style_preference",
        "voice_style_preference",
        "meal_reply_rule",
    ])
    def test_the_rules_about_how_ted_talks_go(self, is_voice_rule, key):
        assert is_voice_rule(key) is True

    @pytest.mark.parametrize("key", [
        "nudge_preferences",      # "meals, water, supplements, moving"
        "daily_preference",       # "wants end of day check for missed items"
        "logging_preference",
        "coaching_preference",
        "diet_preference",
        "drink_preference",
        "activity_level",
        "health_note",
        "supplement_coq10",
        "weight_kg",
        "name",
    ])
    def test_the_persons_own_choices_stay(self, is_voice_rule, key):
        assert is_voice_rule(key) is False

    def test_it_is_the_gates_own_function(self, script, is_voice_rule):
        # Not a copy of the rule. If the gate stops refusing a key, this stops
        # deleting it the same day, and the two can never disagree about a
        # person's memory.
        import sys

        sys.path.insert(0, str(script.REPO / "hermes"))
        import ted_safety_gates

        assert is_voice_rule is ted_safety_gates.is_voice_rule_key


class TestSelection:
    def test_a_voice_rule_is_reported_with_its_owner(self, script, is_voice_rule):
        rows = script.voice_rules([fact("u1", "tone_preference")], USERS, is_voice_rule)
        assert len(rows) == 1
        assert rows[0]["name"] == "GT"
        assert rows[0]["whatsappUserId"] == "whatsapp:sha256:gt"

    def test_an_ordinary_fact_is_left_alone(self, script, is_voice_rule):
        rows = script.voice_rules([fact("u1", "weight_kg", "82")], USERS, is_voice_rule)
        assert rows == []

    def test_a_fact_whose_person_is_gone_is_not_reported(self, script, is_voice_rule):
        """They asked to be forgotten. Naming them in a report undoes that."""
        rows = script.voice_rules([fact("u9", "tone_preference")], USERS, is_voice_rule)
        assert rows == []

    def test_a_person_with_no_whatsapp_id_cannot_be_written_to(self, script, is_voice_rule):
        users = [{"_id": "u3", "name": "Nobody", "whatsappUserId": ""}]
        rows = script.voice_rules([fact("u3", "tone_preference")], users, is_voice_rule)
        assert rows == []

    def test_two_rules_on_one_person_are_one_request(self, script, is_voice_rule):
        rows = script.voice_rules(
            [fact("u1", "tone_preference"), fact("u1", "meal_reply_rule")],
            USERS, is_voice_rule,
        )
        grouped = script.by_person(rows)
        assert list(grouped) == ["whatsapp:sha256:gt"]
        assert len(grouped["whatsapp:sha256:gt"]) == 2

    def test_two_people_are_two_requests(self, script, is_voice_rule):
        rows = script.voice_rules(
            [fact("u1", "tone_preference"), fact("u2", "tone_preference")],
            USERS, is_voice_rule,
        )
        assert len(script.by_person(rows)) == 2


class TestTheWrite:
    """`--apply` is the irreversible half, so its refusals are pinned too."""

    def _reply(self, script, monkeypatch, payload):
        import io
        import json as jsonlib

        seen = {}

        class Response:
            def read(self):
                return jsonlib.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout=0):
            seen["url"] = request.full_url
            seen["body"] = jsonlib.loads(request.data.decode())
            seen["auth"] = request.headers.get("Authorization")
            return Response()

        monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
        return seen

    def test_it_asks_the_gateways_own_door_for_named_keys_only(self, script, monkeypatch):
        seen = self._reply(script, monkeypatch, {"success": True, "deleted": 2})
        env = {
            "TED_CONVEX_SITE_URL": "https://example.convex.site/",
            "TED_HERMES_SHARED_SECRET": "shh",
        }
        result = script.forget(env, "whatsapp:sha256:gt", ["tone_preference", "meal_reply_rule"])
        assert result == "deleted 2"
        assert seen["url"] == "https://example.convex.site/ted-memory"
        assert seen["auth"] == "Bearer shh"
        assert seen["body"]["action"] == "forget-facts"
        assert seen["body"]["keys"] == ["tone_preference", "meal_reply_rule"]

    def test_a_refusal_is_reported_and_never_raises(self, script, monkeypatch):
        self._reply(script, monkeypatch, {"success": False, "error": "Invalid keys"})
        result = script.forget(
            {"TED_CONVEX_SITE_URL": "https://x.convex.site", "TED_HERMES_SHARED_SECRET": "s"},
            "whatsapp:sha256:gt", ["tone_preference"],
        )
        assert result == "refused: Invalid keys"

    def test_a_dead_network_is_reported_and_never_raises(self, script, monkeypatch):
        def urlopen(request, timeout=0):
            raise OSError("no route to host")

        monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
        result = script.forget(
            {"TED_CONVEX_SITE_URL": "https://x.convex.site", "TED_HERMES_SHARED_SECRET": "s"},
            "whatsapp:sha256:gt", ["tone_preference"],
        )
        assert result.startswith("failed:")


class TestDryRunIsTheDefault:
    def test_nothing_is_written_without_apply(self, script, monkeypatch, capsys):
        import sys

        monkeypatch.setattr(script, "convex_rows", lambda table: {
            "userFacts": [fact("u1", "tone_preference", "short lowercase")],
            "users": USERS,
        }[table])

        def refuse(*args, **kwargs):
            raise AssertionError("a dry run must not write")

        monkeypatch.setattr(script, "forget", refuse)
        monkeypatch.setattr(sys, "argv", ["ted-purge-voice-rules.py"])
        assert script.main() == 0
        out = capsys.readouterr().out
        assert "Nothing was deleted" in out
        assert "short lowercase" in out

    def test_keys_only_prints_no_rule_text(self, script, monkeypatch, capsys):
        import sys

        monkeypatch.setattr(script, "convex_rows", lambda table: {
            "userFacts": [fact("u1", "tone_preference", "short lowercase")],
            "users": USERS,
        }[table])
        monkeypatch.setattr(sys, "argv", ["ted-purge-voice-rules.py", "--keys-only"])
        assert script.main() == 0
        out = capsys.readouterr().out
        assert "tone_preference" in out
        assert "short lowercase" not in out

    def test_apply_without_credentials_stops_before_reading_anything(
        self, script, monkeypatch, capsys
    ):
        import sys

        monkeypatch.setattr(script, "load_env", lambda: {})
        monkeypatch.setattr(script, "convex_rows", lambda table: (_ for _ in ()).throw(
            AssertionError("must not reach production without credentials")
        ))
        monkeypatch.setattr(sys, "argv", ["ted-purge-voice-rules.py", "--apply"])
        assert script.main() == 1
