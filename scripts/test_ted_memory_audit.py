"""What the memory audit must not claim about two stores it has not compared.

Three of these are mistakes this file made against the real table, and all
three reported something more confident than what was measured:

1. It printed "all 43 agree" having compared nothing. The value was never read
   out of the row, so every mirrored fact fell into the "present, therefore
   fine" branch. Presence is not agreement.
2. Once it did compare, it reported eight `goal` facts as drift. Seven were the
   same goal in two vocabularies — `users.goal` holds `loseWeight`, the fact
   beside it says "lose weight". An enum and free text cannot be diffed as
   strings, and saying they disagree is a false alarm that costs trust.
3. A key it did not recognise was silently dropped from the layer counts,
   which made the layers add up to less than the facts and nobody notice.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-memory-audit.py"

SPEC = importlib.util.spec_from_file_location("ted_memory_audit", _SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def facts(*specs):
    """(key, user, value) triples in the shape `analyse` consumes."""
    return [
        {
            "key": key,
            "user": user,
            "layer": audit.layer_of(key),
            "value_chars": len(value),
            "value_norm": audit._norm(value),  # noqa: SLF001
            "use_count": use,
            "last_used": "",
        }
        for key, user, value, use in specs
    ]


# ── Layering ───────────────────────────────────────────────────────────


def test_every_layer_name_is_one_t14_asks_for_or_the_one_it_missed():
    allowed = {"profile", "behavioural", "health", "preference", "instruction"}
    assert set(audit.LAYERS.values()) <= allowed


def test_teds_own_voice_rules_are_not_facts_about_the_person():
    """The layer T14 does not name, and the reason it had to be added.

    Every one of these restates SOUL.md's "How I talk": short, lowercase,
    hinglish, one thought, no dashes, no receipt-style replies.
    """
    for key in (
        "tone_preference",
        "chat_style_preference",
        "voice_style_preference",
        "meal_reply_rule",
    ):
        assert audit.layer_of(key) == "instruction", key


def test_a_preference_that_sounds_like_an_instruction_is_still_the_persons():
    """The misfiling this table made, and the argument for a fixed vocabulary.

    `nudge_preferences` is "meals, water, supplements, moving" — which nudges
    this person wants. `daily_preference` is "wants end of day check for missed
    items". Both were filed as `instruction` on the strength of the key name,
    and deleting them as duplicated voice rules would have thrown away the only
    record of what the user asked for.

    A layer decided from a key the model invented is a layer decided from a
    guess. That is why the key vocabulary has to be fixed before retrieval
    rules can be keyed on a layer.
    """
    for key in (
        "nudge_preferences",
        "daily_preference",
        "logging_preference",
        "coaching_preference",
    ):
        assert audit.layer_of(key) == "preference", key


def test_a_misspelled_supplement_is_still_a_health_fact():
    """`suppplement_vitamin_b12`, three p's, is in the live table.

    Enumerating supplement keys cannot work — the model names each one — so
    the prefix rule is what catches the typo, and nothing else does.
    """
    assert audit.layer_of("supplement_vitamin_d") == "health"
    assert audit.layer_of("suppplement_vitamin_b12") == "health"


def test_an_unknown_key_is_unclassified_not_guessed():
    assert audit.layer_of("favourite_biryani") == "unclassified"


def test_unclassified_keys_are_still_counted(monkeypatch):
    """A key nobody recognised must not vanish from the totals."""
    data = {
        "facts": facts(("favourite_biryani", "u1", "hyderabadi", 0)),
        "users": {"u1": {}},
    }
    found = audit.analyse(data)
    assert found["facts"] == 1
    assert found["layers"]["unclassified"]["facts"] == 1
    assert found["unclassified_keys"] == ["favourite_biryani"]


def test_layer_counts_add_up_to_the_facts():
    data = {
        "facts": facts(
            ("name", "u1", "Asha", 0),
            ("activity_level", "u1", "desk job", 0),
            ("tone_preference", "u1", "lowercase", 0),
            ("supplement_coq10", "u1", "100mg", 0),
            ("favourite_biryani", "u1", "hyderabadi", 0),
        ),
        "users": {"u1": {}},
    }
    found = audit.analyse(data)
    assert sum(r["facts"] for r in found["layers"].values()) == found["facts"]


# ── The two stores ─────────────────────────────────────────────────────


def test_presence_is_not_agreement():
    """Mistake 1. A fact whose counterpart could not be read is `unreadable`.

    It must never be counted as agreeing — that is how the first version
    printed "all 43 agree" having compared nothing at all.
    """
    data = {
        "facts": facts(("weight_kg", "u1", "", 0)),
        "users": {"u1": {"weightKg": "72"}},
    }
    mirror = audit.analyse(data)["mirrored_in_users_table"]
    assert mirror["facts"] == 1
    assert mirror["agreeing"] == 0
    assert mirror["uncompared"] == 1


def test_a_real_disagreement_is_reported():
    data = {
        "facts": facts(("weight_kg", "u1", "81", 0)),
        "users": {"u1": {"weightKg": "72"}},
    }
    mirror = audit.analyse(data)["mirrored_in_users_table"]
    assert mirror["disagreeing"] == ["weight_kg"]


def test_formatting_differences_are_not_drift():
    """"175" against "175.0", "Male" against "male"."""
    data = {
        "facts": facts(
            ("height_cm", "u1", "175", 0),
            ("gender", "u2", "Male", 0),
        ),
        "users": {"u1": {"heightCm": "175.0"}, "u2": {"sex": "male"}},
    }
    mirror = audit.analyse(data)["mirrored_in_users_table"]
    assert mirror["agreeing"] == 2
    assert mirror["disagreeing"] == []


def test_goal_is_never_reported_as_drift():
    """Mistake 2. An enum and free text are two vocabularies, not a conflict.

    `users.goal` is `loseWeight`; the fact beside it says "lose weight". Seven
    of eight live rows are exactly this, and calling them drift is a false
    alarm. They are counted as incomparable, and the report says why.
    """
    data = {
        "facts": facts(
            ("goal", "u1", "lose weight", 0),
            ("goal", "u2", "holding steady", 0),
        ),
        "users": {"u1": {"goal": "loseWeight"}, "u2": {"goal": "maintainWeight"}},
    }
    mirror = audit.analyse(data)["mirrored_in_users_table"]
    assert mirror["disagreeing"] == []
    assert mirror["incomparable"] == {"goal": 2}
    assert mirror["facts"] == 2


def test_a_fact_with_no_counterpart_is_not_mirrored():
    data = {
        "facts": facts(("weight_kg", "u1", "72", 0)),
        "users": {"u1": {}},
    }
    assert audit.analyse(data)["mirrored_in_users_table"]["facts"] == 0


# ── Supersession ───────────────────────────────────────────────────────


def test_a_repeated_character_typo_is_caught():
    """The live case: one user holds both spellings, and both go to the model."""
    data = {
        "facts": facts(
            ("supplement_vitamin_b12", "u1", "1000mcg", 0),
            ("suppplement_vitamin_b12", "u1", "1500mcg", 0),
        ),
        "users": {"u1": {}},
    }
    found = audit.analyse(data)
    assert len(found["key_collisions"]) == 1
    assert found["key_collisions"][0][2] == "repeated character"


def test_one_key_containing_another_is_caught():
    data = {
        "facts": facts(("goal", "u1", "lose weight", 0), ("goal_raw", "u1", "cut", 0)),
        "users": {"u1": {}},
    }
    assert audit.analyse(data)["key_collisions"]


def test_the_same_key_in_two_users_is_not_a_collision():
    """Two people each having a `name` is the system working."""
    data = {
        "facts": facts(("name", "u1", "Asha", 0), ("name", "u2", "Ravi", 0)),
        "users": {"u1": {}, "u2": {}},
    }
    assert audit.analyse(data)["key_collisions"] == []


def test_unrelated_keys_in_one_user_are_not_a_collision():
    data = {
        "facts": facts(
            ("name", "u1", "Asha", 0),
            ("activity_level", "u1", "desk job", 0),
        ),
        "users": {"u1": {}},
    }
    assert audit.analyse(data)["key_collisions"] == []


# ── Reuse, and refusing to read it early ───────────────────────────────


def test_reuse_carries_its_ripening_date():
    """Mistake 3's cousin: a zero here means "not measured yet" until 23 Sep.

    Commit d554a88 shipped the counter on 16 Sep and asked for a week of live
    serving first. The date travels with the number so nobody reads a 1% as a
    verdict on whether memory works.
    """
    data = {
        "facts": facts(("name", "u1", "Asha", 0), ("activity_level", "u1", "x", 3)),
        "users": {"u1": {}},
    }
    reuse = audit.analyse(data)["reuse"]
    assert reuse["facts_ever_reused"] == 1
    assert reuse["ripens_at"] == audit.RIPENS_AT == "2026-09-23"


def test_no_facts_does_not_divide_by_zero():
    found = audit.analyse({"facts": [], "users": {}})
    assert found["facts"] == 0
    assert found["reuse"]["facts_ever_reused"] == 0


# ── Reading the table ──────────────────────────────────────────────────


def test_columns_are_read_by_name_not_position():
    """`npx convex data` prints only the columns its sample happens to have.

    A row read by position silently shifts the moment a user without an `age`
    is sampled, which is how a height ends up reported as a weight.
    """
    header = ["_id", "age", "name", "weightKg"]
    row = ["u1", "22", "Asha", "72"]
    assert audit.cell(header, row, "name") == "Asha"
    assert audit.cell(header, row, "weightKg") == "72"
    assert audit.cell(header, row, "heightCm") == ""


def test_norm_leaves_words_alone():
    assert audit._norm("  Holding Steady ") == "holding steady"  # noqa: SLF001
    assert audit._norm("175.0") == "175"  # noqa: SLF001


def test_norm_only_strips_a_fractional_zero():
    """Written while the first version turned 1000 into 1.

    Trailing zeros are noise after a decimal point and load-bearing before
    one. Stripping them from any digit string would have called a 1000mcg dose
    and a 100mcg one the same fact, and reported agreement between two stores
    holding different doses.
    """
    assert audit._norm("1000") == "1000"  # noqa: SLF001
    assert audit._norm("100") == "100"  # noqa: SLF001
    assert audit._norm("72.50") == "72.5"  # noqa: SLF001
    assert audit._norm("1000mcg") == "1000mcg"  # noqa: SLF001
