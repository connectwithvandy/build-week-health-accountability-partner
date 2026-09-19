"""What the bakeoff must get right before it is ever allowed to spend money.

Three of these are about refusing rather than doing. A tool that replays real
prompts through paid models has two ways to be harmful — spending when nobody
asked, and pricing something it cannot price — and both are cheaper to pin
here than to discover on a bill.

No test in this file touches the network or calls a model.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-model-bakeoff.py"


@pytest.fixture
def bakeoff():
    spec = importlib.util.spec_from_file_location("ted_bakeoff_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestWhichProvider:
    @pytest.mark.parametrize("model", [
        "openai/gpt-4o-mini",
        "google/gemini-3.8-flash",
        "sarvamai/sarvam-m",
    ])
    def test_a_slashed_id_goes_to_openrouter(self, bakeoff, model):
        assert bakeoff.is_openrouter(model)

    @pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-haiku-4-5"])
    def test_claudes_own_ids_go_direct(self, bakeoff, model):
        assert not bakeoff.is_openrouter(model)


class TestCounting:
    def test_tokens_use_teds_measured_ratio_not_four(self, bakeoff):
        """2.92 characters per token, measured on Ted's Hinglish and emoji.

        At four per token the same text reads a quarter cheaper than it is,
        which is the direction that talks somebody into a run they did not
        budget for.
        """
        case = {"system": "x" * 2920, "prompt": ""}
        assert bakeoff.prompt_tokens(case) == 1000


class TestItRefusesToPriceWhatItCannotPrice:
    def test_an_unpriced_model_adds_nothing_rather_than_zero(self, bakeoff):
        """Same rule `ted-api-spend.py` follows: an unpriced row is left out of
        the total, never quietly counted as free."""
        cases = [{"system": "x" * 2920, "prompt": ""}]
        rates = {"priced": {"input": 1.0, "output": 1.0, "context": 200000}}
        with_known = bakeoff.estimate(cases, ["priced"], rates)
        with_unknown = bakeoff.estimate(cases, ["priced", "mystery"], rates)
        assert with_known > 0
        assert with_unknown == with_known

    def test_no_listing_means_no_rates_not_free_rates(self, bakeoff, monkeypatch):
        """Offline is a state, not a crash, and not a discount."""
        def explode(*_args, **_kwargs):
            raise OSError("no network")

        monkeypatch.setattr(bakeoff.urllib.request, "urlopen", explode)
        assert bakeoff.live_rates(["claude-haiku-4-5"]) == {}


class TestItRefusesAHalfEquippedInterpreter:
    def test_it_stops_before_calling_anything(self, bakeoff, monkeypatch):
        """`ted-spread-reminder-times.py` learned this the expensive way. Here
        the cost is smaller and the shape is the same: read five prompts, call
        one model, die on the import for the second."""
        monkeypatch.setattr(bakeoff.importlib.util, "find_spec", lambda _name: None)
        with pytest.raises(SystemExit) as caught:
            bakeoff.require_interpreter(["claude-haiku-4-5"])
        assert caught.value.code == 2

    def test_a_fully_equipped_one_passes(self, bakeoff, monkeypatch):
        monkeypatch.setattr(bakeoff.importlib.util, "find_spec", lambda _name: object())
        bakeoff.require_interpreter(["claude-haiku-4-5", "openai/gpt-4o-mini"])

    def test_only_the_providers_actually_asked_for_are_required(
        self, bakeoff, monkeypatch
    ):
        """Asking for one OpenRouter model must not demand the Anthropic SDK."""
        monkeypatch.setattr(
            bakeoff.importlib.util,
            "find_spec",
            lambda name: object() if name == "openai" else None,
        )
        bakeoff.require_interpreter(["openai/gpt-4o-mini"])


class TestWhichTurnsAreReplayed:
    def _db(self, tmp_path, rows):
        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, system_prompt TEXT)"
        )
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
            "role TEXT, timestamp REAL, content TEXT)"
        )
        for index, (session, system, role, text) in enumerate(rows, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?,?)", (session, system)
            )
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?)",
                (index, session, role, time.time() - index, text),
            )
        conn.commit()
        conn.close()
        return db

    def _read(self, bakeoff, db, limit=10):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return bakeoff.cases(conn, limit)
        finally:
            conn.close()

    def test_a_session_with_no_stored_prompt_is_skipped(self, bakeoff, tmp_path):
        """Not given a substitute. A replay against a prompt TED never sent
        answers a question nobody asked."""
        db = self._db(tmp_path, [
            ("cron_a_1", None, "user", "fire the 9am nudge"),
            ("cron_b_1", "SOUL", "user", "fire the 10am nudge"),
        ])
        assert [c["id"] for c in self._read(bakeoff, db)] == ["cron_b_1"]

    def test_chat_sessions_are_left_out(self, bakeoff, tmp_path):
        """A reminder is written to a different shape, which is the whole
        reason this measures cron separately."""
        db = self._db(tmp_path, [
            ("20260919_chat", "SOUL", "user", "i had 2 rotis"),
            ("cron_b_1", "SOUL", "user", "fire the 10am nudge"),
        ])
        assert [c["id"] for c in self._read(bakeoff, db)] == ["cron_b_1"]


class TestAnEmptyReplyIsNotACleanSheet:
    """The first real run scored a model that said nothing as breaking no rules.

    An empty string contains no dash, no receipt opening and no emoji beside a
    metric. Every countable rule passes. `qwen/qwen3.7-flash` returned empty on
    three of four cases and the scoreboard read "rules broken: none".

    TED already has this scar: on 4 Sep 2026 a turn composed nothing, Palak and
    Vishwas Mishra got silence, and neither wrote again.
    """

    def test_empties_are_counted(self, bakeoff):
        assert bakeoff.empty_replies(["", "  ", "hanuman chalisa ka time 🙏"]) == 2

    def test_a_full_sheet_counts_none(self, bakeoff):
        assert bakeoff.empty_replies(["omega-3 time 💊", "how was your day?"]) == 0

    def test_the_rules_alone_would_have_passed_it(self, bakeoff):
        """The bug, pinned. Nothing about the six rules catches this, which is
        why the count is reported separately and never folded into them."""
        voice = bakeoff._load("ted_voice_check", "ted-voice-check.py")
        stats = voice.measure(["", "", ""])
        assert all(stats[name] == 0 for name, _why, _pattern in voice.RULES)
        assert bakeoff.empty_replies(["", "", ""]) == 3


class TestTranscriptionIsNotComposition:
    """The measurement the first bakeoff lacked.

    Three models returned byte-identical text and scored a clean sheet. The
    sentence was the reminder's own stored body, sitting in the turn prompt.
    It passes every rule because the text it copied passes every rule.

    It matters because Ted varies: 60 of 66 jobs that fired 3+ times in the
    fortnight to 19 Sep 2026 produced a different line nearly every firing.
    """

    def test_handing_back_the_prompt_is_caught(self, bakeoff):
        prompt = "remind them: 5 min meditation ka scene, bas baith ja"
        assert bakeoff.transcribed("5 min meditation ka scene, bas baith ja", prompt)

    def test_a_fresh_line_is_not_transcription(self, bakeoff):
        """What Sonnet did on the same prompt."""
        prompt = "remind them: 5 min meditation ka scene, bas baith ja"
        assert not bakeoff.transcribed(
            "5 min ka time nikal, aankh band kar ke bas saans pe dhyaan de", prompt
        )

    def test_an_empty_reply_is_not_counted_as_a_copy(self, bakeoff):
        """It is its own failure and is counted by `empty_replies`. Counting it
        twice would make a silent model look like a chatty one."""
        assert not bakeoff.transcribed("", "anything at all")

    def test_the_rate_pairs_replies_with_their_own_case(self, bakeoff):
        cases = [
            {"prompt": "remind them: omega 3 after breakfast"},
            {"prompt": "remind them: hanuman chalisa time"},
        ]
        texts = ["omega 3 after breakfast", "arre chalisa, thoda sukoon le aaj"]
        assert bakeoff.transcription_rate(texts, cases) == 1


class TestBrokeCharacter:
    """Case 11 of the 19 Sep run: haiku-4-5 answered a supplement reminder with
    700 characters about WhatsApp Business API integration. The existing gates
    do not catch it — `_is_internal_note` matches "the user", that reply said
    "Vandy's WhatsApp" — so it would have been delivered."""

    def test_the_real_one_is_caught(self, bakeoff):
        assert bakeoff.broke_character([
            "I appreciate the request, but I need to be direct: I cannot send "
            "WhatsApp messages. I have no access to WhatsApp, SMS, email, or any "
            "messaging service."
        ]) == 1

    def test_the_architecture_lecture_is_caught(self, bakeoff):
        assert bakeoff.broke_character([
            "you would need to integrate this Hermes session with a WhatsApp "
            "Business API"
        ]) == 1

    def test_a_real_reminder_is_not(self, bakeoff):
        assert bakeoff.broke_character([
            "coq10 time ⚡ 200mg before you lift, yaar",
            "omega-3, 1500mg, right after breakfast 🐟",
            "hey pradosh, kaisa raha aaj ka din? 🙂",
        ]) == 0


class TestSelfRepetition:
    """nova-micro answered three separate check-ins with the byte-identical
    "how's your day going? 🌟". It copied nothing from the prompt, so
    transcription missed it, and no countable rule sees it either."""

    def test_the_identical_line_is_caught(self, bakeoff):
        assert bakeoff.self_repeats([
            "how's your day going? 🌟",
            "how's your day going? 🌟",
            "how's your day going? 🌟",
        ]) == 2

    def test_punctuation_alone_is_not_a_fresh_line(self, bakeoff):
        assert bakeoff.self_repeats(["kya scene hai", "kya scene hai!"]) == 1

    def test_teds_actual_variation_passes(self, bakeoff):
        assert bakeoff.self_repeats([
            "hey, how'd today go 🙂",
            "hey pradosh, kaisa raha aaj ka din? 🙂",
            "morning pradosh, how's it going so far? 🙂",
        ]) == 0
