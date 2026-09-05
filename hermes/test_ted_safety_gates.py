import json
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from hermes import ted_safety_gates as gates
from hermes.ted_safety_gates import (
    DISCLOSURE_MESSAGE,
    GOAL_QUESTION,
    OPENING_MESSAGE,
    action_claim_gate,
    calorie_gate,
    consent_gate,
    transform_response,
    _capture_turn,
    _load_disclosure_state,
    _log_disclosure,
    _record_tool_success,
    _transform_live_response,
)


def message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def reset_user(user_key: str) -> None:
    """Wipe a test key completely, tombstone included.

    `_forget_user` is production behaviour, not a reset: it deliberately
    leaves a `forgotten_at` mark so a live erasure cannot be undone by a
    thread that is still open. Used as teardown it therefore leaks a
    forgotten user into the next test in the class, which is exactly what
    happened — six meal-breakdown tests started demanding a fresh disclosure.
    Teardown wants the key gone, so it says so.
    """
    gates._forget_user(user_key)
    with gates._ONBOARDING_LOCK:
        gates._ONBOARDING_STATE.pop(user_key, None)


# The notice first and nameless, then why, then question one. Spelled out
# rather than built from the constants: this is the message a real person
# gets after giving their name, and it should be readable as one here.
VANDY_DISCLOSURE = (
    f"{DISCLOSURE_MESSAGE}\n\n"
    "right Vandy, before i’m any use to you, quick six questions to get "
    "your calorie number. one minute tops, pakka promise \U0001f91e\n\n"
    "*1/6* how old are you? beta's 18+"
)


class TedSafetyGatesTest(unittest.TestCase):
    def test_prepared_start_uses_exact_lowercase_copy(self) -> None:
        self.assertEqual(
            transform_response(
                history=[message("user", "Okay Ted, let's do this!")],
                user_message="Okay Ted, let's do this!",
                response_text="A different model-generated opener.",
            ),
            OPENING_MESSAGE,
        )

    def test_replays_calorie_failure_without_returning_a_number(self) -> None:
        history: list[dict[str, str]] = []
        expected = gates.AGE_QUESTION

        for user_text in ("Track calories", "It's ragi roti", "It's only 1 roti"):
            history.append(message("user", user_text))
            reply = calorie_gate(history, user_text, "About 120 calories.")
            self.assertEqual(reply, expected)
            self.assertNotRegex(reply or "", r"\b120\b")
            history.append(message("assistant", reply or ""))

    def test_accepts_a_bare_age_reply_from_the_current_turn(self) -> None:
        history = [
            message("user", "Meal and steps"),
            message("assistant", "I need your age before I can give calorie numbers."),
        ]
        self.assertIsNone(
            calorie_gate(history, "33", "Got it — what are your steps today?")
        )

    def test_golden_path_reaches_past_the_age_gate(self) -> None:
        history = [message("user", "Okay Ted, let's do this!")]
        opener = (
            "here's the deal: you tell me what you ate or got done, "
            "i keep score and close out the day with a recap. "
            "what should i call you?"
        )
        self.assertEqual(
            transform_response(
                history=history,
                user_message=history[0]["content"],
                response_text=opener,
            ),
            OPENING_MESSAGE,
        )
        history.extend([message("assistant", opener), message("user", "Vandy")])
        disclosure = transform_response(
            history=history,
            user_message="Vandy",
            response_text="what's one thing you want to change?",
        )
        self.assertEqual(disclosure, VANDY_DISCLOSURE)
        history.extend([message("assistant", disclosure or ""), message("user", "Meal and steps")])
        # A per-food estimate is not a calorie target, so it goes out as Ted
        # wrote it. Demanding an age here was the bug.
        meal_reply = "roughly 280 calories, 14g protein."
        self.assertIsNone(
            transform_response(
                history=history,
                user_message="Meal and steps",
                response_text=meal_reply,
            )
        )
        history.extend(
            [message("assistant", meal_reply), message("user", "what should my calorie target be?")]
        )
        target_gate = transform_response(
            history=history,
            user_message="what should my calorie target be?",
            response_text="let's work out maintenance first.",
        )
        self.assertEqual(target_gate, gates.AGE_QUESTION)
        history.append(message("assistant", target_gate or ""))
        # The age is accepted and the gate moves on to the next missing field
        # instead of asking for the age again.
        after_age = transform_response(
            history=history,
            user_message="33",
            response_text="got it — what's your daily step target?",
        )
        self.assertEqual(after_age, "before i can do that maths, how tall are you?")

    def test_blocks_under_18(self) -> None:
        history = [message("user", "I am 17 and want to track calories")]
        self.assertEqual(
            calorie_gate(history, history[0]["content"], "Try 1,400 calories."),
            gates.UNDER_18_REFUSAL,
        )

    def test_requires_one_missing_maintenance_input(self) -> None:
        history = [message("user", "I am 33, 5 ft, 58 kg and female")]
        self.assertEqual(
            calorie_gate(history, "Estimate maintenance calories", "2,300 calories"),
            "last one. how active is a normal day? desk most of it, on your feet, "
            "or training regularly?",
        )

    def test_calculates_maintenance_from_supplied_values_without_a_deficit(self) -> None:
        history = [
            message("user", "I am 33, female, 5 ft, 58 kg, and active"),
        ]
        reply = calorie_gate(
            history,
            "Give me a calorie target",
            "Your maintenance is 2,300 and 1,400 is a reasonable deficit.",
        )
        self.assertEqual(
            reply,
            "rough maintenance is about 2,080 calories a day, "
            "worked out only from the numbers you gave me.",
        )
        self.assertNotIn("deficit", reply or "")

    def test_disclosure_is_forced_after_name_and_only_once(self) -> None:
        history = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]
        self.assertEqual(consent_gate(history, "What is your goal?"), VANDY_DISCLOSURE)

        history.append(message("assistant", VANDY_DISCLOSURE))
        self.assertIsNone(consent_gate(history, "What is your goal?"))

    def test_disclosure_uses_a_name_given_in_a_sentence(self) -> None:
        history = [
            message("assistant", "What should I call you?"),
            message("user", "call me Vandy"),
        ]
        self.assertEqual(consent_gate(history, GOAL_QUESTION), VANDY_DISCLOSURE)

    def test_the_notice_and_question_one_go_out_as_one_message(self) -> None:
        """SCOPING.md §3.4: one send, so nothing in it can be half-delivered."""
        # The constant stays the notice alone; the rest is joined at send
        # time so the privacy text has exactly one definition.
        self.assertNotIn("1/5", DISCLOSURE_MESSAGE)
        self.assertNotIn(GOAL_QUESTION, DISCLOSURE_MESSAGE)
        delivered = gates._personalized_disclosure("Vandy")
        self.assertIn(DISCLOSURE_MESSAGE, delivered)
        self.assertTrue(delivered.endswith(gates._setup_question(0)))
        # The notice comes first and carries no name. A mis-parsed name used
        # to land inside it — "hey Can I send you voice notes 🙂" is a real one.
        self.assertTrue(delivered.startswith(DISCLOSURE_MESSAGE))
        self.assertNotIn("Vandy", DISCLOSURE_MESSAGE)
        # The open goal question moved to the far side of the number.
        self.assertNotIn(GOAL_QUESTION, delivered)
        # No background sender left to stall.
        self.assertFalse(hasattr(gates, "_schedule_goal_question"))
        self.assertFalse(hasattr(gates, "_send_goal_question"))

    def test_calorie_gate_does_not_skip_name_or_disclosure(self) -> None:
        # A first message is a first message whatever it says. "Track
        # calories" gets the opener back, which is still the name question.
        first_turn = [message("user", "Track calories")]
        self.assertEqual(
            transform_response(
                history=first_turn,
                user_message="Track calories",
                response_text="What should I call you?",
            ),
            OPENING_MESSAGE,
        )

        named = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]
        self.assertEqual(
            transform_response(
                history=named,
                user_message="Vandy",
                response_text="What is your goal?",
            ),
            VANDY_DISCLOSURE,
        )

    def test_new_chat_cannot_return_calories_before_the_name(self) -> None:
        history = [message("user", "Track calories")]
        self.assertEqual(
            transform_response(
                history=history,
                user_message="Track calories",
                response_text="One ragi roti is about 120 calories.",
            ),
            OPENING_MESSAGE,
        )

    def test_new_chat_cannot_advance_to_another_question_before_the_name(self) -> None:
        history = [message("user", "Hi")]
        self.assertEqual(
            transform_response(
                history=history,
                user_message="Hi",
                response_text="What health goal are you working on?",
            ),
            OPENING_MESSAGE,
        )

    def test_removes_unproven_save_claim_but_keeps_the_real_question(self) -> None:
        """The claim goes. The question survives, in Ted's own lowercase.

        This used to assert a capital L. The gate was upper-casing whatever it
        left behind, which is how a warm lowercase sentence reached a real user
        on 3 Sep as "Logged this." Removing a claim is the gate's job; deciding
        how Ted sounds is not.
        """
        self.assertEqual(
            action_claim_gate(
                "Good to know, 33 noted. But losing, maintaining, or building—which one?",
                action_succeeded=False,
            ),
            "losing, maintaining, or building—which one?",
        )

    def test_allows_action_claim_after_a_successful_tool(self) -> None:
        self.assertIsNone(
            action_claim_gate("Your reminder is scheduled.", action_succeeded=True)
        )

    def test_does_not_treat_an_ordinary_set_as_an_action_claim(self) -> None:
        self.assertIsNone(
            action_claim_gate("Here is a set of three exercises.")
        )

    def test_unrelated_tool_success_does_not_unlock_a_save_claim(self) -> None:
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        _capture_turn(
            platform="whatsapp",
            session_id="wrong-tool",
            conversation_history=history,
            user_message="Remember that my target is 9000.",
        )
        _record_tool_success(
            session_id="wrong-tool",
            status="ok",
            tool_name="cronjob",
            args={"action": "list"},
            result='{"success": true, "count": 0}',
        )
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id="wrong-tool",
                response_text="Your target is saved.",
            ),
            gates.CLAIM_NOT_DONE,
        )

    def test_staged_memory_write_does_not_unlock_a_save_claim(self) -> None:
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        _capture_turn(
            platform="whatsapp",
            session_id="staged-memory",
            conversation_history=history,
            user_message="Remember that my target is 9000.",
        )
        _record_tool_success(
            session_id="staged-memory",
            status="ok",
            tool_name="memory",
            args={"action": "add"},
            result='{"success": true, "staged": true}',
        )
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id="staged-memory",
                response_text="Your target is saved.",
            ),
            gates.CLAIM_NOT_DONE,
        )

    def test_real_memory_write_unlocks_only_memory_claim(self) -> None:
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        _capture_turn(
            platform="whatsapp",
            session_id="real-memory",
            conversation_history=history,
            user_message="Remember that my target is 9000.",
        )
        _record_tool_success(
            session_id="real-memory",
            status="ok",
            tool_name="memory",
            args={"action": "add"},
            result='{"success": true, "message": "Entry added."}',
        )
        self.assertIsNone(
            _transform_live_response(
                platform="whatsapp",
                session_id="real-memory",
                response_text="Your target is saved.",
            )
        )
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id="real-memory",
                response_text="Your reminder is scheduled.",
            ),
            gates.CLAIM_NOT_DONE,
        )

    def test_disclosure_is_not_repeated_when_transformed_text_is_missing_from_history(self) -> None:
        session_id = "disclosure-state-test"
        sender_id = "disclosure-state-test@s.whatsapp.net"
        user_key = gates._user_state_key("whatsapp", sender_id, session_id)
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        named_history = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id=sender_id,
            conversation_history=named_history,
            user_message="Vandy",
        )
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id=session_id,
                response_text="What do you want to change?",
            ),
            VANDY_DISCLOSURE,
        )

        with patch.object(gates, "_persist_disclosure_state"):
            _log_disclosure(
                platform="whatsapp",
                session_id=session_id,
                assistant_response=VANDY_DISCLOSURE,
            )
            _log_disclosure(
                platform="whatsapp",
                session_id=session_id,
                assistant_response=VANDY_DISCLOSURE,
            )

        history_without_transformed_reply = named_history + [
            message("assistant", "What do you want to change?"),
            message("user", "Routine"),
        ]
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id=sender_id,
            conversation_history=history_without_transformed_reply,
            user_message="Routine",
        )
        reply = _transform_live_response(
            platform="whatsapp",
            session_id=session_id,
            response_text="routine is broad—what should look different?",
        )
        # The point of this test: the disclosure does not go out twice.
        self.assertNotIn(DISCLOSURE_MESSAGE, reply or "")
        # It is not left alone either. The five are running, so the
        # outstanding one comes back rather than the model's own question.
        self.assertEqual(reply, gates._setup_question(0))
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_disclosure_flag_follows_the_user_across_sessions(self) -> None:
        sender_id = "same-user@s.whatsapp.net"
        first_session = "first-session"
        second_session = "second-session"
        user_key = gates._user_state_key("whatsapp", sender_id, first_session)
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        named_history = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]

        with patch.object(gates, "_persist_disclosure_state"):
            _capture_turn(
                platform="whatsapp",
                session_id=first_session,
                sender_id=sender_id,
                conversation_history=named_history,
                user_message="Vandy",
            )
            self.assertEqual(
                _transform_live_response(
                    platform="whatsapp",
                    session_id=first_session,
                    response_text=GOAL_QUESTION,
                ),
                VANDY_DISCLOSURE,
            )
            _log_disclosure(
                platform="whatsapp",
                session_id=first_session,
                assistant_response=VANDY_DISCLOSURE,
            )

            _capture_turn(
                platform="whatsapp",
                session_id=second_session,
                sender_id=sender_id,
                conversation_history=[],
                user_message="Routine",
            )
            reply = _transform_live_response(
                platform="whatsapp",
                session_id=second_session,
                response_text="routine is broad—what should look different?",
            )
            # A new session, and the disclosure still does not repeat: the
            # durable record follows the user, not the transcript.
            self.assertNotIn(DISCLOSURE_MESSAGE, reply or "")
            self.assertEqual(reply, gates._setup_question(0))
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_replays_the_four_message_onboarding_loop_once(self) -> None:
        session_id = "four-message-replay"
        sender_id = "four-message-replay@s.whatsapp.net"
        user_key = gates._user_state_key("whatsapp", sender_id, session_id)
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        history = [message("assistant", "What should I call you?")]
        model_replies = (
            GOAL_QUESTION,
            "routine is broad—what should look different day to day?",
            "what’s one small routine you want to make consistent first?",
            "chalo, what’s one small routine you want to make consistent first?",
        )
        visible_replies: list[str] = []

        with patch.object(gates, "_persist_disclosure_state"):
            for user_text, model_reply in zip(
                ("Vandy", "Routine", "routine", "okay understood"),
                model_replies,
            ):
                history.append(message("user", user_text))
                _capture_turn(
                    platform="whatsapp",
                    session_id=session_id,
                    sender_id=sender_id,
                    conversation_history=history,
                    user_message=user_text,
                )
                transformed = _transform_live_response(
                    platform="whatsapp",
                    session_id=session_id,
                    response_text=model_reply,
                )
                visible_reply = transformed or model_reply
                visible_replies.append(visible_reply)
                _log_disclosure(
                    platform="whatsapp",
                    session_id=session_id,
                    assistant_response=visible_reply,
                )
                # Hermes stores the model's original reply internally even
                # when the delivery gate replaces what WhatsApp receives.
                history.append(message("assistant", model_reply))

        self.assertEqual(visible_replies.count(VANDY_DISCLOSURE), 1)
        # None of "Routine", "routine" or "okay understood" is an age, so the
        # question comes back — but a bounded number of times. Three asks, the
        # first of them riding inside the disclosure, and then Ted stops. This
        # is the same loop that pestered J for a name, and it is bounded the
        # same way.
        self.assertEqual(
            sum(gates._setup_question(0) in reply for reply in visible_replies),
            gates._MAX_SETUP_ASKS,
        )
        self.assertEqual(
            visible_replies,
            [
                VANDY_DISCLOSURE,
                gates._setup_question(0),
                gates._setup_question(0),
                # Given up on, so the model's own reply goes out untouched.
                model_replies[3],
            ],
        )
        self.assertEqual(gates._setup_state(user_key), "stalled")
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_disclosure_state_recovers_existing_sends_from_agent_log(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            log_path = root / "agent.log"
            state_path.write_text(
                '{"session_ids": ["saved-session"]}', encoding="utf-8"
            )
            log_path.write_text(
                "INFO consent_disclosure_sent session=logged-session privacy_url=x\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _load_disclosure_state(state_path, log_path),
                {"saved-session", "logged-session"},
            )

    def test_hashed_user_flag_survives_a_restart_reload(self) -> None:
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            missing_log = Path(directory) / "missing.log"
            user_key = gates._user_state_key(
                "whatsapp", "restart-user@s.whatsapp.net", "old-session"
            )
            gates._DISCLOSURE_SENT_KEYS.add(user_key)
            try:
                with patch.object(gates, "_DISCLOSURE_STATE_PATH", state_path):
                    gates._persist_disclosure_state()
                self.assertIn(
                    user_key,
                    _load_disclosure_state(state_path, missing_log),
                )
            finally:
                gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_convex_memory_is_loaded_only_for_the_current_sender(self) -> None:
        seen_user_keys: list[str] = []

        def fake_request(action: str, user_key: str, facts=None):
            self.assertEqual(action, "get")
            self.assertIsNone(facts)
            seen_user_keys.append(user_key)
            return {
                "success": True,
                "facts": [{"key": "owner", "value": user_key[-8:]}],
            }

        with patch.object(gates, "_convex_request", side_effect=fake_request):
            first = _capture_turn(
                platform="whatsapp",
                session_id="sender-a-session",
                sender_id="sender-a@s.whatsapp.net",
                conversation_history=[],
                user_message="hello",
            )
            second = _capture_turn(
                platform="whatsapp",
                session_id="sender-b-session",
                sender_id="sender-b@s.whatsapp.net",
                conversation_history=[],
                user_message="hello",
            )

        self.assertEqual(len(seen_user_keys), 2)
        self.assertNotEqual(seen_user_keys[0], seen_user_keys[1])
        self.assertNotIn("sender-a", seen_user_keys[0])
        self.assertIn(seen_user_keys[0][-8:], (first or {}).get("context", ""))
        self.assertNotIn(seen_user_keys[0][-8:], (second or {}).get("context", ""))

    def test_convex_memory_save_is_bound_to_the_active_sender(self) -> None:
        session_id = "bound-save-session"
        sender_id = "bound-save@s.whatsapp.net"
        expected_user_key = gates._user_state_key("whatsapp", sender_id, session_id)
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id=sender_id,
            conversation_history=[],
            user_message="call me Vandy",
        )

        with patch.object(
            gates,
            "_convex_request",
            return_value={"success": True, "saved": 1},
        ) as request:
            result = gates._save_user_facts(
                {"facts": [{"key": "name", "value": "Vandy"}]},
                session_id=session_id,
            )

        self.assertEqual(result, '{"success": true, "saved": 1}')
        request.assert_called_once_with(
            "save",
            expected_user_key,
            facts=[{"key": "name", "value": "Vandy"}],
            body=None,
        )

    def test_successful_convex_memory_save_unlocks_a_save_claim(self) -> None:
        session_id = "convex-memory-success"
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="convex-memory-success@s.whatsapp.net",
            conversation_history=history,
            user_message="My target is 9000 steps.",
        )
        _record_tool_success(
            session_id=session_id,
            status="ok",
            tool_name="ted_memory_save",
            args={"facts": [{"key": "steps", "value": "9000"}]},
            result='{"success": true, "saved": 1}',
        )
        self.assertIsNone(
            _transform_live_response(
                platform="whatsapp",
                session_id=session_id,
                response_text="Your step target is saved.",
            )
        )


class InjectedMemoryContextTest(unittest.TestCase):
    """Hermes appends the Convex memory block to the user's own message."""

    @staticmethod
    def with_memory(user_text: str, *facts: str) -> str:
        """Build a user turn the way Hermes delivers it, block appended."""
        block = gates._format_user_memory(
            {
                "success": True,
                "facts": [
                    {"key": key, "value": value}
                    for key, value in (fact.split(": ", 1) for fact in facts)
                ],
            }
        )
        return f"{user_text}\n\n{block}"

    def test_a_saved_goal_is_not_read_as_a_body_measurement(self) -> None:
        turn = self.with_memory("Hi", "goal: lose 5 kg")
        texts = gates._user_turns([message("user", turn)])

        self.assertEqual(texts, ["Hi"])
        self.assertIsNone(gates._find_weight_kg(texts))
        self.assertIsNone(gates._find_age(texts))

    def test_a_saved_calorie_target_does_not_open_the_calorie_flow(self) -> None:
        turn = self.with_memory("drank 2 litres water", "calorie target: 1800")

        self.assertFalse(
            gates._calorie_flow_active(
                [message("user", turn)], "drank 2 litres water"
            )
        )

    def test_the_name_survives_the_appended_block(self) -> None:
        history = [
            message("assistant", "first things first — what should i call you?"),
            message("user", self.with_memory("Vandy", "name: Vandy")),
        ]

        self.assertEqual(gates._given_name(history), "Vandy")

    def test_the_block_still_starts_with_the_shared_marker(self) -> None:
        block = gates._format_user_memory(
            {"success": True, "facts": [{"key": "name", "value": "Vandy"}]}
        )

        self.assertTrue(block.startswith(gates._MEMORY_CONTEXT_MARKER))
        self.assertIn("- name: Vandy", block)
        self.assertEqual(gates._strip_memory_context(block), "")


# The exact assistant turn from the 2 Sep WhatsApp thread that looped.
LIVE_NAME_ASK = (
    "first things first though — what should i actually call you day to day, "
    "and what's the one goal we're chasing here?"
)


class OnboardingStateTest(unittest.TestCase):
    """Onboarding state is recorded, never re-derived from model prose."""

    def setUp(self) -> None:
        state = patch.object(gates, "_ONBOARDING_STATE", {})
        persist = patch.object(gates, "_persist_onboarding_state")
        state.start()
        persist.start()
        self.addCleanup(state.stop)
        self.addCleanup(persist.stop)

    def test_the_live_wording_is_recognised_as_the_name_question(self) -> None:
        self.assertTrue(gates._asks_for_name(LIVE_NAME_ASK))

    def test_a_promise_to_message_later_is_not_the_name_question(self) -> None:
        self.assertFalse(gates._asks_for_name("cool, i'll call you at 8pm."))
        self.assertFalse(gates._asks_for_name("i'll call you once it's done."))

    def test_the_live_thread_no_longer_loops(self) -> None:
        user_key = "whatsapp:sha256:live"

        # Turn 1: the model asks in its own words. The gate lets Ted's voice
        # through and records that the question went out.
        self.assertIsNone(consent_gate([], LIVE_NAME_ASK, user_key))
        self.assertEqual(gates._name_asks(user_key), 1)

        # Turn 2: she answers. Hermes stores the model's original reply.
        gates._capture_name_answer(user_key, "Vandy")
        history = [
            message("assistant", LIVE_NAME_ASK),
            message("user", "Vandy"),
        ]
        self.assertEqual(
            consent_gate(history, GOAL_QUESTION, user_key), VANDY_DISCLOSURE
        )

    def test_an_unrecognised_question_still_cannot_loop_forever(self) -> None:
        """The bound holds even when phrase matching fails completely."""
        user_key = "whatsapp:sha256:loop"
        unmatched = "so, who am i talking to today"

        replies = [consent_gate([], unmatched, user_key) for _ in range(5)]

        self.assertEqual(replies[:3], ["What should I call you?"] * 3)
        # The name question stops. What follows is the disclosure, not another
        # ask and not silence: this used to be [None, None], and that silence
        # is why a user who never gives a name has no consent record while
        # their meals go on being logged.
        for reply in replies[3:]:
            self.assertNotEqual(reply, "What should I call you?")
            self.assertIn(gates.PRIVACY_URL, reply or "")

    def test_giving_up_on_the_name_still_discloses(self) -> None:
        """Someone who never answers is still owed the notice and the wipe route."""
        user_key = "whatsapp:sha256:noname"
        for _ in range(gates._MAX_NAME_ASKS):
            consent_gate([], "who am i talking to", user_key)

        disclosure = consent_gate([], "anyway, what did you eat?", user_key)

        self.assertIsNotNone(disclosure)
        self.assertIn(gates.PRIVACY_URL, disclosure)
        self.assertIn("delete my data", disclosure)
        # Addressed to nobody in particular, because nobody said who they are.
        self.assertFalse(disclosure.startswith("hey "))
        self.assertIsNone(gates._known_name(user_key))

    def test_once_delivered_the_disclosure_is_not_repeated(self) -> None:
        """_log_disclosure records the send, and that is what stops the repeat."""
        user_key = "whatsapp:sha256:noname2"
        for _ in range(gates._MAX_NAME_ASKS):
            consent_gate([], "who am i talking to", user_key)
        sent = consent_gate([], "anyway, what did you eat?", user_key)
        self.assertIsNotNone(sent)

        gates._mark_disclosure_sent(user_key)

        self.assertIsNone(consent_gate([], "and a 20 min run", user_key))

    def test_a_name_in_convex_memory_means_the_gate_never_asks(self) -> None:
        user_key = "whatsapp:sha256:convex"
        gates._remember_name_from_facts(
            user_key,
            {"success": True, "facts": [{"key": "name", "value": "Vandy"}]},
        )

        self.assertEqual(
            consent_gate([], GOAL_QUESTION, user_key), VANDY_DISCLOSURE
        )
        self.assertEqual(gates._name_asks(user_key), 0)

    def test_the_opening_message_counts_as_asking_for_the_name(self) -> None:
        user_key = "whatsapp:sha256:opening"

        self.assertEqual(
            transform_response(
                history=[message("user", "Okay Ted, let's do this!")],
                user_message="Okay Ted, let's do this!",
                response_text="A different model-generated opener.",
                user_key=user_key,
            ),
            OPENING_MESSAGE,
        )
        self.assertEqual(gates._name_asks(user_key), 1)

        gates._capture_name_answer(user_key, "call me Vandy")
        self.assertEqual(gates._known_name(user_key), "Vandy")

    def test_the_name_is_not_taken_before_the_question_is_asked(self) -> None:
        user_key = "whatsapp:sha256:early"
        gates._capture_name_answer(user_key, "Okay Ted, let's do this!")

        self.assertIsNone(gates._known_name(user_key))


class ClaimGateTest(unittest.TestCase):
    """Ted's own claims are gated; descriptions of the user's day are not."""

    # Real replies from milestones 8, 9 and 13, which the old gate destroyed.
    TOTALS = (
        "1,180 calories so far, 3 meals logged, 4,200 steps. "
        "a 20 min walk closes the step gap."
    )
    CORRECTION = "ah, paneer. updated: roughly 380 calories, 19g protein."
    REVIEW = (
        "3 meals logged, water done, walk done. tomorrow: protein at breakfast."
    )

    def test_todays_totals_survive_intact(self) -> None:
        self.assertIsNone(action_claim_gate(self.TOTALS))

    def test_a_correction_keeps_its_recalculated_numbers(self) -> None:
        self.assertIsNone(action_claim_gate(self.CORRECTION))

    def test_the_evening_review_keeps_its_counts(self) -> None:
        self.assertIsNone(action_claim_gate(self.REVIEW))

    def test_other_descriptions_of_the_users_day_survive(self) -> None:
        for reply in (
            "4 glasses recorded so far, 2 to go.",
            "your target was updated last week, so this is measured against it.",
            "2 workouts logged this week — same as last week.",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(action_claim_gate(reply))

    def test_an_unbacked_save_claim_is_still_removed(self) -> None:
        self.assertEqual(
            action_claim_gate("I've saved that to your log."),
            gates.CLAIM_NOT_DONE,
        )

    def test_the_check_in_claim_no_longer_slips_through(self) -> None:
        """The false claim the cron gate was built to catch, and missed."""
        self.assertEqual(
            action_claim_gate("chalo, 8pm check-in is set."),
            gates.CLAIM_NOT_DONE,
        )

    def test_other_scheduling_promises_are_caught(self) -> None:
        for reply in (
            "I'll remind you at 8pm.",
            "I'll ping you tomorrow morning.",
            "that's on for tomorrow morning.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), gates.CLAIM_NOT_DONE
                )

    def test_real_scheduling_replies_from_the_2_sep_thread(self) -> None:
        """Both slipped the gate live; both are true, so both need a tool."""
        for reply in (
            "all 5 pings are set — coq10 8:45am, omega3+b12 10:30am 💊",
            "done, one-off ping at 5pm today for the vitamin 👍",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), gates.CLAIM_NOT_DONE
                )
                self.assertIsNone(
                    action_claim_gate(reply, successful_actions={"cron"})
                )

    def test_a_proven_action_lets_the_claim_through(self) -> None:
        self.assertIsNone(
            action_claim_gate(
                "I've saved that to your log.", successful_actions={"memory"}
            )
        )
        self.assertIsNone(
            action_claim_gate(
                "chalo, 8pm check-in is set.", successful_actions={"cron"}
            )
        )

    def test_a_claim_is_stripped_but_the_reading_survives(self) -> None:
        self.assertEqual(
            action_claim_gate(
                "I've saved that. 3 meals logged, 4,200 steps."
            ),
            "3 meals logged, 4,200 steps.",
        )


class OnboardingCloseTest(unittest.TestCase):
    """Onboarding may not sign off while the evening check-in time is missing."""

    def setUp(self) -> None:
        state = patch.object(gates, "_ONBOARDING_STATE", {})
        persist = patch.object(gates, "_persist_onboarding_state")
        state.start()
        persist.start()
        self.addCleanup(state.stop)
        self.addCleanup(persist.stop)

    def test_all_set_is_refused_while_the_review_time_is_missing(self) -> None:
        """The tester on 2 Sep dodged the time four times and was told All set."""
        gates._update_onboarding("u", done=["name", "goal"])
        for closer in (
            "all set! send me your first meal whenever.",
            "you're all set 🙌",
            "we're done — talk tonight.",
            "you're good to go.",
            "setup complete.",
        ):
            with self.subTest(closer=closer):
                self.assertEqual(
                    gates.onboarding_close_gate(closer, "u"),
                    gates.REVIEW_TIME_QUESTION,
                )

    def test_it_closes_once_the_time_is_actually_recorded(self) -> None:
        """The blocking question is gone. The weekly offer rides along once."""
        gates._update_onboarding("u", done=["name", "goal", "dailyReview"])
        closing = gates.onboarding_close_gate("all set!", "u")
        self.assertIsNotNone(closing)
        self.assertNotEqual(closing, gates.REVIEW_TIME_QUESTION)
        self.assertTrue(closing.startswith("all set!"))
        self.assertIn(gates.WEEKLY_REVIEW_OFFER, closing)

    def test_the_weekly_offer_is_made_exactly_once(self) -> None:
        gates._update_onboarding("u", done=["name", "goal", "dailyReview"])
        self.assertIn(
            gates.WEEKLY_REVIEW_OFFER, gates.onboarding_close_gate("all set!", "u")
        )
        # Second sign-off: they have already been asked, so it truly closes.
        self.assertIsNone(gates.onboarding_close_gate("you're all set", "u"))

    def test_a_recorded_weekly_answer_suppresses_the_offer(self) -> None:
        """Said yes or said no, either way the question is spent."""
        gates._update_onboarding(
            "u", done=["name", "goal", "dailyReview", "weeklyReview"]
        )
        self.assertIsNone(gates.onboarding_close_gate("all set!", "u"))

    def test_ordinary_replies_are_never_touched(self) -> None:
        gates._update_onboarding("u", done=["name"])
        for reply in (
            "nice, 39g protein in that one.",
            "arre, gym got ghosted today?",
            "you're at 1800ml, one more glass.",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(gates.onboarding_close_gate(reply, "u"))

    def test_a_user_with_no_record_is_left_alone(self) -> None:
        """Anyone who onboarded before this gate must not be nagged."""
        self.assertIsNone(gates.onboarding_close_gate("all set!", "someone-old"))

    def test_the_question_asks_once_and_names_a_shape(self) -> None:
        question = gates.REVIEW_TIME_QUESTION
        self.assertEqual(question.count("?"), 1)
        self.assertEqual(question, question.lower())
        self.assertIn("9pm", question)


class DeleteMyDataTest(unittest.TestCase):
    """A deletion confirmation must be backed by a real deletion."""

    def setUp(self) -> None:
        state = patch.object(gates, "_ONBOARDING_STATE", {})
        persist = patch.object(gates, "_persist_onboarding_state")
        state.start()
        persist.start()
        self.addCleanup(state.stop)
        self.addCleanup(persist.stop)

    def test_the_confirmation_that_slipped_through_is_now_caught(self) -> None:
        self.assertEqual(
            action_claim_gate("done, your profile, logs and uploads are deleted."),
            gates.CLAIM_NOT_DONE,
        )

    def test_other_ways_of_confirming_a_deletion_are_caught(self) -> None:
        for reply in (
            "all cleared, fresh start whenever you want.",
            "that's wiped — nothing left on my side.",
            "your data's gone.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), gates.CLAIM_NOT_DONE
                )

    def test_ordinary_health_talk_is_not_a_deletion_claim(self) -> None:
        for reply in (
            "the bloating is gone, that's a good sign.",
            "your energy dip is gone once protein is up.",
            "that craving is gone in 20 minutes, promise.",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(action_claim_gate(reply))

    def test_a_real_deletion_lets_the_confirmation_through(self) -> None:
        self.assertIsNone(
            action_claim_gate(
                "done, your profile, logs and uploads are deleted.",
                successful_actions={"delete"},
            )
        )

    def test_the_tool_refuses_without_explicit_confirmation(self) -> None:
        session_id = "delete-unconfirmed"
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="delete-test@s.whatsapp.net",
            conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="delete my data",
        )
        result = json.loads(
            gates._delete_user_data({"confirmed": False}, session_id=session_id)
        )

        self.assertFalse(result["success"])
        self.assertIn("confirm", result["error"].lower())

    def test_a_typo_no_longer_wipes_a_users_history(self) -> None:
        """On 2 Sep 2026 "Ges" deleted a tester's data. It must not again."""
        for reply in ("Ges", "yess", "ys", "gez", "yesss", "ye s"):
            with self.subTest(reply=reply):
                session_id = f"delete-typo-{reply}"
                _capture_turn(
                    platform="whatsapp",
                    session_id=session_id,
                    sender_id="typo@s.whatsapp.net",
                    conversation_history=[
                        message("user", "delete my data"),
                        message("assistant", "this wipes everything, no undo. delete?"),
                    ],
                    user_message=reply,
                )
                result = json.loads(
                    gates._delete_user_data({"confirmed": True}, session_id=session_id)
                )
                self.assertFalse(result["success"])
                self.assertIn("nothing has been deleted", result["error"].lower())

    def test_the_request_cannot_double_as_its_own_confirmation(self) -> None:
        """Otherwise "delete my data" wipes on the first message, unasked."""
        session_id = "delete-self-confirm"
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="self@s.whatsapp.net",
            conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="delete my data",
        )
        result = json.loads(
            gates._delete_user_data({"confirmed": True}, session_id=session_id)
        )

        self.assertFalse(result["success"])

    def test_a_yes_that_ted_never_asked_for_is_refused(self) -> None:
        session_id = "delete-unasked"
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="unasked@s.whatsapp.net",
            conversation_history=[message("assistant", "nice, 39g protein in that.")],
            user_message="yes",
        )
        result = json.loads(
            gates._delete_user_data({"confirmed": True}, session_id=session_id)
        )

        self.assertFalse(result["success"])

    def test_a_real_confirmation_still_goes_through(self) -> None:
        for reply in ("yes", "Yes!", "confirm", "delete it", "haan", "y"):
            with self.subTest(reply=reply):
                self.assertTrue(gates._is_delete_confirmation(reply))

    def test_the_refusal_never_tells_the_user_their_data_is_gone(self) -> None:
        """A refusal the model paraphrases as success is worse than no gate."""
        session_id = "delete-wording"
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="wording@s.whatsapp.net",
            conversation_history=[
                message("assistant", "this wipes everything, no undo. delete?"),
            ],
            user_message="Ges",
        )
        error = json.loads(
            gates._delete_user_data({"confirmed": True}, session_id=session_id)
        )["error"].lower()

        self.assertIn("do not tell them anything is gone", error)

    def test_the_tool_refuses_when_no_user_is_active(self) -> None:
        result = json.loads(
            gates._delete_user_data({"confirmed": True}, session_id="no-such-session")
        )

        self.assertFalse(result["success"])

    def test_deletion_also_clears_the_gates_own_state(self) -> None:
        """Otherwise Ted still greets a deleted user by name."""
        user_key = "whatsapp:sha256:erase"
        gates._remember_name(user_key, "Vandy")
        gates._record_name_ask(user_key)

        with patch.object(gates, "_persist_disclosure_state"):
            gates._DISCLOSURE_SENT_KEYS.add(user_key)
            gates._forget_user(user_key)
            self.assertNotIn(user_key, gates._DISCLOSURE_SENT_KEYS)

        self.assertIsNone(gates._known_name(user_key))
        self.assertEqual(gates._name_asks(user_key), 0)

    def test_a_successful_delete_tool_proves_the_claim(self) -> None:
        session_id = "delete-proven"
        _capture_turn(
            platform="whatsapp",
            session_id=session_id,
            sender_id="delete-proven@s.whatsapp.net",
            conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="yes",
        )
        _record_tool_success(
            session_id=session_id,
            status="ok",
            tool_name="ted_memory_delete",
            args={"confirmed": True},
            result='{"success": true, "deleted": true}',
        )
        with gates._TURN_LOCK:
            proven = set(gates._TURN_CONTEXT[session_id]["successful_actions"])

        self.assertIn("delete", proven)



class CalorieProfileParsingTest(unittest.TestCase):
    """Order 05: the parsers that used to read quantities as body measurements."""

    def test_quantities_are_never_read_as_an_age(self) -> None:
        for text in (
            "i'm having 2 rotis and dal",
            "i am 5'4\"",
            "i'm 5 kg over my target",
            "i am 3 meals down today",
            "i drank 2 litres of water",
        ):
            with self.subTest(text=text):
                self.assertIsNone(gates._find_age([text]))

    def test_a_real_age_is_still_read(self) -> None:
        for text, expected in (
            ("i am 33", 33),
            ("im 28 years old", 28),
            ("i'm 41 yrs", 41),
            ("age 36", 36),
            ("i am 17 and want to track calories", 17),
        ):
            with self.subTest(text=text):
                self.assertEqual(gates._find_age([text]), expected)


    def test_a_word_inside_a_word_never_counts_as_the_question(self) -> None:
        """"age" is inside "message", and the disclosure says "messages".

        Every conversation opens with DISCLOSURE_MESSAGE, so on a substring
        match Ted had asked for the user's age before they had said anything.
        Any number between 10 and 99 in their first reply then became their
        age, and `_remember_age` writes the minor flag, which is sticky and
        clears only on "delete my data". One ordinary sentence bought a
        permanent silent refusal of every calorie number.
        """
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        for text in (
            "remind me about green tea in 10 minutes",
            "i walked 20 floors today",
            "log 30 min of yoga",
        ):
            with self.subTest(text=text):
                self.assertIsNone(gates.extract_calorie_profile(history, text).age)

    def test_the_same_trap_in_the_words_a_coach_actually_uses(self) -> None:
        for asked in ("what's your average step count?", "want me to manage that?"):
            with self.subTest(asked=asked):
                self.assertIsNone(
                    gates.extract_calorie_profile(
                        [message("assistant", asked)], "about 40 on a good day"
                    ).age
                )

    def test_the_real_age_question_still_gets_its_answer(self) -> None:
        for asked in (gates.AGE_QUESTION, "quick one, what's your age?", "how old are you?"):
            with self.subTest(asked=asked):
                self.assertEqual(
                    gates.extract_calorie_profile(
                        [message("assistant", asked)], "33"
                    ).age,
                    33,
                )

    def test_a_bare_number_answers_the_height_question(self) -> None:
        history = [
            message("user", "i am 33 and want a calorie target"),
            message("assistant", "how tall are you?"),
        ]
        profile = gates.extract_calorie_profile(history, "170")
        self.assertEqual(profile.height_cm, 170.0)

    def test_a_bare_number_answers_the_weight_question(self) -> None:
        history = [
            message("user", "i am 33, 170 cm, chasing a calorie target"),
            message("assistant", "and your weight?"),
        ]
        profile = gates.extract_calorie_profile(history, "62")
        self.assertEqual(profile.weight_kg, 62.0)

    def test_an_out_of_range_bare_number_is_not_a_measurement(self) -> None:
        history = [message("assistant", "how tall are you?")]
        self.assertIsNone(gates.extract_calorie_profile(history, "12").height_cm)

    def test_inches_are_kept_when_the_unit_is_left_off(self) -> None:
        """"5 foot 4" is how people say it out loud, and it is not 5 foot 0."""
        for said in ("i'm 5 foot 4", "i'm 5 feet 4", "i'm 5'4\"", "i'm 5 ft 4 in"):
            with self.subTest(said=said):
                self.assertEqual(gates._find_height_cm([said]), 162.56)

    def test_a_half_inch_survives_the_words_around_it(self) -> None:
        """Pallavi's own words, 4 Sep 2026. This read as 152.4 cm."""
        said = "I am 5 feet 4 and a half inches tall and my weight is 63.5 right now"
        self.assertEqual(gates._find_height_cm([said]), 163.83)

    def test_feet_alone_does_not_swallow_the_next_number(self) -> None:
        """The inches slot must not eat a weight standing beside it."""
        self.assertEqual(gates._find_height_cm(["i'm 5 feet, 63.5 kg"]), 152.4)
        self.assertEqual(gates._find_height_cm(["i'm 5 feet 63 kg"]), 152.4)

    def test_eleven_inches_still_parses(self) -> None:
        self.assertEqual(gates._find_height_cm(["i'm 5 ft 11"]), 180.34)

    def test_a_unit_jammed_onto_the_number_keeps_the_decimal(self) -> None:
        """"63.5kgs" used to come back as 63, losing half a kilo in silence."""
        self.assertEqual(gates._find_weight_kg(["63.5kgs"]), 63.5)
        self.assertEqual(gates._find_weight_kg(["i weigh 63.5 kilos"]), 63.5)
        history = [message("assistant", "and your weight?")]
        self.assertEqual(
            gates.extract_calorie_profile(history, "63.5kgs").weight_kg, 63.5
        )

    def test_a_four_digit_number_is_still_not_a_measurement(self) -> None:
        history = [message("assistant", "how tall are you?")]
        self.assertIsNone(gates.extract_calorie_profile(history, "1234").height_cm)

    def test_the_maintenance_figure_uses_the_height_she_actually_gave(self) -> None:
        """A height in feet must reach the formula intact.

        The 4 Sep 2026 thread is the case: 5 feet 4 and a half inches was read
        as 152.4 cm, and the sentence promising it used only her numbers gave
        her 1,520 instead of 1,610.
        """
        history = [
            message(
                "user",
                "i am 31, female, 5 feet 4 and a half inches, 63.5 kg, sedentary",
            ),
        ]
        profile = gates.extract_calorie_profile(history, "")
        self.assertEqual(profile.height_cm, 163.83)
        self.assertEqual(profile.weight_kg, 63.5)
        reply = calorie_gate(history, "what should my calorie target be?", "sure.")
        self.assertIn("1,610", reply or "")
        self.assertNotIn("1,520", reply or "")
        self.assertNotIn("deficit", reply or "")

    def test_a_stated_weight_still_needs_a_question_to_anchor_it(self) -> None:
        """Known gap, recorded so it is not mistaken for working.

        "my weight is 63.5" carries no unit, so it is only read as an answer to
        a weight question Ted just asked. State it in passing and it is lost.
        Widening this is not free: a goal weight ("i want to get to 59") sits in
        the same sentences and must never be read as the current one.
        """
        said = "i am 5 feet 4 and a half inches tall and my weight is 63.5 right now"
        self.assertIsNone(gates._find_weight_kg([said]))
        anchored = [message("assistant", "and your height and weight?")]
        self.assertEqual(
            gates.extract_calorie_profile(anchored, said).weight_kg, 63.5
        )

    def test_a_loosely_worded_answer_gives_sex_and_activity(self) -> None:
        profile = gates.extract_calorie_profile(
            [
                message("user", "i am 33, 170 cm, 62 kg, want a calorie target"),
                message("assistant", "how active is a normal day?"),
            ],
            "I am a woman, mostly at a desk",
        )
        self.assertEqual(profile.sex, "female")
        self.assertEqual(profile.activity, "sedentary")


class CalorieGateReachTest(unittest.TestCase):
    """Order 05: the 18+ check belongs to the target flow, not every mention."""

    def test_a_per_food_question_does_not_demand_an_age(self) -> None:
        history = [message("user", "how many calories in a roti?")]
        self.assertIsNone(
            calorie_gate(history, "how many calories in a roti?", "about 120 calories.")
        )

    def test_a_later_unrelated_turn_is_not_still_gated(self) -> None:
        history = [
            message("user", "how many calories in a roti?"),
            message("assistant", "about 120 calories."),
            message("user", "that was lunch"),
            message("assistant", "noted."),
        ]
        self.assertIsNone(
            calorie_gate(history, "drank 2 litres water", "nice, 2 down.")
        )

    def test_a_minor_is_still_refused_on_a_per_food_estimate(self) -> None:
        history = [message("user", "i am 15 years old")]
        self.assertEqual(
            calorie_gate(
                history, "how many calories in a roti?", "about 120 calories."
            ),
            gates.UNDER_18_REFUSAL,
        )

    def test_a_meal_log_is_not_mistaken_for_a_minor(self) -> None:
        history = [message("user", "i'm having 2 rotis and paneer")]
        self.assertIsNone(
            calorie_gate(
                history,
                "i'm having 2 rotis and paneer",
                "ooh paneer, nice — roughly 380 calories.",
            )
        )

    def test_the_verified_maintenance_figure_is_unchanged(self) -> None:
        history = [
            message("user", "i am 33, female, 170 cm, 62 kg, sedentary"),
        ]
        reply = calorie_gate(
            history, "what's my calorie target?", "let's start from maintenance."
        )
        self.assertIn("1,630", reply or "")
        self.assertNotIn("deficit", reply or "")



class StructuredWriteToolsTest(unittest.TestCase):
    """Order 10: the tools that finally write the modelled tables."""

    SESSION = "session-structured-writes"
    USER_KEY = "whatsapp:sha256:owner"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": self.USER_KEY,
                "chat_id": "owner@s.whatsapp.net",
                "message_id": "wamid.LIVE",
            }
        self.addCleanup(self._drop_context)

    def _drop_context(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def _capture(self, handler, args):
        """Run a tool handler, returning the write it would send to Convex.

        Reads are skipped. Saving a reminder now also schedules it, and
        working out when 10:30 in London is on a laptop in Kolkata means
        reading the user's timezone — a `get` that would otherwise be the last
        call recorded and leave every assertion here looking at an empty body.
        """
        sent: dict[str, object] = {}

        def fake_request(action, user_key, facts=None, body=None):
            if action != "get":
                sent.update(
                    {"action": action, "user_key": user_key, "body": body or {}}
                )
            return {"success": True}

        with patch.object(gates, "_convex_request", fake_request):
            raw = handler(args, session_id=self.SESSION)
        return sent, json.loads(raw)

    def test_a_meal_is_written_with_the_bound_user_key(self) -> None:
        sent, result = self._capture(
            gates._log_daily_entry,
            {
                "entry_type": "meal",
                "meal": {"items": ["paneer roll"], "calories": 380, "protein_grams": 19},
            },
        )
        self.assertTrue(result["success"])
        self.assertEqual(sent["action"], "log")
        self.assertEqual(sent["user_key"], self.USER_KEY)
        body = sent["body"]
        self.assertEqual(body["entryType"], "meal")
        self.assertEqual(body["meal"]["calories"], 380)
        self.assertEqual(body["meal"]["fiberGrams"], 0)
        self.assertEqual(body["externalMessageId"], "wamid.LIVE")

    def test_the_model_cannot_name_another_users_row(self) -> None:
        for handler, args in (
            (
                gates._log_daily_entry,
                {
                    "entry_type": "water",
                    "water_ml": 250,
                    "whatsappUserId": "whatsapp:sha256:someone-else",
                    "user_key": "whatsapp:sha256:someone-else",
                },
            ),
            (
                gates._set_target,
                {"steps": 8000, "whatsappUserId": "whatsapp:sha256:someone-else"},
            ),
            (
                gates._day_summary,
                {"whatsappUserId": "whatsapp:sha256:someone-else"},
            ),
        ):
            with self.subTest(tool=handler.__name__):
                sent, _ = self._capture(handler, args)
                self.assertEqual(sent["user_key"], self.USER_KEY)
                self.assertNotIn("whatsappUserId", sent["body"])

    def test_the_http_payload_carries_only_the_bound_user(self) -> None:
        captured: dict[str, object] = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read() -> bytes:
                return b'{"success": true}'

        def fake_urlopen(request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        with patch.dict(
            gates.os.environ,
            {
                "TED_CONVEX_SITE_URL": "https://example.convex.site",
                "TED_HERMES_SHARED_SECRET": "shh",
            },
        ):
            with patch.object(gates.urllib.request, "urlopen", fake_urlopen):
                gates._convex_request(
                    "log",
                    self.USER_KEY,
                    body={
                        "whatsappUserId": "whatsapp:sha256:someone-else",
                        "action": "delete",
                        "steps": 8000,
                    },
                )

        payload = captured["payload"]
        self.assertEqual(payload["whatsappUserId"], self.USER_KEY)
        self.assertEqual(payload["action"], "log")
        self.assertEqual(payload["steps"], 8000)

    def test_a_tool_refuses_when_no_whatsapp_user_is_active(self) -> None:
        for handler in (
            gates._log_daily_entry,
            gates._day_summary,
            gates._set_target,
            gates._set_reminder,
            gates._save_onboarding,
        ):
            with self.subTest(tool=handler.__name__):
                raw = handler({"entry_type": "water"}, session_id="no-such-session")
                self.assertFalse(json.loads(raw)["success"])

    def test_a_meal_without_items_is_refused_before_convex(self) -> None:
        sent, result = self._capture(gates._log_daily_entry, {"entry_type": "meal"})
        self.assertFalse(result["success"])
        self.assertEqual(sent, {})

    def test_snake_case_arguments_reach_convex_as_camel_case(self) -> None:
        sent, _ = self._capture(
            gates._set_reminder,
            {"quiet_hours_start": "22:00", "daily_review_time": "21:00", "max_per_day": 3},
        )
        self.assertEqual(
            sent["body"],
            {"quietHoursStart": "22:00", "dailyReviewTime": "21:00", "maxPerDay": 3},
        )

    def test_onboarding_rejects_a_step_that_is_not_in_the_flow(self) -> None:
        sent, result = self._capture(
            gates._save_onboarding, {"current_field": "not-a-step"}
        )
        self.assertFalse(result["success"])
        self.assertEqual(sent, {})

    def test_a_logged_entry_proves_the_claim_gate(self) -> None:
        _record_tool_success(
            tool_name="ted_log_entry",
            status="ok",
            args={},
            result=json.dumps({"success": True}),
            session_id=self.SESSION,
        )
        with gates._TURN_LOCK:
            proven = set(gates._TURN_CONTEXT[self.SESSION]["successful_actions"])
        self.assertIn("memory", proven)

    def test_saving_a_reminder_preference_does_not_prove_a_schedule(self) -> None:
        _record_tool_success(
            tool_name="ted_set_reminder",
            status="ok",
            args={},
            result=json.dumps({"success": True}),
            session_id=self.SESSION,
        )
        with gates._TURN_LOCK:
            proven = set(gates._TURN_CONTEXT[self.SESSION]["successful_actions"])
        self.assertIn("memory", proven)
        self.assertNotIn("cron", proven)
        # So the false claim is still stripped.
        self.assertNotIn(
            "8pm check-in is set",
            action_claim_gate("chalo, 8pm check-in is set.", successful_actions=proven),
        )


class TestRunIsolationTest(unittest.TestCase):
    """Order 07: nothing in a test run may reach the live machine state."""

    def _assert_not_in_hermes(self, path: Path, label: str) -> None:
        hermes = Path.home() / ".hermes"
        self.assertFalse(
            path == hermes or hermes in path.parents,
            f"{label} points into the live gateway state: {path}",
        )

    def test_no_gate_path_points_into_the_live_gateway(self) -> None:
        for label in (
            "_STATE_DIR",
            "_DISCLOSURE_STATE_PATH",
            "_ONBOARDING_STATE_PATH",
            "_AGENT_LOG_PATH",
        ):
            with self.subTest(path=label):
                self._assert_not_in_hermes(getattr(gates, label), label)

    def test_writing_state_lands_in_the_sandbox(self) -> None:
        gates._record_name_ask("fixture-key-that-must-not-escape")
        written = gates._ONBOARDING_STATE_PATH.read_text(encoding="utf-8")
        self.assertIn("fixture-key-that-must-not-escape", written)
        self._assert_not_in_hermes(gates._ONBOARDING_STATE_PATH, "onboarding state")

    def test_convex_credentials_are_not_inherited_by_the_suite(self) -> None:
        self.assertEqual(
            gates._missing_convex_env(),
            ["TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET"],
        )


class RegistrationVisibilityTest(unittest.TestCase):
    """Order 06: a dropped memory tool must never be silent."""

    class _Ctx:
        def __init__(self) -> None:
            self.tools: list[str] = []
            self.hooks: list[str] = []

        def register_tool(self, **kwargs: object) -> None:
            self.tools.append(str(kwargs.get("name")))

        def register_hook(self, name: str, _handler: object) -> None:
            self.hooks.append(name)

    def test_a_missing_variable_is_named_at_warning_level(self) -> None:
        ctx = self._Ctx()
        with patch.dict(
            gates.os.environ,
            {"TED_CONVEX_SITE_URL": "https://example.convex.site"},
            clear=True,
        ):
            with self.assertLogs("ted.safety_gates", level="WARNING") as captured:
                gates.register(ctx)

        joined = "\n".join(captured.output)
        self.assertIn("TED_HERMES_SHARED_SECRET", joined)
        self.assertNotIn("TED_CONVEX_SITE_URL", joined)
        self.assertIn("~/.hermes/.env", joined)

    def test_a_healthy_boot_still_announces_itself(self) -> None:
        ctx = self._Ctx()
        with patch.dict(
            gates.os.environ,
            {
                "TED_CONVEX_SITE_URL": "https://example.convex.site",
                "TED_HERMES_SHARED_SECRET": "shh",
            },
            clear=True,
        ):
            with self.assertLogs("ted.safety_gates", level="INFO") as captured:
                gates.register(ctx)

        self.assertIn("ted_safety_gates_registered", "\n".join(captured.output))
        self.assertIn("ted_memory_save", ctx.tools)
        self.assertIn("transform_llm_output", ctx.hooks)


class StorageOutageTest(unittest.TestCase):
    """When Convex is down the user is told the update did not save.

    SCOPING.md #27. The claim gate's "I haven't completed that action" is a
    different statement — it means Ted claimed something no tool did — and a
    tester cannot tell from it whether their meal is in the database.
    """

    SESSION = "storage-outage-session"
    SENDER = "outage@s.whatsapp.net"

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            _capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id=self.SENDER,
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="two rotis and dal",
            )
        self.addCleanup(gates._TURN_CONTEXT.pop, self.SESSION, None)

    @staticmethod
    def outage() -> dict[str, object]:
        return {
            "success": False,
            "error": gates._STORAGE_UNAVAILABLE,
            "storage_error": True,
        }

    def test_a_failed_log_tells_the_user_it_did_not_save(self) -> None:
        with patch.object(gates, "_convex_request", return_value=self.outage()):
            gates._log_daily_entry(
                {
                    "entry_type": "meal",
                    "meal": {"items": ["2 rotis", "dal"], "calories": 420},
                },
                session_id=self.SESSION,
            )

        reply = _transform_live_response(
            platform="whatsapp",
            session_id=self.SESSION,
            response_text="logged it — roughly 420 calories.",
        )

        self.assertEqual(reply, gates.STORAGE_NOT_SAVED)
        self.assertNotEqual(reply, gates.CLAIM_NOT_DONE)

    def test_the_outage_line_is_not_the_claim_gate_line(self) -> None:
        """Distinct strings, so a tester can tell the two failures apart."""
        self.assertNotEqual(gates.STORAGE_NOT_SAVED, gates.CLAIM_NOT_DONE)
        self.assertIn("save", gates.STORAGE_NOT_SAVED)
        self.assertIn("again", gates.STORAGE_NOT_SAVED)

    def test_a_silent_failure_still_reaches_the_user(self) -> None:
        """The reply claimed nothing, so the claim gate would have said nothing."""
        with patch.object(gates, "_convex_request", return_value=self.outage()):
            gates._log_daily_entry(
                {"entry_type": "water", "water_ml": 500},
                session_id=self.SESSION,
            )

        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id=self.SESSION,
                response_text="nice, that's 500ml.",
            ),
            gates.STORAGE_NOT_SAVED,
        )

    def test_a_reading_is_kept_but_never_implies_the_write_landed(self) -> None:
        self.assertEqual(
            gates.action_claim_gate(
                "I've saved that. 3 meals logged, 4,200 steps.",
                storage_failed=True,
            ),
            f"3 meals logged, 4,200 steps. {gates.STORAGE_NOT_SAVED}",
        )

    def test_a_healthy_turn_is_completely_unchanged(self) -> None:
        with patch.object(
            gates, "_convex_request", return_value={"success": True, "logged": 1}
        ):
            gates._log_daily_entry(
                {
                    "entry_type": "meal",
                    "meal": {"items": ["2 rotis", "dal"], "calories": 420},
                },
                session_id=self.SESSION,
            )

        with gates._TURN_LOCK:
            self.assertFalse(gates._TURN_CONTEXT[self.SESSION].get("storage_failed"))
        self.assertIsNone(
            gates.action_claim_gate("3 meals logged, 4,200 steps.", storage_failed=False)
        )

    def test_a_validation_refusal_is_not_reported_as_an_outage(self) -> None:
        """Bad model arguments are Ted's problem, not the database's."""
        gates._log_daily_entry({"entry_type": "nonsense"}, session_id=self.SESSION)

        with gates._TURN_LOCK:
            self.assertFalse(gates._TURN_CONTEXT[self.SESSION].get("storage_failed"))


class MemoryCacheTest(unittest.TestCase):
    """The pre-LLM Convex read is not repeated on every single turn."""

    USER = "whatsapp:sha256:cache-test"

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)

    def test_repeat_reads_inside_the_ttl_hit_the_cache(self) -> None:
        payload = {"success": True, "facts": [{"key": "name", "value": "Vandy"}]}
        with patch.object(
            gates, "_convex_request", return_value=payload
        ) as request:
            first = gates._cached_user_memory(self.USER)
            second = gates._cached_user_memory(self.USER)
            third = gates._cached_user_memory(self.USER)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_a_write_invalidates_the_cache(self) -> None:
        """A saved fact must be visible on the very next turn, not in 5 minutes."""
        with patch.object(
            gates,
            "_convex_request",
            return_value={"success": True, "facts": []},
        ) as request:
            gates._cached_user_memory(self.USER)
            gates._convex_write("save", self.USER, "", facts=[{"key": "a", "value": "b"}])
            gates._cached_user_memory(self.USER)

        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["get", "save", "get"],
        )

    def test_a_failed_read_is_never_cached(self) -> None:
        """One unlucky read must not leave Ted amnesiac for the whole TTL."""
        with patch.object(
            gates, "_convex_request", return_value={"success": False}
        ) as request:
            gates._cached_user_memory(self.USER)
            gates._cached_user_memory(self.USER)

        self.assertEqual(request.call_count, 2)

    def test_an_expired_entry_is_refetched(self) -> None:
        payload = {"success": True, "facts": []}
        with patch.object(gates, "_convex_request", return_value=payload) as request:
            gates._cached_user_memory(self.USER)
            stamp, value = gates._MEMORY_CACHE[self.USER]
            gates._MEMORY_CACHE[self.USER] = (stamp - gates._MEMORY_CACHE_TTL - 1, value)
            gates._cached_user_memory(self.USER)

        self.assertEqual(request.call_count, 2)

    def test_users_do_not_share_a_cache_entry(self) -> None:
        """Per-user isolation is the whole point of the SHA-256 keying."""
        with patch.object(
            gates, "_convex_request", return_value={"success": True, "facts": []}
        ) as request:
            gates._cached_user_memory("whatsapp:sha256:aaa")
            gates._cached_user_memory("whatsapp:sha256:bbb")
            gates._cached_user_memory("whatsapp:sha256:aaa")

        self.assertEqual(request.call_count, 2)


class ConvexTimeoutTest(unittest.TestCase):
    """The read on the pre-LLM path is short; a write may wait longer."""

    def _timeout_for(self, action: str) -> float:
        seen: dict[str, float] = {}

        class _Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_: object) -> bool:
                return False

            @staticmethod
            def read() -> bytes:
                return b'{"success": true}'

        def _urlopen(_request: object, timeout: float = 0.0) -> object:
            seen["timeout"] = timeout
            return _Response()

        with patch.dict(
            gates.os.environ,
            {
                "TED_CONVEX_SITE_URL": "https://example.convex.site",
                "TED_HERMES_SHARED_SECRET": "shh",
            },
            clear=True,
        ):
            with patch.object(gates.urllib.request, "urlopen", _urlopen):
                gates._convex_request(action, "whatsapp:sha256:timeout")
        return seen["timeout"]

    def test_the_per_turn_read_is_the_short_timeout(self) -> None:
        self.assertEqual(self._timeout_for("get"), gates._CONVEX_READ_TIMEOUT)

    def test_a_write_keeps_the_longer_timeout(self) -> None:
        for action in ("save", "log", "target", "reminder", "onboarding", "delete"):
            with self.subTest(action=action):
                self.assertEqual(
                    self._timeout_for(action), gates._CONVEX_WRITE_TIMEOUT
                )

    def test_the_read_timeout_is_shorter_than_it_was(self) -> None:
        """5s on every turn was up to 5s of dead air before Ted even thought."""
        self.assertLess(gates._CONVEX_READ_TIMEOUT, 5.0)


class DuplicateAndDateConfirmationTest(unittest.TestCase):
    """Milestone 10: Ted asks before writing a repeat or a day that is not today."""

    SESSION = "milestone-10-session"
    SENDER = "m10@s.whatsapp.net"

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            _capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id=self.SENDER,
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="dal and rice",
            )
        self.addCleanup(gates._TURN_CONTEXT.pop, self.SESSION, None)

    def log(self, **extra: object) -> dict:
        args = {
            "entry_type": "meal",
            "meal": {"items": ["dal", "rice"], "calories": 420},
        }
        args.update(extra)
        return json.loads(gates._log_daily_entry(args, session_id=self.SESSION))

    def test_the_flags_default_to_false_on_every_call(self) -> None:
        """An omitted flag must never read as permission."""
        seen = {}
        with patch.object(
            gates,
            "_convex_request",
            side_effect=lambda *a, **k: seen.update(k.get("body") or {})
            or {"success": True},
        ):
            self.log()
        self.assertIs(seen["dateConfirmed"], False)
        self.assertIs(seen["secondOneConfirmed"], False)
        self.assertEqual(seen["today"], gates._today())

    def test_a_clash_is_reported_as_a_question_not_a_save(self) -> None:
        occurred = int(time.mktime((2026, 9, 2, 13, 15, 0, 0, 0, -1)) * 1000)
        with patch.object(
            gates,
            "_convex_request",
            return_value={
                "success": False,
                "needsConfirmation": "duplicate",
                "clashesWith": {
                    "entryType": "meal",
                    "occurredAt": occurred,
                    "dedupeKey": "msg:abc",
                },
            },
        ):
            result = self.log()

        self.assertFalse(result["success"])
        self.assertEqual(result["needsConfirmation"], "duplicate")
        self.assertIn("Nothing was saved", result["ask"])
        self.assertIn("lunch", result["ask"])
        self.assertIn("1:15 pm", result["ask"])
        self.assertIn("second_one_confirmed", result["ask"])
        self.assertIn("msg:abc", result["ask"])

    def test_a_clash_does_not_unlock_the_save_claim(self) -> None:
        """success is false, so "logged it" is still stripped."""
        with patch.object(
            gates,
            "_convex_request",
            return_value={
                "success": False,
                "needsConfirmation": "duplicate",
                "clashesWith": {"entryType": "meal", "dedupeKey": "k1"},
            },
        ):
            raw = gates._log_daily_entry(
                {"entry_type": "meal", "meal": {"items": ["dal"], "calories": 420}},
                session_id=self.SESSION,
            )
        gates._record_tool_success(
            tool_name="ted_log_entry", status="ok", args={}, result=raw,
            session_id=self.SESSION,
        )
        with gates._TURN_LOCK:
            proven = set(gates._TURN_CONTEXT[self.SESSION]["successful_actions"])
        self.assertNotIn("memory", proven)
        self.assertEqual(
            gates.action_claim_gate("logged it.", successful_actions=proven),
            gates.CLAIM_NOT_DONE,
        )

    def test_a_clash_is_not_reported_as_a_storage_outage(self) -> None:
        """Ted asking a question is not the database being down."""
        with patch.object(
            gates,
            "_convex_request",
            return_value={
                "success": False,
                "needsConfirmation": "duplicate",
                "clashesWith": {"entryType": "meal", "dedupeKey": "k1"},
            },
        ):
            self.log()
        with gates._TURN_LOCK:
            self.assertFalse(gates._TURN_CONTEXT[self.SESSION].get("storage_failed"))

    def test_a_named_date_is_reported_as_a_question(self) -> None:
        with patch.object(
            gates,
            "_convex_request",
            return_value={
                "success": False,
                "needsConfirmation": "date",
                "localDate": "2026-09-01",
                "today": "2026-09-02",
            },
        ):
            result = self.log(local_date="2026-09-01")

        self.assertFalse(result["success"])
        self.assertIn("2026-09-01", result["ask"])
        self.assertIn("not today", result["ask"])
        self.assertIn("date_confirmed", result["ask"])

    def test_a_confirmed_answer_is_passed_through(self) -> None:
        seen = {}
        with patch.object(
            gates,
            "_convex_request",
            side_effect=lambda *a, **k: seen.update(k.get("body") or {})
            or {"success": True, "entryId": "e1"},
        ):
            result = self.log(second_one_confirmed=True, date_confirmed=True)
        self.assertIs(seen["secondOneConfirmed"], True)
        self.assertIs(seen["dateConfirmed"], True)
        self.assertTrue(result["success"])

    def test_a_truthy_string_is_not_a_confirmation(self) -> None:
        """Only a real boolean True counts, so a hallucinated value cannot pass."""
        seen = {}
        with patch.object(
            gates,
            "_convex_request",
            side_effect=lambda *a, **k: seen.update(k.get("body") or {})
            or {"success": True},
        ):
            self.log(second_one_confirmed="yes", date_confirmed="true")
        self.assertIs(seen["secondOneConfirmed"], False)
        self.assertIs(seen["dateConfirmed"], False)

    def test_meal_slots_read_the_way_a_person_would_say_them(self) -> None:
        for hour, expected in ((8, "breakfast"), (13, "lunch"), (17, "a snack"), (20, "dinner")):
            with self.subTest(hour=hour):
                self.assertEqual(gates._meal_slot(hour), expected)
        self.assertEqual(gates._meal_slot(3), "a meal")


class AttachmentBoundaryTest(unittest.TestCase):
    """SCOPING #8 and #10: photos log meals; PDFs are health plans, never updates."""

    SESSION = "attachment-session"

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            _capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id="attach@s.whatsapp.net",
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="here you go",
            )
        self.addCleanup(gates._TURN_CONTEXT.pop, self.SESSION, None)

    def log(self, source: str, entry_type: str) -> dict:
        args: dict[str, object] = {"entry_type": entry_type, "source": source}
        if entry_type == "meal":
            args["meal"] = {"items": ["dal"], "calories": 420}
        if entry_type == "water":
            args["water_ml"] = 500
        with patch.object(
            gates, "_convex_request", return_value={"success": True}
        ) as request:
            result = json.loads(gates._log_daily_entry(args, session_id=self.SESSION))
        return {"result": result, "wrote": request.called}

    def test_a_pdf_can_never_log_a_daily_update(self) -> None:
        for entry_type in gates._ENTRY_TYPES:
            with self.subTest(entry_type=entry_type):
                outcome = self.log("pdf", entry_type)
                self.assertFalse(outcome["result"]["success"])
                self.assertFalse(outcome["wrote"], "a PDF reached the database")
                self.assertIn("health plan", outcome["result"]["error"])

    def test_a_photo_logs_a_meal_and_nothing_else(self) -> None:
        self.assertTrue(self.log("photo", "meal")["wrote"])
        for entry_type in ("water", "steps", "workout", "commitment"):
            with self.subTest(entry_type=entry_type):
                outcome = self.log("photo", entry_type)
                self.assertFalse(outcome["wrote"])
                self.assertIn("only log a meal", outcome["result"]["error"])

    def test_text_and_voice_still_carry_everything(self) -> None:
        for source in ("text", "voice"):
            for entry_type in gates._ENTRY_TYPES:
                with self.subTest(source=source, entry_type=entry_type):
                    self.assertTrue(self.log(source, entry_type)["wrote"])

    def test_the_rule_is_a_table_not_a_guess(self) -> None:
        self.assertIsNone(gates._attachment_refusal("photo", "meal"))
        self.assertIsNotNone(gates._attachment_refusal("photo", "steps"))
        self.assertIsNotNone(gates._attachment_refusal("pdf", "meal"))
        self.assertIsNone(gates._attachment_refusal("text", "steps"))


class BadReplyReportTest(unittest.TestCase):
    """Milestone 11: "report that" stores the exact turn and confirms it."""

    SESSION = "report-session"
    SENDER = "report@s.whatsapp.net"
    BAD = "eat 900 calories a day and you'll drop 5kg by friday."

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)
        self.history = [
            message("assistant", DISCLOSURE_MESSAGE),
            message("user", "how do i lose weight fast"),
            message("assistant", self.BAD),
        ]
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            _capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id=self.SENDER,
                conversation_history=self.history,
                user_message="that reply was wrong",
            )
        self.addCleanup(gates._TURN_CONTEXT.pop, self.SESSION, None)

    def test_the_phrases_a_person_would_actually_use(self) -> None:
        for phrase in (
            "report that",
            "report this reply",
            "that reply was wrong",
            "that answer is unsafe",
            "this was bad advice",
            "flag that",
            "wrong answer",
            "that's dangerous",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(gates._asks_to_report(phrase))

    def test_ordinary_conversation_is_not_a_report(self) -> None:
        for phrase in (
            "i had two rotis",
            "that was a good workout",
            "i got the answer wrong on my quiz",
            "report my weekly steps",
            "that reply was helpful",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(gates._asks_to_report(phrase))

    def test_the_reported_turn_is_stored_verbatim(self) -> None:
        sent = {}
        with patch.object(
            gates,
            "_convex_request",
            side_effect=lambda action, key, **k: sent.update(
                {"action": action, "key": key, **(k.get("body") or {})}
            )
            or {"success": True, "reportId": "r1"},
        ):
            reply = _transform_live_response(
                platform="whatsapp",
                session_id=self.SESSION,
                response_text="sorry about that! anyway, what did you have for lunch?",
            )

        self.assertEqual(sent["action"], "report")
        self.assertEqual(sent["assistantMessage"], self.BAD)
        self.assertEqual(sent["userMessage"], "that reply was wrong")
        self.assertEqual(reply, gates.REPORT_CONFIRMATION)

    def test_the_model_does_not_get_to_write_the_confirmation(self) -> None:
        """Whatever the model said, the user gets the same sentence."""
        with patch.object(
            gates, "_convex_request", return_value={"success": True}
        ):
            for model_said in ("no problem!", "I have escalated this to a human coach.", ""):
                with self.subTest(model_said=model_said):
                    self.assertEqual(
                        _transform_live_response(
                            platform="whatsapp",
                            session_id=self.SESSION,
                            response_text=model_said,
                        ),
                        gates.REPORT_CONFIRMATION,
                    )

    def test_a_failed_store_is_admitted_not_faked(self) -> None:
        with patch.object(
            gates,
            "_convex_request",
            return_value={"success": False, "error": "down", "storage_error": True},
        ):
            reply = _transform_live_response(
                platform="whatsapp",
                session_id=self.SESSION,
                response_text="noted!",
            )
        self.assertEqual(reply, gates.REPORT_NOT_SAVED)
        self.assertNotEqual(reply, gates.REPORT_CONFIRMATION)

    def test_nothing_to_report_falls_back_to_normal_conversation(self) -> None:
        session = "report-empty"
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            _capture_turn(
                platform="whatsapp",
                session_id=session,
                sender_id=self.SENDER,
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="report that",
            )
        self.addCleanup(gates._TURN_CONTEXT.pop, session, None)
        with patch.object(gates, "_convex_request", return_value={"success": True}) as req:
            reply = _transform_live_response(
                platform="whatsapp",
                session_id=session,
                response_text="what would you like me to look at?",
            )
        self.assertNotEqual(reply, gates.REPORT_CONFIRMATION)
        self.assertFalse(
            any(call.args and call.args[0] == "report" for call in req.call_args_list)
        )


class RepeatTargetAskGateTest(unittest.TestCase):
    """One target ask per day. The second one is a nag, whatever it wears.

    Both strings in the first test are real. Ted sent them to the same user
    two hours apart on 3 Sep 2026, in answer to the same question, and the
    voice card was carrying the correct version of that line the whole time.
    """

    FIRST = (
        "light day so far, moong sprouts salad and then those cutlets, "
        "420 cal and 20g protein logged, no target set yet so nothing to "
        "measure against \U0001f937\u200d\u2640\ufe0f no water or steps in either.\n"
        "wanna set a calorie/protein target so \"how am i doing\" actually "
        "means something?"
    )
    SECOND = (
        "sprouts, cutlets, and that peanut toast, three light-ish meals, no "
        "water or steps logged yet. still no target set though, so this is "
        "just numbers floating without a goal, wanna fix that?"
    )

    # Live, 3 Sep, 20:54:59 and 20:55:04 — two "how am i doing" messages that
    # arrived five seconds apart. Kept verbatim: the second one is the exact
    # sentence the gate was built to stop and did not.
    FIRST_LIVE = (
        "sprouts, cutlets, and that peanut toast, three light meals so far, "
        "but zero water and steps logged. no target set either so i can't "
        "really tell you good or bad, just... floating. wanna fix the target "
        "bit?"
    )
    SECOND_LIVE = (
        "same picture as a sec ago Vandy, three meals in, water and steps "
        "still at zero. give me a target and this actually turns into an "
        "answer instead of a shrug \U0001f937\u200d\u2640\ufe0f"
    )

    def setUp(self) -> None:
        self.user_key = f"repeat-target-{id(self)}"
        self.addCleanup(gates._ONBOARDING_STATE.pop, self.user_key, None)

    def ask(self, response: str, user_message: str = "How am i doing today"):
        return gates.repeat_target_ask_gate(user_message, response, self.user_key)

    def test_the_first_ask_goes_out_untouched(self) -> None:
        self.assertIsNone(self.ask(self.FIRST))
        self.assertTrue(gates._target_asked_today(self.user_key))

    def test_the_second_ask_the_same_day_loses_the_question(self) -> None:
        self.assertIsNone(self.ask(self.FIRST))
        stripped = self.ask(self.SECOND)
        self.assertIsNotNone(stripped)
        self.assertNotIn("?", stripped)
        for word in ("target", "goal", "wanna fix"):
            self.assertNotIn(word, stripped.lower())
        # What is left is the actual answer to "how am i doing".
        self.assertIn("peanut toast", stripped)
        self.assertIn("three light-ish meals", stripped)


    def test_an_ask_without_a_question_mark_still_counts(self) -> None:
        """The 20:54 pair on 3 Sep, five seconds apart, that got past the gate.

        The first ask ended "wanna fix the target bit?" and was counted. The
        second was an imperative — no "?" — so the trigger said no and the
        nag went out.
        """
        self.assertIsNone(self.ask(self.FIRST_LIVE))
        stripped = self.ask(self.SECOND_LIVE)
        self.assertEqual(
            stripped,
            "same picture as a sec ago Vandy, three meals in, water and "
            "steps still at zero.",
        )

    def test_a_demand_is_told_apart_from_a_confirmation(self) -> None:
        """Both open with a verb and both say "target"; only one is an ask."""
        for demand in (
            "give me a target and this actually turns into an answer",
            "set a target and we're away",
            "let's fix a calorie target",
            "just tell me your protein target",
        ):
            with self.subTest(demand=demand):
                self.assertTrue(gates._is_target_ask(demand))
        for statement in (
            "your daily step target is set at 9000 steps.",
            "i've set your protein target to 90g.",
            "8,200 is close, just 800 short of your 9,000 target today.",
            "give me a shout when you're done",
        ):
            with self.subTest(statement=statement):
                self.assertFalse(gates._is_target_ask(statement))

    def test_a_new_day_earns_one_more_ask(self) -> None:
        self.assertIsNone(self.ask(self.FIRST))
        gates._update_onboarding(self.user_key, target_ask_date="2026-09-02")
        self.assertIsNone(self.ask(self.SECOND))

    def test_they_raised_it_so_they_get_an_answer(self) -> None:
        """Asking twice is nagging. Answering twice is the job."""
        self.assertIsNone(self.ask(self.FIRST))
        for message in (
            "what should my protein target be?",
            "no target yet, what do you suggest",
            "set my calorie target",
        ):
            with self.subTest(message=message):
                self.assertIsNone(self.ask(self.SECOND, user_message=message))

    def test_ordinary_target_talk_is_never_in_range(self) -> None:
        """Confirming, measuring and coaching all survive."""
        self.assertIsNone(self.ask(self.FIRST))
        for reply in (
            "your daily step target is set at 9000 steps.",
            "8,200 is close, just 800 short of your 9,000 target today.",
            "you're at 5,600 steps, so 2,400 short. do you have plans to hit "
            "that goal today?",
            "logged it \U0001f44d",
            "",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(self.ask(reply))

    def test_an_ask_that_is_the_whole_message_is_left_alone(self) -> None:
        """Sending nothing is worse than sending the nag."""
        self.assertIsNone(self.ask(self.FIRST))
        self.assertIsNone(self.ask("wanna give me a protein target?"))

    def test_a_bare_reask_is_still_caught_when_it_has_company(self) -> None:
        self.assertIsNone(self.ask(self.FIRST))
        stripped = self.ask(
            "three meals in, decent protein. want to give me a protein "
            "target so this actually means something?"
        )
        self.assertEqual(stripped, "three meals in, decent protein.")

    def test_the_whole_real_path_strips_the_second_nag(self) -> None:
        """Through transform_response, not just the gate in isolation.

        This is the 3 Sep failure end to end: two "how am i doing" turns two
        hours apart, and the second reply arrives without the re-ask.
        """
        user_key = f"repeat-target-e2e-{id(self)}"
        self.addCleanup(reset_user, user_key)
        history = [
            message("user", "hi"),
            message("assistant", VANDY_DISCLOSURE),
            message("user", "Meal and steps"),
        ]
        asked = "How am i doing today"
        first = transform_response(
            history=history,
            user_message=asked,
            response_text=self.FIRST,
            user_key=user_key,
        )
        self.assertIsNone(first)

        history.extend(
            [message("assistant", self.FIRST), message("user", "New meal")]
        )
        second = transform_response(
            history=history,
            user_message=asked,
            response_text=self.SECOND,
            user_key=user_key,
        )
        self.assertIsNotNone(second)
        self.assertNotIn("?", second)
        self.assertNotIn("target", second.lower())
        self.assertIn("peanut toast", second)

    # Every string below is one Ted actually sent, taken from the live
    # transcript rather than invented, and classified by hand. The detector
    # was measured against all 60 target/goal replies in that transcript;
    # these are the ones that decide the shape of it. Two rounds of real
    # mistakes came out of this table: a `[^?]*` trigger that reached across
    # sentence boundaries, and an English-only cue list that was blind to the
    # Hinglish form of the same question.
    REAL_ASKS = (
        "wanna set a calorie/protein target so \"how am i doing\" actually "
        "means something?",
        "got it, 33 \u2014 noted for reference.  what's your daily step "
        "target, roughly?",
        "yep, you're Vandy. now the actual question: what's your daily step "
        "target? throw me a number like 6k, 8k, 10k.",
        "Yes! Just a quick one: What are your daily targets for steps, water "
        "intake, and workouts?",
        "Could you let me know your target step count for today?",
        "Kitne steps ka target hai aaj?",
    )
    REAL_NOT_ASKS = (
        # Confirming a target, then asking for something else entirely. The
        # first trigger read this as an ask and would have spent the day's
        # one ask on it.
        "Great, your daily calorie target is set at 1400. Before we move "
        "forward, could you share your age, height, weight, and activity "
        "level?",
        # Coaching about a target that already exists is not a re-ask.
        "You're at 5,600 steps now, so you're just 2,400 steps away from "
        "your 8,000-step target. Do you have any plans to help you reach "
        "that goal today?",
        "Great job reaching 5,600 steps! Is that close to your daily "
        "target, or do you have more steps planned for today?",
        # The erasure question lists "targets" among what it will wipe.
        # Stripping the question out of this would be the worst edit here.
        "just to make sure, you want me to permanently wipe everything I "
        "have on you, profile, targets, logs, all of it? no undo once it's "
        "done.",
        # The onboarding goal question is a state machine that has to keep
        # asking until it is answered, so "goal" is out of range by design.
        "Pradosh, got it \U0001f64c so what's the actual goal here, drop "
        "weight, build muscle, just get more consistent with eating and "
        "moving?",
        "your daily step target is set at 9000 steps.",
    )

    def test_classifies_real_transcript_lines(self) -> None:
        for line in self.REAL_ASKS:
            with self.subTest(ask=line[:60]):
                self.assertTrue(gates._contains_target_ask(line))
        for line in self.REAL_NOT_ASKS:
            with self.subTest(not_ask=line[:60]):
                self.assertFalse(gates._contains_target_ask(line))

    def test_a_known_miss_stays_documented(self) -> None:
        """One real ask the detector does not catch, recorded rather than hidden.

        A bare noun-phrase question with the verb in the *next* sentence. The
        cue list is sentence-scoped, which is what keeps the false positives
        above out, and this is the price of that. If a future change catches
        it, this test fails and should simply be deleted.
        """
        self.assertFalse(
            gates._contains_target_ask(
                "hey, so, step count and the meal target? give me numbers "
                "and we're set to go"
            )
        )

    def test_no_user_key_means_no_state_to_count_with(self) -> None:
        self.assertIsNone(
            gates.repeat_target_ask_gate("how am i doing", self.SECOND, "")
        )


class TheCardDoesNotTeachRudenessTest(unittest.TestCase):
    """The rude line came from the documents, not from the model.

    "want to give me a protein target so this actually means something?" sat
    in SOUL.md as the good answer and in VOICE_CARD as a worked example. On
    3 Sep at 20:55 Ted wrote "give me a target and this actually turns into
    an answer instead of a shrug" — the same sentence with the serial numbers
    filed off. It copied what it was shown, which is what a worked example is
    for. So the examples are the fix, and this is the guard on them.
    """

    SOUL = Path(__file__).with_name("SOUL.md")

    # Telling the user their own day is worthless until they do you a favour.
    PUNCHLINE = (
        "so this actually means something",
        "instead of a shrug",
        "just numbers floating",
        "nothing to measure against",
    )

    def examples(self) -> list[str]:
        """Only the "Real examples of you:" block.

        The "Never you:" block quotes these same sentences on purpose, which
        is the point of it.
        """
        lines: list[str] = []
        collecting = False
        for line in gates.VOICE_CARD.splitlines():
            if line.startswith("Real examples of you:"):
                collecting = True
                continue
            if collecting and line and not line.startswith(" "):
                break
            if collecting and line.strip():
                lines.append(line.strip())
        return lines

    def test_the_block_is_found_at_all(self) -> None:
        """A guard on the guard: a renamed heading must not pass silently."""
        self.assertGreater(len(self.examples()), 4)

    def test_the_card_never_shows_it_as_something_to_say(self) -> None:
        for said in self.examples():
            for phrase in self.PUNCHLINE:
                with self.subTest(line=said, phrase=phrase):
                    self.assertNotIn(phrase, said)

    def test_ted_does_not_order_the_user_about(self) -> None:
        """"give me a target" is an order. The card must not model one."""
        for said in self.examples():
            with self.subTest(said=said):
                self.assertFalse(
                    said.strip('"').startswith(("give me a target", "set a target")),
                    f"the card shows an order as something to say: {said}",
                )

    def test_soul_never_marks_it_with_a_tick(self) -> None:
        if not self.SOUL.exists():
            self.skipTest("SOUL.md is not beside the tests")
        for line in self.SOUL.read_text(encoding="utf-8").splitlines():
            if "\u2713" not in line and "\u2705" not in line:
                continue
            for phrase in self.PUNCHLINE:
                with self.subTest(line=line[:60], phrase=phrase):
                    self.assertNotIn(phrase, line)


class ReminderReceiptGateTest(unittest.TestCase):
    """A confirmation is not a receipt.

    "done, pinging you in 10" was true — the job existed, so the claim gate
    had nothing to strip. It just never said back the thing that was asked
    for. The subject and the time both come off the cronjob tool's own
    result, so this gate never has to read the model's prose to know them.
    """

    RECEIPT = "done, pinging you in 10 \U0001f375"
    user_key = "reminder-receipt-test"

    def job(self, name: str = "Green tea reminder", minutes: int = 10) -> dict:
        when = gates._local_now(self.user_key) + timedelta(minutes=minutes)
        return {"name": name, "next_run_at": when.isoformat()}

    def gate(self, response: str, job: dict | None = None):
        return gates.reminder_receipt_gate(
            response, self.job() if job is None else job, self.user_key
        )

    def test_the_receipt_becomes_the_thing_itself(self) -> None:
        self.assertEqual(
            self.gate(self.RECEIPT), "green tea, ten minutes on the clock \u23f3"
        )

    def test_a_reply_that_already_says_it_back_is_left_alone(self) -> None:
        for good in (
            "green tea, ten minutes on the clock \u23f3",
            "green tea in ten, i'll shout \u23f3",
            "ok green tea at 8:40",
        ):
            with self.subTest(reply=good):
                self.assertIsNone(self.gate(good))

    def test_no_cron_job_this_turn_means_no_gate(self) -> None:
        self.assertIsNone(gates.reminder_receipt_gate(self.RECEIPT, None, self.user_key))

    def test_a_clock_time_once_the_wait_stops_being_a_wait(self) -> None:
        line = self.gate("all set!", self.job("Iron reminder", minutes=200))
        self.assertIsNotNone(line)
        self.assertTrue(line.startswith("iron, "))
        self.assertNotIn("on the clock", line)

    def test_tomorrow_is_named_rather_than_implied(self) -> None:
        # Far enough out that it is always the next day whatever time the
        # suite runs, and never further than that.
        job = self.job("Iron reminder", minutes=60 * 25)
        self.assertIn(
            gates._reminder_when(self.user_key, job["next_run_at"]).split()[-1],
            ("tomorrow", "monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday"),
        )

    def test_a_name_that_is_not_a_label_leaves_the_reply_alone(self) -> None:
        """A wrong sentence written confidently is worse than the receipt."""
        for name in (
            # Ted's own scheduled jobs are keyed, not named.
            "ted:sha256:owner:daily_review",
            # An unnamed job takes the first fifty characters of its prompt.
            "Send Vandy a short, warm, casual Ted-style WhatsApp remin",
            "",
            # Too long to be a subject; this is a sentence.
            "the thing we talked about earlier this evening, the tea one",
        ):
            with self.subTest(name=name):
                self.assertIsNone(self.gate("sorted \U0001f44d", self.job(name)))

    def test_an_unreadable_time_leaves_the_reply_alone(self) -> None:
        self.assertIsNone(
            self.gate(self.RECEIPT, {"name": "Green tea reminder", "next_run_at": "soon"})
        )

    def test_a_reply_carrying_anything_else_is_never_overwritten(self) -> None:
        """Losing a logged meal is the worse of the two failures."""
        self.assertIsNone(
            self.gate(
                "logged the dal, 340 cal in. and done, pinging you in 10. "
                "want me to line up anything else for tonight?"
            )
        )

    def test_names_keep_the_shape_they_were_given(self) -> None:
        self.assertTrue(self.gate("all set!", self.job("CoQ10 reminder")).startswith("CoQ10,"))
        self.assertTrue(self.gate("all set!", self.job("Vitamin D reminder")).startswith("vitamin D,"))

    def test_the_live_path_carries_the_job_from_the_tool(self) -> None:
        session = "reminder-receipt-live"
        _capture_turn(
            platform="whatsapp",
            session_id=session,
            conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="remind me about green tea in 10 minutes",
        )
        when = datetime.now(dt_timezone.utc) + timedelta(minutes=10)
        _record_tool_success(
            session_id=session,
            status="ok",
            tool_name="cronjob",
            args={"action": "create"},
            result=json.dumps(
                {
                    "success": True,
                    "name": "Green tea reminder",
                    "next_run_at": when.isoformat(),
                }
            ),
        )
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id=session,
                response_text=self.RECEIPT,
            ),
            "green tea, ten minutes on the clock \u23f3",
        )

    def test_a_cron_list_leaves_nothing_behind_for_the_gate(self) -> None:
        session = "reminder-receipt-list"
        _capture_turn(
            platform="whatsapp",
            session_id=session,
            conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="what reminders do i have",
        )
        _record_tool_success(
            session_id=session,
            status="ok",
            tool_name="cronjob",
            args={"action": "list"},
            result='{"success": true, "count": 0}',
        )
        with gates._TURN_LOCK:
            self.assertIsNone(gates._TURN_CONTEXT[session].get("reminder_set"))

class CronReminderGateTest(unittest.TestCase):
    """Milestone 12: cron reminders are Ted talking, so Ted's rules apply.

    cron/scheduler.py builds its agent with platform="cron", so before this
    every gate here returned early and a scheduled ping reached a real WhatsApp
    thread with nothing checked.
    """

    SESSION = "cron_919661eba04c_20260903_084500"
    CHAT = "144504426369026@lid"

    def jobs_file(self, origin: dict | None) -> object:
        job = {"id": "919661eba04c", "name": "CoQ10 reminder"}
        if origin is not None:
            job["origin"] = origin
        path = Path(self.tmp) / "jobs.json"
        path.write_text(json.dumps([job]), encoding="utf-8")
        return patch.object(gates, "_CRON_JOBS_PATH", path)

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_a_cron_run_is_no_longer_invisible_to_the_gate(self) -> None:
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            self.assertEqual(
                gates._cron_whatsapp_recipient(self.SESSION), self.CHAT
            )

    def test_a_cron_run_is_written_with_the_voice_card_in_the_room(self) -> None:
        """The evening review is a cron run, and it used to write blind.

        `_capture_turn` guarded on platform == "whatsapp", so every message
        Ted sends unprompted was generated with no voice guidance at all —
        the one class of message a user gets without asking for it.
        """
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            captured = gates._capture_turn(
                platform="cron",
                session_id=self.SESSION,
                sender_id="",
                user_message="write the evening review",
                conversation_history=[],
            )
        self.assertIsNotNone(captured)
        self.assertIn("close friend in Bangalore", captured["context"])
        self.assertIn("that's your ten. green tea", captured["context"])

    def test_a_cron_run_for_someone_elses_job_gets_no_context(self) -> None:
        with self.jobs_file({"platform": "telegram", "chat_id": "123"}):
            self.assertIsNone(
                gates._capture_turn(
                    platform="cron",
                    session_id=self.SESSION,
                    sender_id="",
                    user_message="ping",
                    conversation_history=[],
                )
            )

    def test_a_cron_review_knows_whose_name_to_use(self) -> None:
        """The evening review is the message most worth having a name in it."""
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            user_key = gates._user_state_key("whatsapp", self.CHAT, self.SESSION)
            gates._remember_name(user_key, "Vandana")
            self.addCleanup(gates._update_onboarding, user_key, name=None)
            captured = gates._capture_turn(
                platform="cron",
                session_id=self.SESSION,
                sender_id="",
                user_message="write the evening review",
                conversation_history=[],
            )
        self.assertIn("You are talking to Vandana", captured["context"])

    def test_the_voice_card_names_the_flat_reminder_shapes(self) -> None:
        """3 Sep: "done, pinging you in 10" and then "green tea time"."""
        self.assertIn("ten minutes on the clock", gates.VOICE_CARD)
        self.assertIn("pinging you in 10", gates.VOICE_CARD)
        self.assertIn("green tea time", gates.VOICE_CARD)

    def test_a_cron_job_for_another_platform_is_left_alone(self) -> None:
        with self.jobs_file({"platform": "telegram", "chat_id": "123"}):
            self.assertIsNone(gates._cron_whatsapp_recipient(self.SESSION))
        with self.jobs_file(None):
            self.assertIsNone(gates._cron_whatsapp_recipient(self.SESSION))

    def test_an_ordinary_session_id_is_not_mistaken_for_cron(self) -> None:
        for session in ("20260901_235408_3bab3370", "", "cron_", "croncron_x_1"):
            with self.subTest(session=session):
                self.assertIsNone(gates._cron_job_id(session))

    def test_the_recipient_resolves_to_the_same_person_as_a_live_turn(self) -> None:
        """The cap and quiet hours must apply to the real user, not a stray key."""
        from_cron = gates._user_state_key("whatsapp", self.CHAT, self.SESSION)
        from_chat = gates._user_state_key("whatsapp", self.CHAT, "live-session")
        self.assertEqual(from_cron, from_chat)

    def test_quiet_hours_suppress_the_ping_entirely(self) -> None:
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            with patch.object(
                gates,
                "_convex_request",
                return_value={"success": True, "allowed": False, "reason": "quietHours"},
            ):
                self.assertEqual(
                    _transform_live_response(
                        platform="cron",
                        session_id=self.SESSION,
                        response_text="morning! coq10 time ☀️",
                    ),
                    gates.CRON_SILENT,
                )

    def test_the_cap_and_a_pause_suppress_it_too(self) -> None:
        for reason in ("dailyCap", "paused"):
            with self.subTest(reason=reason):
                with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
                    with patch.object(
                        gates,
                        "_convex_request",
                        return_value={"success": True, "allowed": False, "reason": reason},
                    ):
                        self.assertEqual(
                            _transform_live_response(
                                platform="cron",
                                session_id=self.SESSION,
                                response_text="coq10 time",
                            ),
                            gates.CRON_SILENT,
                        )

    def test_an_unreadable_policy_falls_back_to_default_quiet_hours(self) -> None:
        """A Convex blip must not silently kill reminders the user set up.

        Blanket suppression looked like the safe failure until it was pointed
        at a real account: the five live vitamin reminders have no row in the
        reminders table at all, so "no policy" and "policy unreadable" both
        meant "send nothing", with nothing anywhere to say why.
        """
        outage = {"success": False, "error": "unavailable"}

        def reply_at(clock: str) -> str | None:
            with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
                with patch.object(gates, "_convex_request", return_value=outage):
                    with patch.object(gates.time, "strftime", lambda *_: clock):
                        return _transform_live_response(
                            platform="cron",
                            session_id=self.SESSION,
                            response_text="coq10 time",
                        )

        # Daytime: the ping the user asked for still arrives.
        for clock in ("08:45", "10:30", "16:00", "21:59"):
            with self.subTest(clock=clock):
                self.assertIsNone(reply_at(clock))
        # Night: 3am is still 3am when the database is down.
        for clock in ("22:00", "23:30", "03:00", "06:59"):
            with self.subTest(clock=clock):
                self.assertEqual(reply_at(clock), gates.CRON_SILENT)

    def test_the_python_fallback_matches_the_backend_defaults(self) -> None:
        """Two copies of the same quiet hours, in different languages."""
        model = (
            Path(__file__).resolve().parent.parent / "convex" / "model.ts"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'DEFAULT_QUIET_HOURS_START = "{gates.DEFAULT_QUIET_HOURS_START}"', model
        )
        self.assertIn(
            f'DEFAULT_QUIET_HOURS_END = "{gates.DEFAULT_QUIET_HOURS_END}"', model
        )

    def test_an_allowed_reminder_goes_out_unchanged(self) -> None:
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            with patch.object(
                gates,
                "_convex_request",
                return_value={"success": True, "allowed": True, "reason": "ok"},
            ):
                self.assertIsNone(
                    _transform_live_response(
                        platform="cron",
                        session_id=self.SESSION,
                        response_text="coq10 time 💊",
                    )
                )

    def test_a_cleared_reminder_still_cannot_make_a_false_claim(self) -> None:
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            with patch.object(
                gates,
                "_convex_request",
                return_value={"success": True, "allowed": True, "reason": "ok"},
            ):
                self.assertEqual(
                    _transform_live_response(
                        platform="cron",
                        session_id=self.SESSION,
                        response_text="i've saved that to your log.",
                    ),
                    gates.CLAIM_NOT_DONE,
                )

    def test_a_cleared_reminder_still_cannot_hand_out_calorie_numbers(self) -> None:
        with self.jobs_file({"platform": "whatsapp", "chat_id": self.CHAT}):
            with patch.object(
                gates,
                "_convex_request",
                return_value={"success": True, "allowed": True, "reason": "ok"},
            ):
                reply = _transform_live_response(
                    platform="cron",
                    session_id=self.SESSION,
                    response_text="reminder: stick to 1,200 calories today.",
                )
        # Dropped outright: a one-line ping has no conversation behind it, so
        # nothing here can prove the recipient is an adult.
        self.assertEqual(reply, gates.CRON_SILENT)

    def test_a_non_whatsapp_platform_is_still_ignored(self) -> None:
        self.assertIsNone(
            _transform_live_response(
                platform="telegram", session_id="x", response_text="hi"
            )
        )


class CronRecipientFromDeliverTest(unittest.TestCase):
    """The evening review names its recipient in `deliver`, not `origin`.

    A job created from a WhatsApp message carries `origin`, and every
    supplement reminder has one. The daily and weekly reviews do not — Ted
    makes them for a user key, `origin` is None, and the chat lives in
    `deliver` as "whatsapp:<chat id>". Reading only `origin` meant the review
    resolved to no recipient and went out with no voice card, which is the
    exact hole the cron branch of _capture_turn exists to close. Live on
    3 Sep: job c6d5c7b2cbf0, deliver whatsapp:144504426369026@lid, origin
    None.
    """

    CHAT = "144504426369026@lid"

    def test_origin_still_wins_when_it_is_there(self) -> None:
        self.assertEqual(
            gates._cron_job_chat_id(
                {
                    "origin": {"platform": "whatsapp", "chat_id": self.CHAT},
                    "deliver": "origin",
                }
            ),
            self.CHAT,
        )

    def test_the_review_resolves_through_deliver(self) -> None:
        self.assertEqual(
            gates._cron_job_chat_id(
                {"origin": None, "deliver": f"whatsapp:{self.CHAT}"}
            ),
            self.CHAT,
        )

    def test_the_first_whatsapp_entry_wins_in_a_list(self) -> None:
        self.assertEqual(
            gates._cron_job_chat_id(
                {"origin": None, "deliver": f"local,whatsapp:{self.CHAT}"}
            ),
            self.CHAT,
        )

    def test_what_is_not_a_recipient_stays_none(self) -> None:
        for job in (
            {"origin": None, "deliver": "local"},
            {"origin": None, "deliver": "origin"},
            {"origin": None, "deliver": ""},
            {"origin": None},
            {},
            # Another platform is not ours, by either route.
            {"origin": {"platform": "telegram", "chat_id": "123"}},
            {"origin": None, "deliver": "telegram:123"},
        ):
            with self.subTest(job=job):
                self.assertIsNone(gates._cron_job_chat_id(job))

    def test_an_unresolvable_recipient_still_gets_the_plain_card(self) -> None:
        """The broken owner job is a placeholder, not a user key.

        It must not raise and must not borrow somebody else's name — it
        hashes to a key with no record, so the nameless card is correct.
        """
        card = gates._voice_card(
            gates._user_state_key("whatsapp", "owner@s.whatsapp.net", "sess")
        )
        self.assertEqual(card, gates.VOICE_CARD)
        self.assertNotIn("You are talking to", card)

class ConvexCompatibilityCheckTest(unittest.TestCase):
    """The checker that stops a restart onto a Convex that cannot answer.

    Green matters as much as red here: a checker that only ever fails gets
    ignored, and one that passes wrongly is worse than none.
    """

    @staticmethod
    def checker():
        import importlib.util

        path = Path(__file__).resolve().parent.parent / "scripts" / "ted-convex-check.py"
        spec = importlib.util.spec_from_file_location("ted_convex_check", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_check(self, responder) -> tuple[list[str], bool]:
        module = self.checker()

        class Stub:
            host = "test-deployment"

            def call(self_inner, payload):
                return 200, responder(payload)

        return module.check(Stub())

    @staticmethod
    def healthy(payload):
        action = payload["action"]
        if action == "capabilities":
            return {"success": True, "actions": sorted(gates.REQUIRED_CONVEX_ACTIONS)}
        if action == "reports":
            return {"success": True, "reports": []}
        if action in ("log", "report"):
            return {"error": "Uncaught Error: localDate must be YYYY-MM-DD"}
        if action == "reminderGate":
            return {"error": "Uncaught Error: nowLocalTime must be a 24-hour HH:MM"}
        return {"success": True}

    def test_a_matching_deployment_passes(self) -> None:
        report, broken = self.run_check(self.healthy)
        self.assertFalse(broken, "\n".join(report))
        self.assertTrue(all(line.startswith("  ok") for line in report), report)

    def test_the_exact_failure_of_2_sep_is_caught(self) -> None:
        """Production accepted 'log' but rejected the gate's new arguments."""

        def responder(payload):
            if payload["action"] == "log":
                return {
                    "error": "ArgumentValidationError: Object contains extra field "
                    "`dateConfirmed` that is not in the validator."
                }
            return self.healthy(payload)

        report, broken = self.run_check(responder)
        self.assertTrue(broken)
        joined = "\n".join(report)
        self.assertIn("dateConfirmed", joined)
        self.assertIn("logging would break on restart", joined)

    def test_a_missing_action_is_named(self) -> None:
        def responder(payload):
            if payload["action"] == "capabilities":
                return {
                    "success": True,
                    "actions": sorted(gates.REQUIRED_CONVEX_ACTIONS - {"reminderGate"}),
                }
            return self.healthy(payload)

        report, broken = self.run_check(responder)
        self.assertTrue(broken)
        self.assertIn("reminderGate", "\n".join(report))

    def test_an_old_deployment_still_gets_a_specific_report(self) -> None:
        """No capabilities endpoint must not stop it naming the real gaps."""

        def responder(payload):
            if payload["action"] in ("capabilities", "reminderGate", "report", "reports"):
                return {"error": "Unsupported action"}
            return self.healthy(payload)

        report, broken = self.run_check(responder)
        self.assertTrue(broken)
        joined = "\n".join(report)
        for expected in ("reminderGate", "report", "reports"):
            self.assertIn(expected, joined)

    def test_a_backend_ahead_of_the_gate_is_not_a_failure(self) -> None:
        """Deploying Convex first is the safe order and must stay green."""

        def responder(payload):
            if payload["action"] == "capabilities":
                return {
                    "success": True,
                    "actions": sorted(gates.REQUIRED_CONVEX_ACTIONS | {"somethingNew"}),
                }
            return self.healthy(payload)

        report, broken = self.run_check(responder)
        self.assertFalse(broken, "\n".join(report))
        self.assertIn("somethingNew", "\n".join(report))

    def test_the_gate_and_the_backend_declare_the_same_actions(self) -> None:
        """The two lists are edited in different files and must not drift."""
        import re

        model = (
            Path(__file__).resolve().parent.parent / "convex" / "model.ts"
        ).read_text(encoding="utf-8")
        block = model.split("TED_HTTP_ACTIONS = [")[1].split("]")[0]
        self.assertEqual(
            set(re.findall(r'"(\w+)"', block)),
            set(gates.REQUIRED_CONVEX_ACTIONS),
        )


class RoughInputTest(unittest.TestCase):
    """Order 13: names and messages that are not the happy path."""

    def _fresh_key(self, name: str) -> str:
        key = f"rough-input-{name}"
        gates._DISCLOSURE_SENT_KEYS.discard(key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(key, None)
        return key

    def test_a_trailing_emoji_is_not_part_of_the_name(self) -> None:
        self.assertEqual(gates._clean_name("call me Vandy \U0001f604"), "Vandy")
        self.assertEqual(gates._clean_name("I'm Vandy \U0001fae1\U0001f642"), "Vandy")
        self.assertEqual(gates._clean_name("\U0001f604 Vandy"), "Vandy")

    def test_an_emoji_only_name_is_refused_rather_than_stored(self) -> None:
        for text in ("\U0001fae1", "\U0001f604\U0001f642", "   \U0001fae1   "):
            with self.subTest(text=text):
                self.assertIsNone(gates._clean_name(text))

    def test_a_name_too_long_is_refused_rather_than_truncated(self) -> None:
        long_name = "Vandana " * 40
        self.assertIsNone(gates._clean_name(long_name))
        # The old parser kept the first 40 characters, mid-word, silently.
        self.assertNotEqual(gates._clean_name(long_name), long_name.strip()[:40])

    def test_an_ordinary_name_still_survives(self) -> None:
        self.assertEqual(gates._clean_name("call me Vandy"), "Vandy")
        self.assertEqual(gates._clean_name("my name is Vandana Agarwal"), "Vandana Agarwal")
        self.assertEqual(gates._clean_name("\u0935\u0902\u0926\u0928\u093e"), "\u0935\u0902\u0926\u0928\u093e")

    def test_an_emoji_only_answer_makes_the_gate_ask_again(self) -> None:
        user_key = self._fresh_key("emoji-name")
        history = [
            message("assistant", "What should I call you?"),
            message("user", "\U0001fae1"),
        ]
        reply = consent_gate(history, "nice to meet you", user_key)
        self.assertEqual(reply, "What should I call you?")

    def test_the_prepared_message_sent_twice_is_acknowledged(self) -> None:
        user_key = self._fresh_key("double-press")
        history = [
            message("user", "Okay Ted, let's do this \U0001fae1"),
            message("assistant", OPENING_MESSAGE),
        ]
        self.assertEqual(
            transform_response(
                history=history,
                user_message="Okay Ted, let's do this \U0001fae1",
                response_text="hey again!",
                user_key=user_key,
            ),
            gates.ALREADY_STARTED_MESSAGE,
        )

    def test_an_empty_message_during_onboarding_asks_for_the_name(self) -> None:
        user_key = self._fresh_key("empty-onboarding")
        history = [message("assistant", "What should I call you?")]
        self.assertEqual(
            transform_response(
                history=history,
                user_message="   ",
                response_text="",
                user_key=user_key,
            ),
            gates.NAME_NOT_USABLE_MESSAGE,
        )

    def test_a_media_only_message_after_onboarding_is_left_alone(self) -> None:
        """A meal photo is the product. Only the name question intercepts it."""
        user_key = self._fresh_key("media-after")
        history = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
            message("assistant", gates._personalized_disclosure("Vandy")),
            message("user", "routine"),
        ]
        reply = transform_response(
            history=history,
            user_message="",
            response_text="that looks like about 500 kcal",
            user_key=user_key,
            action_succeeded=True,
        )
        self.assertNotEqual(reply, gates.NAME_NOT_USABLE_MESSAGE)


class GoalQuestionDeliveryTest(unittest.TestCase):
    """Order 08: the goal question cannot be lost, because it is not a send."""

    def test_a_restart_between_the_two_sends_cannot_lose_it(self) -> None:
        user_key = "goal-question-restart"
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(user_key, None)
        history = [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]
        delivered = consent_gate(history, "anything at all", user_key)
        # One message carries the notice and question one, so there is no
        # window in which the disclosure has landed and the next step is
        # still owed by a thread that may not run.
        self.assertIn(gates.PRIVACY_URL, delivered)
        self.assertIn(gates._setup_question(0), delivered)
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)


class GoldenPathTest(unittest.TestCase):
    """Order 14(2): the whole V1 conversation, replayed through the live gates."""

    def setUp(self) -> None:
        self.user_key = "golden-path-e2e"
        gates._DISCLOSURE_SENT_KEYS.discard(self.user_key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(self.user_key, None)
        self.history: list[dict[str, str]] = []
        self.visible: list[str] = []

    def tearDown(self) -> None:
        gates._DISCLOSURE_SENT_KEYS.discard(self.user_key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(self.user_key, None)

    def turn(self, user_text: str, model_reply: str, **kwargs: object) -> str:
        """One WhatsApp round trip. Returns what the user actually sees."""
        self.history.append(message("user", user_text))
        gated = transform_response(
            history=list(self.history),
            user_message=user_text,
            response_text=model_reply,
            user_key=self.user_key,
            **kwargs,
        )
        reply = model_reply if gated is None else gated
        self.history.append(message("assistant", reply))
        self.visible.append(reply)
        return reply

    def test_the_whole_conversation_end_to_end(self) -> None:
        # 1. The prepared start message. Ted's opener replaces whatever the
        #    model wrote, so the promise and the name question are exact.
        self.assertEqual(
            self.turn("Okay Ted, let's do this \U0001fae1", "hey, and you are?"),
            OPENING_MESSAGE,
        )

        # 2. The name. Notice, why, and question one arrive as ONE message.
        disclosure = self.turn("Vandy", "nice to meet you")
        self.assertEqual(disclosure, VANDY_DISCLOSURE)
        self.assertIn(gates.PRIVACY_URL, disclosure)
        self.assertIn(gates._setup_question(0), disclosure)
        # The open goal question is not here any more. It comes after the
        # number, where it follows from something.
        self.assertNotIn(GOAL_QUESTION, disclosure)

        # 3. The counted five. Question one came inside the disclosure, so
        #    four answers walk the rest of the count. The model is writing
        #    something else every turn and none of it goes out: while the five
        #    are running, the count is Ted's, not the model's.
        for answer, expected in (
            ("33", gates._setup_question(1)),
            ("170cm", gates._setup_question(2)),
            ("62kg", gates._setup_question(3)),
            ("female", gates._setup_question(4)),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(self.turn(answer, "noted!"), expected)

        # 4. All five in, and the read-back comes before the number. This is
        #    the step that would have caught Pallavi's height.
        self.turn("desk most of the day", "great, here's your target")
        summary = self.turn("lose fat", "noted")
        self.assertIn("here's what i've got:", summary)
        self.assertIn("33", summary)
        self.assertIn("170 cm", summary)
        self.assertIn("62 kg", summary)
        # Not a single calorie number until she has agreed to the inputs.
        self.assertNotIn("1,630", summary)

        # 5. She agrees, and the number lands — maintenance, never a cut, and
        #    the goal question follows it now rather than preceding it.
        payoff = self.turn("yep", "here you go")
        self.assertIn("all six", payoff)
        self.assertIn("1,630", payoff)
        self.assertIn("maintenance", payoff)
        # The goal is question 6/6 now, so it is answered before here. The
        # payoff speaks to it and offers a bounded target to choose between.
        self.assertNotIn(GOAL_QUESTION, payoff)
        self.assertIn("to lose", payoff)
        # A named cut, and it is never below resting energy or the floor.
        profile = gates.CalorieProfile(
            age=33, height_cm=170, weight_kg=62, sex="female",
            activity="sedentary", goal="loseWeight",
        )
        target = gates._loss_target(profile)
        self.assertIn(f"{target:,}", payoff)
        self.assertGreaterEqual(target, gates._resting_energy(profile))
        self.assertGreaterEqual(target, gates._LOSS_FLOOR_KCAL["female"])
        self.assertLess(target, gates._estimated_maintenance(profile))
        self.assertEqual(gates._setup_state(self.user_key), "done")

        # 6. The goal, then the check-in time. Ted's own words survive again
        #    now that the five are done — except for the check-in time itself,
        #    which the gate owns end to end. The model reaching for it in its
        #    own words gets the gate's words instead, once, and the gate reads
        #    the answer rather than trusting the model to record it. This is
        #    what stopped the question going out twice on 4 Sep.
        self.assertEqual(self.turn("eat more protein", "good one, noted."), "good one, noted.")
        asked = self.turn("when do you check in?", "good one. what time should i check in?")
        self.assertEqual(asked, gates.REVIEW_TIME_QUESTION)
        self.assertEqual(gates._review_state(self.user_key), "asking")

        # The answer is read here, not by the model, so a model that forgets to
        # save it cannot make the question come back. Storage has to answer for
        # the step to close: a recorded step with no reminder row behind it is
        # the exact failure the close gate exists to prevent.
        with patch.object(gates, "_convex_request", return_value={"success": True}):
            settled = self.turn("8pm", "locked.")
        self.assertIn("8pm", settled)
        self.assertIn("dailyReview", set(gates._onboarding(self.user_key).get("done") or ()))
        self.assertEqual(gates._review_state(self.user_key), "done")

        # And it is asked once. A sign-off now closes cleanly instead of being
        # replaced by the question a second time.
        self.assertNotEqual(
            self.turn("great", "you're all set."), gates.REVIEW_TIME_QUESTION
        )

        # 4. First meal by text, with the log tool actually succeeding. A
        #    per-food estimate is not a target, so the numbers go out intact.
        meal = self.turn(
            "3 rotis and dal for lunch",
            "roughly 480 calories, 18g protein.",
            action_succeeded=True,
        )
        self.assertEqual(meal, "roughly 480 calories, 18g protein.")

        # 5. A correction. The recalculated numbers must survive the claim gate.
        correction = self.turn(
            "actually it was 2 rotis",
            "updated — that's about 380 calories, 15g protein now.",
            action_succeeded=True,
        )
        self.assertIn("380", correction)
        self.assertIn("15g protein", correction)

        # 6. "how am I doing today?" — today's totals reach the user whole.
        totals = self.turn(
            "how am i doing today?",
            "2 meals logged, water done, steps short by 2k.",
        )
        self.assertEqual(totals, "2 meals logged, water done, steps short by 2k.")
        self.assertIn("2 meals logged", totals)

        # 7. The evening review keeps its counts.
        review = self.turn(
            "wrap up my day",
            "3 meals logged, water done, walk done. tomorrow: protein at breakfast.",
        )
        self.assertIn("3 meals logged", review)
        self.assertIn("tomorrow: protein at breakfast", review)

        # 8. "delete my data" — the model claiming it is done, with no tool
        #    behind it, still never reaches the user. It used to be replaced
        #    with the generic "I haven't completed that action"; the gate now
        #    asks the confirmation question itself, which blocks the same
        #    false claim and moves the erasure forward instead of stalling it.
        refused = self.turn("delete my data", "Done, everything has been deleted.")
        self.assertEqual(refused, gates.DELETE_CONFIRMATION_QUESTION)
        self.assertNotIn("has been deleted", refused)

        # 9. Confirmed, with the delete tool proven this turn. Only now does a
        #    deletion confirmation reach the user.
        confirmed = self.turn(
            "yes",
            "Done, everything has been deleted.",
            successful_actions={"delete"},
        )
        self.assertEqual(confirmed, "Done, everything has been deleted.")

        # The name is asked exactly once across the whole conversation.
        self.assertEqual(
            sum(gates._asks_for_name(reply) for reply in self.visible), 1
        )
        # And the disclosure went out exactly once.
        self.assertEqual(
            sum(gates.PRIVACY_URL in reply for reply in self.visible), 1
        )


class LoadBearingSafetyTest(unittest.TestCase):
    """Order 14(3): the two rules that must survive every change above."""

    ADULT = [
        message("assistant", "how old are you?"),
        message("user", "33"),
        message("assistant", "how tall are you?"),
        message("user", "170"),
        message("assistant", "and your weight?"),
        message("user", "62"),
        message("assistant", "are you male or female?"),
        message("user", "female"),
        message("assistant", "how active are you?"),
        message("user", "sedentary"),
    ]
    MINOR = [message("assistant", "how old are you?"), message("user", "15")]

    def test_a_minor_gets_no_calorie_number_however_it_is_phrased(self) -> None:
        """The refusal must not depend on recognising the model's wording.

        Every phrasing below reached a user the gate already knew was 15,
        because the under-18 check sat behind a regex over the model's prose.
        """
        for reply in (
            "that's about 500 kcal",
            "that's about 500 calories",
            "that's about 500 cals",
            "that's about 500 cal",
            "roughly 1.6k a day",
            "about sixteen hundred a day",
            "that's around 2,000 for the day",
            "call it 500 for that plate",
            "you're looking at ~1800 a day",
            "your maintenance is 1630",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    calorie_gate(self.MINOR, "what's in this?", reply),
                    gates.UNDER_18_REFUSAL,
                )

    def test_ordinary_encouragement_to_a_minor_is_not_mangled(self) -> None:
        """The widened check must not turn every reply into a refusal."""
        for reply in ("nice work today, keep it up", "sounds good, see you tomorrow"):
            with self.subTest(reply=reply):
                self.assertIsNone(calorie_gate(self.MINOR, "hey", reply))

    def test_no_path_returns_a_target_below_maintenance(self) -> None:
        for ask in (
            "what should my calorie target be to lose weight?",
            "put me on a 500 calorie deficit",
            "i want to lose 5kg fast, what's my target?",
        ):
            with self.subTest(ask=ask):
                reply = calorie_gate(
                    self.ADULT, ask, "you should eat 1200 calories a day"
                )
                self.assertIsNotNone(reply)
                self.assertNotIn("1200", reply or "")
                self.assertIn("1,630", reply or "")
                self.assertIn("maintenance", reply or "")

    def test_the_mifflin_st_jeor_result_is_unchanged(self) -> None:
        """33 F, 170 cm, 62 kg, sedentary -> 1,630 kcal. Verified in the audit."""
        self.assertEqual(
            gates._estimated_maintenance(
                gates.CalorieProfile(
                    age=33,
                    height_cm=170,
                    weight_kg=62,
                    sex="female",
                    activity="sedentary",
                )
            ),
            1630,
        )


class ProseMatchingHardeningTest(unittest.TestCase):
    """The order 14 point 4 findings, fixed rather than only listed."""

    def test_the_model_mentioning_the_privacy_link_is_not_consent(self) -> None:
        """A helpful link is not a disclosure, and used to read as one."""
        volunteered = [
            message(
                "assistant",
                f"sure — you can read the privacy policy at {gates.PRIVACY_URL} anytime",
            )
        ]
        self.assertFalse(gates._disclosure_was_sent(volunteered))
        real = [message("assistant", gates._personalized_disclosure("Vandy"))]
        self.assertTrue(gates._disclosure_was_sent(real))

    def test_the_disclosure_still_goes_out_after_a_volunteered_link(self) -> None:
        user_key = "volunteered-link"
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        try:
            history = [
                message("assistant", "What should I call you?"),
                message("user", "Vandy"),
                message("assistant", f"btw our policy is at {gates.PRIVACY_URL}"),
            ]
            reply = consent_gate(history, "nice to meet you", user_key)
            self.assertIn(gates.DISCLOSURE_MESSAGE, reply or "")
            self.assertIn("1/6", reply or "")
        finally:
            gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_recorded_state_beats_the_transcript(self) -> None:
        """_log_disclosure writes this only after a real send."""
        user_key = "recorded-beats-transcript"
        gates._DISCLOSURE_SENT_KEYS.discard(user_key)
        try:
            self.assertFalse(gates._disclosure_was_sent([], user_key))
            gates._DISCLOSURE_SENT_KEYS.add(user_key)
            self.assertTrue(gates._disclosure_was_sent([], user_key))
        finally:
            gates._DISCLOSURE_SENT_KEYS.discard(user_key)

    def test_the_claims_that_used_to_slip_are_caught(self) -> None:
        for reply in (
            "Done \u2713",
            "Sorted \u2705",
            "consider it logged",
            "consider it in your log",
            "that's in the system now",
            "your log is up to date",
            "I'll keep that in mind for 8pm",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(action_claim_gate(reply), gates.CLAIM_NOT_DONE)

    def test_descriptions_of_the_users_day_still_survive(self) -> None:
        """The widened patterns must not eat the sentences carrying numbers."""
        for reply in (
            "3 meals logged, water done, walk done. tomorrow: protein at breakfast.",
            "4 glasses recorded so far, 2 to go.",
            "your target was updated last week, so this is measured against it.",
            "2 workouts logged this week — same as last week.",
            "2 meals logged, water done, steps short by 2k.",
            "roughly 480 calories, 18g protein.",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(action_claim_gate(reply))

    def test_a_proven_tool_still_lets_the_claim_through(self) -> None:
        self.assertIsNone(
            action_claim_gate("Done \u2713", successful_actions={"memory"})
        )


class CronJobsFileShapeTest(unittest.TestCase):
    """The reader must handle the shape Hermes actually writes.

    `CronReminderGateTest` above writes its fixture as a bare list, which is a
    shape production never produces. Hermes writes
    ``{"jobs": [...], "updated_at": ...}``, and against that the old
    ``list(raw.values())`` yielded the job list and a timestamp string — never
    a job dict. Every lookup missed, `_cron_whatsapp_recipient` always returned
    None, and the whole milestone-12 cron gate was dead in production while
    these tests stayed green. This class pins the real shape.
    """

    SESSION = "cron_919661eba04c_20260903_084500"
    CHAT = "144504426369026@lid"
    JOB = {
        "id": "919661eba04c",
        "name": "CoQ10 reminder",
        "origin": {"platform": "whatsapp", "chat_id": CHAT},
    }

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "jobs.json"

    def written(self, payload: object) -> object:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return patch.object(gates, "_CRON_JOBS_PATH", self.path)

    def test_the_shape_hermes_actually_writes_resolves(self) -> None:
        wrapped = {"jobs": [self.JOB], "updated_at": "2026-09-02T23:57:11+05:30"}
        with self.written(wrapped):
            self.assertEqual(len(gates._load_cron_jobs()), 1)
            self.assertEqual(
                gates._cron_whatsapp_recipient(self.SESSION), self.CHAT
            )

    def test_a_bare_list_and_an_id_mapping_both_still_resolve(self) -> None:
        for payload in ([self.JOB], {self.JOB["id"]: self.JOB}):
            with self.subTest(shape=type(payload).__name__):
                with self.written(payload):
                    self.assertEqual(
                        gates._cron_whatsapp_recipient(self.SESSION), self.CHAT
                    )

    def test_a_missing_or_unreadable_file_is_not_a_crash(self) -> None:
        with patch.object(gates, "_CRON_JOBS_PATH", self.path / "nope.json"):
            self.assertEqual(gates._load_cron_jobs(), [])
        self.path.write_text("{not json", encoding="utf-8")
        with patch.object(gates, "_CRON_JOBS_PATH", self.path):
            self.assertEqual(gates._load_cron_jobs(), [])


class CronScopeTest(unittest.TestCase):
    """One beta user must never see or touch another's reminders.

    `cronjob` is a Hermes platform tool over a machine-wide store, so
    ``action='list'`` in any WhatsApp thread returned every job on the box. On
    2 Sep 2026 a tester's live thread was handed five of the builder's
    supplement reminders, doses included, along with job ids it could have
    removed.
    """

    NIK = "277391083601962@lid"
    VANDY = "144504426369026@lid"
    MINE = {
        "id": "mine01",
        "name": "Nik omega-3",
        "origin": {"platform": "whatsapp", "chat_id": NIK},
    }
    THEIRS = {
        "id": "theirs01",
        "name": "CoQ10 reminder",
        "origin": {"platform": "whatsapp", "chat_id": VANDY},
    }

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = Path(self._dir.name) / "jobs.json"
        path.write_text(
            json.dumps({"jobs": [self.MINE, self.THEIRS]}), encoding="utf-8"
        )
        patcher = patch.object(gates, "_CRON_JOBS_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT["nik"] = {"chat_id": self.NIK}
        self.addCleanup(
            lambda: gates._TURN_CONTEXT.pop("nik", None)
        )

    def guard(self, session: str, **args: object) -> object:
        return gates._cron_scope_guard(
            tool_name="cronjob", session_id=session, args=args
        )

    def listing(self, session: str) -> object:
        result = json.dumps(
            {
                "success": True,
                "count": 2,
                "jobs": [
                    {"job_id": "mine01", "name": "Nik omega-3"},
                    {"job_id": "theirs01", "prompt_preview": "Send Vandy a..."},
                ],
            }
        )
        return gates._filter_cron_listing(
            tool_name="cronjob",
            session_id=session,
            args={"action": "list"},
            result=result,
        )

    def test_another_chats_jobs_are_stripped_from_a_listing(self) -> None:
        payload = json.loads(self.listing("nik"))
        self.assertEqual(payload["count"], 1)
        self.assertEqual([j["job_id"] for j in payload["jobs"]], ["mine01"])
        self.assertNotIn("Vandy", json.dumps(payload))

    def test_acting_on_another_chats_job_is_blocked(self) -> None:
        for action in ("remove", "update", "pause", "resume", "run"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.guard("nik", action=action, job_id="theirs01"),
                    {"action": "block", "message": gates.CRON_NOT_YOURS},
                )

    def test_a_job_can_also_be_named_rather_than_addressed_by_id(self) -> None:
        self.assertEqual(
            self.guard("nik", action="remove", job_id="CoQ10 reminder"),
            {"action": "block", "message": gates.CRON_NOT_YOURS},
        )

    def test_the_users_own_reminders_still_work(self) -> None:
        self.assertIsNone(self.guard("nik", action="remove", job_id="mine01"))
        self.assertIsNone(self.guard("nik", action="create", schedule="5m"))
        self.assertIsNone(self.guard("nik", action="create", deliver="origin"))
        self.assertIsNone(self.guard("nik", action="list"))

    def test_delivery_to_another_surface_is_blocked(self) -> None:
        for deliver in ("all", "origin,all", "telegram:-1001234567890", "sms:+15551234567"):
            with self.subTest(deliver=deliver):
                self.assertEqual(
                    self.guard("nik", action="create", deliver=deliver),
                    {"action": "block", "message": gates.CRON_DELIVER_ELSEWHERE},
                )

    def test_a_session_with_no_whatsapp_turn_is_left_alone(self) -> None:
        """The builder at a terminal keeps full access to every job."""
        self.assertIsNone(self.guard("cli", action="remove", job_id="theirs01"))
        self.assertIsNone(self.listing("cli"))

    def test_a_non_cron_tool_is_never_touched(self) -> None:
        self.assertIsNone(
            gates._cron_scope_guard(
                tool_name="ted_log_entry", session_id="nik", args={"action": "remove"}
            )
        )


class MinorFlagDurabilityTest(unittest.TestCase):
    """The under-18 block must outlive the conversation it was stated in.

    On 2 Sep 2026 the refusal fired correctly the moment a tester typed
    "I am 15" — but the age was read only out of conversation history. Hermes
    compresses at 50% of the window and protects only the last 20 messages, so
    that turn is compacted away inside the *same* conversation after enough
    messages, and the protection would have stopped firing with nothing said.
    """

    KEY = "whatsapp:sha256:minor-test"
    ADULT = "whatsapp:sha256:adult-test"
    LEAK = "today so far: 1 sandwich + pasta salad, 800 kcal total, 45g protein."

    def setUp(self) -> None:
        self.addCleanup(reset_user, self.KEY)
        self.addCleanup(reset_user, self.ADULT)

    def gate(self, history: list, message: str, reply: str, key: str = "") -> object:
        return gates.calorie_gate(history, message, reply, key or self.KEY)

    def test_the_age_is_recorded_the_moment_it_is_stated(self) -> None:
        self.gate([], "I am 15", "15, noted. what hour works?")
        self.assertTrue(gates._is_known_minor(self.KEY))

    def test_the_refusal_survives_the_turn_being_compacted_away(self) -> None:
        """The whole point: empty history, and the block still holds."""
        self.gate([], "I am 15", "15, noted.")
        self.assertEqual(self.gate([], "check my meal", self.LEAK), gates.UNDER_18_REFUSAL)

    def test_a_later_higher_age_does_not_lift_the_block(self) -> None:
        self.gate([], "I am 15", "15, noted.")
        for message in ("actually I'm 30", "I'm 25 now", "I meant 21"):
            with self.subTest(message=message):
                self.assertEqual(
                    self.gate([], message, self.LEAK), gates.UNDER_18_REFUSAL
                )
        self.assertTrue(gates._is_known_minor(self.KEY))

    def test_a_target_request_from_a_known_minor_is_still_refused(self) -> None:
        self.gate([], "I am 15", "15, noted.")
        self.assertEqual(
            self.gate([], "what's my calorie target?", "maintenance is 2100 calories"),
            gates.UNDER_18_REFUSAL,
        )

    def test_deleting_your_data_really_does_clear_it(self) -> None:
        """Erasure has to be honest, so the flag goes with everything else."""
        self.gate([], "I am 15", "15, noted.")
        gates._forget_user(self.KEY)
        self.assertFalse(gates._is_known_minor(self.KEY))
        self.assertIsNone(self.gate([], "check my meal", self.LEAK))

    def test_an_adult_is_untouched_and_stops_being_re_asked(self) -> None:
        self.gate([], "I'm 33", "got it")
        self.assertEqual(gates._stored_age(self.KEY), 33)
        self.assertFalse(gates._is_known_minor(self.KEY))
        # A per-meal estimate was never gated for an adult and still is not.
        self.assertIsNone(self.gate([], "check my meal", self.LEAK))

    def test_a_restored_age_answers_the_target_flow_without_re_asking(self) -> None:
        """An adult age that scrolled out of the window must not reset the flow."""
        self.gate([], "I'm 33", "got it")
        reply = self.gate([], "what's my maintenance?", "your maintenance is 2100 calories")
        self.assertNotEqual(reply, gates.AGE_QUESTION)

    def test_no_user_key_behaves_exactly_as_before(self) -> None:
        """CLI and test call sites pass no key and must not start storing one."""
        self.assertEqual(
            gates.calorie_gate([], "I am 15", self.LEAK), gates.UNDER_18_REFUSAL
        )
        self.assertIsNone(gates.calorie_gate([], "check my meal", self.LEAK))


if __name__ == "__main__":
    unittest.main()


class UnreadableDocumentTest(unittest.TestCase):
    """A PDF Ted cannot read must be said out loud, not guessed at.

    Hermes inlines a text document's content into the user turn. A binary one
    it cannot inline, so it prepends a note telling the agent to "extract the
    document's text yourself — for example with the terminal tool or the
    ocr-and-documents skill". Ted's WhatsApp toolset is cronjob / file / ted /
    vision: it has neither. The one tool it does have, `file`, will happily
    return a PDF's raw stream decoded as text, because `.pdf` is deliberately
    absent from Hermes' BINARY_EXTENSIONS. A health plan that reads as rubbish
    but not obviously so is exactly how invented calorie targets get born.
    """

    KEY = "whatsapp:sha256:pdf-test"

    # Verbatim from gateway/run.py `_build_document_context_note`.
    PDF_NOTE = (
        "[The user sent a document: 'diet-plan.pdf'. It is saved at: "
        "/Users/x/.hermes/document_cache/doc_ab12_diet-plan.pdf. Its text is "
        "not inlined here (it's a binary format such as PDF or DOCX). To read "
        "it, extract the document's text yourself — for example with the "
        "terminal tool or the ocr-and-documents skill — before answering, "
        "instead of asking the user to paste the contents.]"
    )
    TEXT_NOTE = (
        "[The user sent a text document: 'notes.md'. Its content has been "
        "included below. The file is also saved at: /tmp/doc_cd34_notes.md]"
    )

    def setUp(self) -> None:
        self.addCleanup(reset_user, self.KEY)
        self.history = [message("assistant", DISCLOSURE_MESSAGE)]

    def transform(self, user_message: str, reply: str) -> object:
        return gates.transform_response(
            history=self.history,
            user_message=user_message,
            response_text=reply,
            user_key=self.KEY,
        )

    def test_a_pdf_gets_the_honest_answer(self) -> None:
        self.assertEqual(
            self.transform(self.PDF_NOTE, "Great plan! I've set your targets."),
            gates.UNREADABLE_DOCUMENT_REPLY,
        )

    def test_it_beats_the_calorie_gate_to_the_reply(self) -> None:
        """An unread plan must never reach the maintenance calculation."""
        reply = "your plan says 1,800 calories a day, so that's your target now."
        self.assertEqual(
            self.transform(f"{self.PDF_NOTE}\n\nhere's my plan", reply),
            gates.UNREADABLE_DOCUMENT_REPLY,
        )

    def test_a_docx_is_the_same_note_and_the_same_answer(self) -> None:
        note = self.PDF_NOTE.replace("diet-plan.pdf", "plan.docx")
        self.assertEqual(
            self.transform(note, "Loaded it."), gates.UNREADABLE_DOCUMENT_REPLY
        )

    def test_a_text_document_is_left_alone(self) -> None:
        """Hermes inlines these, so Ted really can read them."""
        self.assertIsNone(gates.unreadable_document_gate(self.TEXT_NOTE))

    def test_an_ordinary_message_is_left_alone(self) -> None:
        for text in (
            "had 2 rotis and dahi",
            "can you read a pdf?",
            "i'll send my plan as a document later",
            "",
        ):
            with self.subTest(text=text):
                self.assertIsNone(gates.unreadable_document_gate(text))

    def test_the_reply_names_what_to_do_instead(self) -> None:
        reply = gates.UNREADABLE_DOCUMENT_REPLY.lower()
        self.assertIn("screenshot", reply)
        self.assertIn("type", reply)
        # It must not claim to have read anything.
        for verb in ("saved", "logged", "set your", "i've read"):
            self.assertNotIn(verb, reply)


class BreakOfferTest(unittest.TestCase):
    """Four nudges into silence, Ted asks instead of sending a fifth.

    The failure this exists to prevent is the one that quietly kills these
    products. A user drifts off, the reminders keep arriving exactly on
    schedule, and the thread becomes something to mute. Muting is invisible to
    Ted and it is not reversible, so the only chance to keep the relationship
    is before it happens.
    """

    SESSION = "cron_000000000000_20260903_084500"
    CHAT = "000000000000000@lid"
    SENDER = "919999999999@s.whatsapp.net"

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)

    def jobs_file(self) -> object:
        path = Path(self.tmp) / "jobs.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "000000000000",
                        "name": "protein reminder",
                        "origin": {"platform": "whatsapp", "chat_id": self.CHAT},
                    }
                ]
            ),
            encoding="utf-8",
        )
        return patch.object(gates, "_CRON_JOBS_PATH", path)

    def gate(self, gate_reply: dict, response_text: str = "protein shake time"):
        def responder(action, user_key, context_id="", body=None, **_):
            if action == "reminderGate":
                return gate_reply
            return {"success": True}

        with self.jobs_file(), patch.object(
            gates, "_convex_request", side_effect=responder
        ):
            return gates._cron_reminder_gate(
                session_id=self.SESSION, response_text=response_text
            )

    def test_an_ordinary_nudge_is_left_alone(self) -> None:
        self.assertIsNone(self.gate({"success": True, "allowed": True, "reason": "ok"}))

    def test_the_fifth_nudge_becomes_the_question(self) -> None:
        reply = self.gate(
            {"success": True, "allowed": True, "reason": "ok", "offerBreak": True}
        )
        self.assertEqual(reply, gates.BREAK_OFFER)

    def test_the_offer_replaces_the_nudge_rather_than_joining_it(self) -> None:
        """A nudge plus a question is two messages. It has to be one."""
        reply = self.gate(
            {"success": True, "allowed": True, "reason": "ok", "offerBreak": True},
            response_text="time for your protein shake",
        )
        self.assertNotIn("protein shake", reply)

    def test_silence_after_the_offer_stays_silent(self) -> None:
        reply = self.gate(
            {"success": True, "allowed": False, "reason": "awaitingReply"}
        )
        self.assertEqual(reply, gates.CRON_SILENT)

    def test_the_offer_names_the_way_out(self) -> None:
        offer = gates.BREAK_OFFER.lower()
        self.assertIn("pause", offer)
        self.assertIn("?", offer)
        # It is a question, not a nudge, and not a guilt trip.
        for word in ("should", "need to", "failing", "disappointed"):
            self.assertNotIn(word, offer)

    def test_a_storage_outage_does_not_invent_a_break_offer(self) -> None:
        """The count lives in the row we could not read, so do not guess."""
        with patch.object(gates.time, "strftime", return_value="09:00"):
            allowed, reason, offer = gates._reminder_allowed("whatsapp:sha256:x")
        self.assertFalse(offer)


class NudgeCountResetTest(unittest.TestCase):
    """Any message resets the count. Not a particular answer, any message."""

    KEY = "whatsapp:sha256:reset-test"

    def test_an_engaged_user_costs_no_write(self) -> None:
        with patch.object(gates, "_convex_request") as req:
            gates._note_user_replied(
                self.KEY, {"unansweredNudges": 0, "awaitingBreakReply": False}
            )
        req.assert_not_called()

    def test_a_missed_nudge_is_cleared(self) -> None:
        with patch.object(
            gates, "_convex_request", return_value={"success": True, "changed": True}
        ) as req:
            gates._note_user_replied(self.KEY, {"unansweredNudges": 2})
        self.assertEqual(req.call_args.args[0], "replied")

    def test_an_unanswered_break_offer_is_cleared_by_anything_at_all(self) -> None:
        with patch.object(
            gates, "_convex_request", return_value={"success": True}
        ) as req:
            gates._note_user_replied(self.KEY, {"awaitingBreakReply": True})
        self.assertEqual(req.call_args.args[0], "replied")

    def test_a_failed_reset_is_silent(self) -> None:
        """Worst case the count clears on the next message. Never fail a turn."""
        with patch.object(
            gates, "_convex_request", return_value={"success": False, "error": "down"}
        ):
            gates._note_user_replied(self.KEY, {"unansweredNudges": 3})

    def test_no_user_key_does_nothing(self) -> None:
        with patch.object(gates, "_convex_request") as req:
            gates._note_user_replied("", {"unansweredNudges": 3})
        req.assert_not_called()


class UserTimeZoneTest(unittest.TestCase):
    """Every date Ted writes belongs to the user's calendar, not the laptop's.

    `users.timeZone` was collected at onboarding, written to Convex, and read by
    nothing: every date came from `time.strftime` on the machine running the
    gateway. In a Bangalore-only beta that is invisible. For anyone else a late
    meal files to the wrong day and quiet hours are wrong by their whole offset,
    which is PRODUCT_BUILD_GUARDRAILS §4 word for word.
    """

    # 19:30 UTC. Already tomorrow in Kolkata, still lunchtime in Los Angeles.
    FIXED = datetime(2026, 9, 3, 19, 30, tzinfo=dt_timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 9, 3, 19, 30, tzinfo=dt_timezone.utc)
            return fixed.astimezone(tz) if tz else fixed

    def setUp(self) -> None:
        gates._MEMORY_CACHE.clear()
        self.addCleanup(gates._MEMORY_CACHE.clear)

    def zoned(self, name):
        """Run with a user whose stored timezone is `name`."""
        return patch.multiple(
            gates,
            datetime=self._Frozen,
            _cached_user_memory=lambda _key: {"facts": [], "timeZone": name},
        )

    def test_the_same_instant_is_a_different_day_in_two_places(self) -> None:
        with self.zoned("Asia/Kolkata"):
            self.assertEqual(gates._today("u"), "2026-09-04")
        with self.zoned("America/Los_Angeles"):
            self.assertEqual(gates._today("u"), "2026-09-03")

    def test_quiet_hours_are_asked_in_the_user_s_own_clock(self) -> None:
        with self.zoned("Asia/Kolkata"):
            self.assertEqual(gates._now_local_time("u"), "01:00")
        with self.zoned("America/Los_Angeles"):
            self.assertEqual(gates._now_local_time("u"), "12:30")

    def test_a_missing_timezone_falls_back_to_the_beta_s_home(self) -> None:
        for stored in (None, ""):
            with self.subTest(stored=stored):
                with self.zoned(stored):
                    self.assertEqual(gates._today("u"), "2026-09-04")

    def test_a_name_the_model_invented_falls_back_instead_of_raising(self) -> None:
        """"IST" and "Bangalore" are not IANA names. Neither may kill a turn."""
        for stored in ("IST", "Bangalore", "GMT+5:30", "../etc/passwd"):
            with self.subTest(stored=stored):
                with self.zoned(stored):
                    self.assertEqual(gates._today("u"), "2026-09-04")

    def test_two_users_in_two_places_do_not_share_an_answer(self) -> None:
        """The multi-user rule: one user's clock is never another's."""
        zones = {
            "whatsapp:sha256:mumbai": "Asia/Kolkata",
            "whatsapp:sha256:london": "Europe/London",
        }
        with patch.multiple(
            gates,
            datetime=self._Frozen,
            _cached_user_memory=lambda key: {"facts": [], "timeZone": zones[key]},
        ):
            self.assertEqual(gates._today("whatsapp:sha256:mumbai"), "2026-09-04")
            self.assertEqual(gates._today("whatsapp:sha256:london"), "2026-09-03")
            self.assertEqual(
                gates._now_local_time("whatsapp:sha256:london"), "20:30"
            )

    def test_no_user_key_never_reaches_for_storage(self) -> None:
        with patch.object(gates, "_cached_user_memory") as memory:
            gates._today("")
        memory.assert_not_called()

    def test_a_logged_moment_renders_in_the_user_s_timezone(self) -> None:
        """The duplicate question says a time back. It must be their time."""
        noon_utc = datetime(
            2026, 9, 3, 12, 0, tzinfo=dt_timezone.utc
        ).timestamp() * 1000
        with self.zoned("Asia/Kolkata"):
            self.assertEqual(
                gates._local_moment("u", noon_utc).strftime("%H:%M"), "17:30"
            )
        with self.zoned("Europe/London"):
            self.assertEqual(
                gates._local_moment("u", noon_utc).strftime("%H:%M"), "13:00"
            )


class GatedReplyParityTest(unittest.TestCase):
    """Ted must know what Ted actually said.

    The 3 Sep failure, exactly. calorie_gate replaced a reply with the age
    question, so that is what reached the user's phone. Hermes recorded the
    model's original sentence in the transcript instead, so Ted's history
    contained no age question at all. The user answered "15" and Ted said
    "that's not something I asked". Ted was not being rude; Ted had no record
    of asking. Every gated turn had this shape.
    """

    KEY = "whatsapp:sha256:parity"
    SENDER = "919999999999@s.whatsapp.net"
    SESSION = "20260903_143000_parity"

    def setUp(self) -> None:
        gates._LAST_GATED_REPLY.clear()
        self.addCleanup(gates._LAST_GATED_REPLY.clear)
        self.addCleanup(reset_user, self.KEY)
        # KEY is a literal; key() derives the real one from the sender, and
        # that is the one the tests actually write through. Resetting only the
        # literal left a forgotten user behind for the next test in the class.
        self.addCleanup(reset_user, gates._user_state_key(
            "whatsapp", self.SENDER, self.SESSION))
        self.addCleanup(gates._TURN_CONTEXT.pop, self.SESSION, None)

    def key(self) -> str:
        return gates._user_state_key("whatsapp", self.SENDER, self.SESSION)

    def capture(self) -> dict | None:
        with patch.object(
            gates, "_cached_user_memory", return_value={"facts": []}
        ):
            return gates._capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id=self.SENDER,
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="15",
            )

    def test_a_replaced_reply_is_handed_back_next_turn(self) -> None:
        gates._record_gated_reply(self.key(), "here's your 1,200 kcal target", gates.AGE_QUESTION)
        context = self.capture()
        self.assertIsNotNone(context)
        self.assertIn(gates.AGE_QUESTION, context["context"])

    def test_the_context_tells_ted_to_own_the_words(self) -> None:
        gates._record_gated_reply(self.key(), "anything", gates.AGE_QUESTION)
        body = self.capture()["context"].lower()
        self.assertIn("never saw what you wrote", body)
        self.assertIn("as though", body)
        # The specific failure: denying a question it can see it asked.
        self.assertIn("did not ask", body)

    def handed_back(self) -> str:
        """The context minus the voice card, which now rides on every turn.

        These tests are about the replaced-reply hand-back, and it used to be
        the only thing that could put a context on a turn — so "nothing was
        handed back" was asserted as "the whole return is None". The voice
        card made that assertion mean something else.
        """
        captured = self.capture() or {}
        return (captured.get("context") or "").replace(gates.VOICE_CARD, "").strip()

    def test_it_is_handed_back_once_and_then_forgotten(self) -> None:
        """A correction two turns old would confuse more than it fixes."""
        gates._record_gated_reply(self.key(), "anything", gates.AGE_QUESTION)
        self.assertIn(gates.AGE_QUESTION, self.handed_back())
        self.assertEqual(self.handed_back(), "")

    def test_an_ungated_turn_records_nothing(self) -> None:
        """Most turns are not replaced. They must cost nothing."""
        gates._record_gated_reply(self.key(), "same text", "same text")
        self.assertEqual(self.handed_back(), "")

    def test_whitespace_alone_is_not_a_replacement(self) -> None:
        gates._record_gated_reply(self.key(), "  hello  ", "hello")
        self.assertEqual(self.handed_back(), "")

    def test_erasure_clears_it(self) -> None:
        key = self.key()
        gates._record_gated_reply(key, "anything", gates.AGE_QUESTION)
        gates._forget_user(key)
        self.assertEqual(self.handed_back(), "")

    def test_the_voice_card_rides_on_every_turn(self) -> None:
        """Including the turns nothing else has anything to say about, which
        is most of them, and exactly where the tone used to drift."""
        self.assertIn(gates.VOICE_CARD, (self.capture() or {})["context"])

    def test_a_suppressed_cron_reminder_is_not_a_replacement(self) -> None:
        """CRON_SILENT means nothing was sent, so there is nothing to report."""
        gates._record_gated_reply(self.key(), "vitamin time", gates.CRON_SILENT)
        # CRON_SILENT is filtered at the call site, but the store must not
        # treat a suppression marker as something the user read either.
        with patch.object(gates, "_cached_user_memory", return_value={"facts": []}):
            context = gates._capture_turn(
                platform="whatsapp",
                session_id=self.SESSION,
                sender_id=self.SENDER,
                conversation_history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="hi",
            )
        if context:
            self.assertNotIn(gates.CRON_SILENT, context["context"])

    def test_the_full_3_sep_failure_does_not_recur(self) -> None:
        """End to end: the gate replaces, the next turn knows."""
        key = self.key()
        replaced = gates.transform_response(
            history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="what should my calorie target be?",
            response_text="your target is 1,200 calories a day.",
            user_key=key,
        )
        self.assertEqual(replaced, gates.AGE_QUESTION)
        gates._record_gated_reply(key, "your target is 1,200 calories a day.", replaced)
        # The user now answers the question they actually saw.
        body = self.capture()["context"]
        self.assertIn("how old are you", body)


class MealBreakdownTest(unittest.TestCase):
    """This meal's numbers, then the day. Written by the gate, not the model.

    On 3 Sep a logged plate came back as "logged 👍 sprouts bowl in — you're at
    roughly 1060 kcal, 46g protein for the day now": no per-meal numbers at
    all, "roughly" in front of a figure read straight out of the database, and
    a receipt word in front of the whole thing. Asking the model more nicely
    was not going to fix that. Guardrail 5: deterministic code owns facts.
    """

    KEY = "whatsapp:sha256:breakdown"

    MEAL = {
        "calories": 220,
        "proteinGrams": 14,
        "carbohydrateGrams": 30,
        "fatGrams": 3,
        "fiberGrams": 9,
    }
    DAY = {"calories": 1060, "proteinGrams": 46}

    def setUp(self) -> None:
        self.addCleanup(reset_user, self.KEY)
        self.history = [message("assistant", DISCLOSURE_MESSAGE)]

    def transform(self, reply: str, meal=None, day=None, **kw):
        return gates.transform_response(
            history=self.history,
            user_message="[image received]",
            response_text=reply,
            user_key=self.KEY,
            action_succeeded=True,
            logged_meal=self.MEAL if meal is None else meal,
            day_summary=self.DAY if day is None else day,
            **kw,
        )

    def test_the_meal_numbers_are_broken_out_one_per_line(self) -> None:
        out = self.transform("ooh sprouts bowl 😍 proper protein for a veg plate")
        self.assertIn("Calories: 220 kcal", out)
        self.assertIn("Protein: 14g", out)
        self.assertIn("Carbs: 30g", out)
        self.assertIn("Fat: 3g", out)
        self.assertIn("Fiber: 9g", out)

    def test_the_day_total_comes_after_the_meal_not_instead_of_it(self) -> None:
        out = self.transform("ooh sprouts bowl")
        self.assertIn("Calories: 1,060", out)
        self.assertIn("Protein: 46g", out)
        self.assertIn("Daily Overview", out)
        # Order matters: this meal first, the day underneath.
        self.assertLess(out.index("Calories: 220"), out.index("Daily Overview"))

    def test_ted_s_own_words_are_kept_and_come_first(self) -> None:
        out = self.transform("ooh sprouts bowl 😍 proper protein for a veg plate")
        self.assertTrue(out.startswith("ooh sprouts bowl"))

    def test_the_day_line_is_dropped_when_it_would_repeat_the_meal(self) -> None:
        """First meal of the day: "220" then "day so far 220" reads as a bug."""
        out = self.transform("ooh sprouts bowl", day={"calories": 220, "proteinGrams": 14})
        self.assertIn("Calories: 220 kcal", out)
        self.assertNotIn("day so far", out)

    def test_nothing_is_appended_when_no_meal_was_logged(self) -> None:
        out = self.transform("how's the day going?", meal={})
        self.assertNotIn("calories", out or "")

    def test_a_failed_save_never_reports_a_day(self) -> None:
        """No write, no numbers. The user is told it did not save instead."""
        out = self.transform("ooh sprouts bowl", storage_failed=True)
        self.assertNotIn("day so far", out)
        self.assertIn(gates.STORAGE_NOT_SAVED, out)

    def test_numbers_are_rounded_and_grouped_like_a_person_writes_them(self) -> None:
        out = self.transform(
            "big one",
            meal={"calories": 1234.6, "proteinGrams": 45.2, "carbohydrateGrams": 0, "fatGrams": 0},
            day={"calories": 2500.0, "proteinGrams": 90.0},
        )
        self.assertIn("Calories: 1,235 kcal", out)
        self.assertIn("Protein: 45g", out)
        self.assertIn("Calories: 2,500", out)
        self.assertIn("Daily Overview", out)
        # A zero macro is omitted rather than printed as a hollow "carbs 0g".
        self.assertNotIn("carbs 0g", out)

    def test_a_stripped_claim_still_carries_the_numbers(self) -> None:
        """The claim gate may cut the sentence. The facts still go out."""
        out = gates.transform_response(
            history=self.history,
            user_message="[image received]",
            response_text="I've saved that to your log.",
            user_key=self.KEY,
            action_succeeded=False,
            logged_meal=self.MEAL,
            day_summary=self.DAY,
        )
        self.assertIn("Calories: 220 kcal", out)

    def test_no_emoji_ever_sits_beside_a_metric(self) -> None:
        """SOUL.md: emoji belong in what Ted says, never in what Ted counts."""
        block = gates.meal_breakdown(self.MEAL, self.DAY)
        for line in block.splitlines():
            if any(ch.isdigit() for ch in line):
                self.assertTrue(line.isascii(), f"non-ascii beside a metric: {line!r}")


class MealFiguresAreNotSaidTwiceTest(unittest.TestCase):
    """The block owns the numbers, so Ted's prose must not repeat them.

    Live on 3 Sep, after the block shipped: "logged 👍 you're at 1340 kcal, 58g
    protein for the day now — solid amount of food today." The block appended
    the same day total underneath, so the user was told it twice and the food
    was never named at all, even though the tool call that saved it knew the
    plate was cheela and ketchup. SOUL.md already forbade both. The model had
    twenty protected examples of doing it anyway.
    """

    MEAL = {
        "items": ["besan/moong dal cheela (2-3 pieces)", "ketchup"],
        "calories": 280,
        "proteinGrams": 12,
        "carbohydrateGrams": 32,
        "fatGrams": 9,
    }
    DAY = {"calories": 1340, "proteinGrams": 58}
    LIVE = "logged 👍 you're at 1340 kcal, 58g protein for the day now."

    def out(self, reply: str, meal=None, day=None) -> str:
        return gates._with_meal_breakdown(
            reply, meal or self.MEAL, day or self.DAY
        )

    def test_the_day_total_appears_exactly_once(self) -> None:
        out = self.out(self.LIVE)
        self.assertEqual(out.count("1,340"), 1)
        self.assertNotIn("1340 kcal", out)

    def test_the_food_is_named_when_ted_did_not_name_it(self) -> None:
        self.assertIn("cheela", self.out(self.LIVE))

    def test_the_food_is_not_named_twice_when_ted_did(self) -> None:
        out = self.out("ooh cheela and ketchup 😍 proper breakfast food")
        self.assertTrue(out.startswith("ooh cheela and ketchup"))
        self.assertNotIn("besan/moong dal", out)

    def test_warm_words_without_numbers_are_kept(self) -> None:
        out = self.out("ooh cheela 😍 solid start. that's proper breakfast food.")
        self.assertIn("solid start", out)
        self.assertIn("proper breakfast food", out)

    def test_only_the_number_sentence_is_dropped(self) -> None:
        out = self.out("ooh cheela 😍 that's 280 calories. nice easy breakfast.")
        self.assertIn("nice easy breakfast", out)
        self.assertNotIn("280 calories", out)

    def test_a_portion_word_does_not_count_as_naming_the_food(self) -> None:
        """"2 pieces" is not the name of a dish."""
        out = self.out("logged, two pieces")
        self.assertIn("cheela", out)

    def test_every_figure_shape_the_model_uses_is_caught(self) -> None:
        for said in (
            "you're at 1340 kcal for the day",
            "that's 58g protein so far",
            "280 calories in that one",
            "protein: 12 for this meal",
            "roughly 1,340 cal today",
            "32g carbs and 9g fat",
        ):
            with self.subTest(said=said):
                self.assertEqual(gates.words_without_figures(said), "")

    def test_ordinary_sentences_survive_the_filter(self) -> None:
        for said in (
            "ooh cheela 😍",
            "proper breakfast food",
            "that's a solid start to the day",
            "want me to remind you at 8?",
        ):
            with self.subTest(said=said):
                self.assertEqual(gates.words_without_figures(said), said)


class OnboardingRemindersTest(unittest.TestCase):
    """Order 18: the check-in time onboarding asks for now has somewhere to go.

    `ted_set_reminder` had never been called once in Ted's entire history, so
    no user had a reminders row, so `maxPerDay`, the pause and the quiet-user
    back-off had nothing to read. Onboarding asked for a check-in time and
    quiet hours and dropped both answers on the floor. These tests hold the
    two halves of the fix: the answers ride on the call the model does make,
    and the row exists even when it sends nothing.
    """

    SESSION = "session-onboarding-reminders"
    USER_KEY = "whatsapp:sha256:owner"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": self.USER_KEY,
                "chat_id": "owner@s.whatsapp.net",
                "message_id": "wamid.LIVE",
            }
        self.addCleanup(self._drop_context)
        for target in (
            patch.object(gates, "_ONBOARDING_STATE", {}),
            patch.object(gates, "_persist_onboarding_state"),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _drop_context(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def _run(self, args, failing=()):
        """Run the onboarding tool, returning every Convex call it made.

        Unlike the single-call helper above, onboarding can now write twice in
        one turn, and which call carries what is the whole point.
        """
        calls: list[dict] = []

        def fake_request(action, user_key, facts=None, body=None):
            calls.append({"action": action, "user_key": user_key, "body": body or {}})
            if action in failing:
                return {"success": False, "error": "Write rejected"}
            return {"success": True, "created": True}

        with patch.object(gates, "_convex_request", fake_request):
            raw = gates._save_onboarding(args, session_id=self.SESSION)
        return calls, json.loads(raw)

    def test_a_check_in_time_given_during_onboarding_is_saved(self) -> None:
        calls, result = self._run(
            {
                "current_field": "quietHours",
                "completed_field": "dailyReview",
                "reminders": {"daily_review_time": "20:00", "max_per_day": 3},
            }
        )
        self.assertTrue(result["success"])
        reminder = [call for call in calls if call["action"] == "reminder"]
        self.assertEqual(len(reminder), 1)
        self.assertEqual(
            reminder[0]["body"], {"dailyReviewTime": "20:00", "maxPerDay": 3}
        )
        self.assertEqual(reminder[0]["user_key"], self.USER_KEY)

    def test_the_onboarding_step_is_still_recorded_in_the_same_call(self) -> None:
        calls, _ = self._run(
            {
                "current_field": "quietHours",
                "completed_field": "dailyReview",
                "reminders": {"daily_review_time": "20:00"},
            }
        )
        onboarding = [call for call in calls if call["action"] == "onboarding"]
        self.assertEqual(len(onboarding), 1)
        self.assertEqual(onboarding[0]["body"]["completedField"], "dailyReview")

    def test_passing_a_reminder_step_creates_the_row_with_no_settings_sent(self) -> None:
        """The backstop. The model sending nothing is the case that has always
        happened, and it must still leave a row behind."""
        calls, result = self._run(
            {"current_field": "morningCommitment", "completed_field": "quietHours"}
        )
        reminder = [call for call in calls if call["action"] == "reminder"]
        self.assertEqual(len(reminder), 1)
        self.assertEqual(reminder[0]["body"], {})
        self.assertEqual(result["remindersSaved"], "defaults")

    def test_an_early_onboarding_step_does_not_write_reminders(self) -> None:
        calls, result = self._run(
            {
                "current_field": "age",
                "completed_field": "name",
                "profile": {"name": "Vandy"},
            }
        )
        self.assertEqual([call["action"] for call in calls], ["onboarding"])
        self.assertNotIn("remindersSaved", result)

    def test_the_default_row_is_written_once_not_on_every_later_step(self) -> None:
        first, _ = self._run(
            {"current_field": "dailyReview", "completed_field": "reminders"}
        )
        second, _ = self._run(
            {"current_field": "confirmation", "completed_field": "complete"}
        )
        self.assertEqual(len([c for c in first if c["action"] == "reminder"]), 1)
        self.assertEqual([c["action"] for c in second], ["onboarding"])

    def test_settings_are_still_saved_after_the_default_row_exists(self) -> None:
        """Being past the backstop must not swallow a real answer given later."""
        self._run({"current_field": "dailyReview", "completed_field": "reminders"})
        calls, _ = self._run(
            {
                "current_field": "complete",
                "completed_field": "quietHours",
                "reminders": {"quiet_hours_start": "23:00", "quiet_hours_end": "06:30"},
            }
        )
        reminder = [call for call in calls if call["action"] == "reminder"]
        self.assertEqual(
            reminder[0]["body"],
            {"quietHoursStart": "23:00", "quietHoursEnd": "06:30"},
        )

    def test_a_failed_reminder_write_does_not_lose_the_onboarding_step(self) -> None:
        calls, result = self._run(
            {
                "current_field": "complete",
                "completed_field": "quietHours",
                "reminders": {"quiet_hours_start": "23:00"},
            },
            failing=("reminder",),
        )
        self.assertTrue(result["success"])
        self.assertIn("remindersError", result)
        self.assertEqual(len([c for c in calls if c["action"] == "onboarding"]), 1)
        # Not marked done, so the next step tries again rather than assuming a
        # row that was never created.
        self.assertFalse(gates._onboarding(self.USER_KEY).get("reminders_row"))

    def test_nothing_is_written_when_the_onboarding_write_itself_failed(self) -> None:
        calls, _ = self._run(
            {"current_field": "complete", "completed_field": "quietHours"},
            failing=("onboarding",),
        )
        self.assertEqual([call["action"] for call in calls], ["onboarding"])

    def test_saving_reminders_through_onboarding_does_not_prove_a_schedule(self) -> None:
        """Same rule as ted_set_reminder: a stored preference is not a booked
        message, and the claim gate must still strip "8pm check-in is set"."""
        _record_tool_success(
            tool_name="ted_save_onboarding",
            status="ok",
            args={"current_field": "complete", "reminders": {"daily_review_time": "20:00"}},
            result=json.dumps({"success": True}),
            session_id=self.SESSION,
        )
        with gates._TURN_LOCK:
            proven = set(gates._TURN_CONTEXT[self.SESSION]["successful_actions"])
        self.assertIn("memory", proven)
        self.assertNotIn("cron", proven)
        self.assertNotIn(
            "8pm check-in is set",
            action_claim_gate("8pm check-in is set.", successful_actions=proven),
        )

    def test_the_two_tools_offer_the_same_settings(self) -> None:
        """One definition, so a field can never exist on one and not the other."""
        standalone = set(gates.TED_SET_REMINDER_SCHEMA["parameters"]["properties"])
        nested = set(
            gates.TED_SAVE_ONBOARDING_SCHEMA["parameters"]["properties"]["reminders"][
                "properties"
            ]
        )
        self.assertEqual(standalone - nested, {"paused_until"})
        self.assertIn("quiet_hours_start", nested)
        self.assertIn("daily_review_time", nested)


class ErasureSurvivesTheOpenThreadTest(unittest.TestCase):
    """Order 18: a deletion the scrollback cannot undo.

    On 3 Sep a wipe cleared Convex and the durable consent record at 15:32:39.
    The next message was answered inside the same 101-message thread, and the
    transcript fallback found Ted's disclosure from 1 Sep and reported consent
    for a user whose data had just been erased. No disclosure went out, no
    onboarding ran, and the next photo was logged against the emptied account.

    A first-time user was never affected — an empty thread has nothing for the
    fallback to find. This is the path of someone who used the erasure Ted
    promises them, in writing, in the disclosure itself.
    """

    USER_KEY = "whatsapp:sha256:forgotten"
    UNTOUCHED = "whatsapp:sha256:never-asked"

    def setUp(self) -> None:
        for target in (
            patch.object(gates, "_ONBOARDING_STATE", {}),
            patch.object(gates, "_persist_onboarding_state"),
            patch.object(gates, "_DISCLOSURE_SENT_KEYS", set()),
            patch.object(gates, "_persist_disclosure_state"),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _old_thread(self) -> list[dict[str, str]]:
        """The thread as it stands when someone asks to be forgotten: their
        name in it, and Ted's disclosure from days ago."""
        return [
            message("user", "hi"),
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
            message("assistant", VANDY_DISCLOSURE),
            message("user", "logged a dosa"),
            message("assistant", "nice one"),
        ]

    def test_the_old_disclosure_stops_counting_once_they_are_forgotten(self) -> None:
        history = self._old_thread()
        self.assertTrue(gates._disclosure_was_sent(history, self.USER_KEY))
        gates._forget_user(self.USER_KEY)
        self.assertFalse(gates._disclosure_was_sent(history, self.USER_KEY))

    def test_consent_is_asked_for_again_rather_than_assumed(self) -> None:
        """The live failure: this returned None, so nothing went out at all."""
        history = self._old_thread()
        gates._forget_user(self.USER_KEY)
        self.assertIsNotNone(
            consent_gate(history, "logged that for you", user_key=self.USER_KEY)
        )

    def test_the_disclosure_goes_out_once_they_give_a_name_again(self) -> None:
        history = self._old_thread()
        gates._forget_user(self.USER_KEY)
        # Asked and answered after the wipe, which is the only name Ted may use.
        history += [
            message("assistant", "What should I call you?"),
            message("user", "Vandy"),
        ]
        reply = consent_gate(history, "ok", user_key=self.USER_KEY)
        self.assertIn(gates.PRIVACY_URL, reply or "")
        # And the five start over with them, because everything Ted knew
        # about them went with the wipe.
        self.assertIn(gates._setup_question(0), reply or "")

    def test_the_name_still_comes_from_the_thread_after_a_wipe(self) -> None:
        """Deliberately not guarded, and the reason is written down.

        Blocking the transcript here was tried and reverted: it also blocks
        the name they give *after* the wipe, because that answer is only ever
        read back out of the same transcript. The result was a permanent loop
        on "what should I call you?" and a disclosure that never went out —
        worse than the leak it prevented. The right fix is to scan only the
        part of the thread after the erasure, which needs a marker the history
        does not carry yet. Until then the disclosure going out is what
        matters, and it does.
        """
        history = self._old_thread()
        gates._forget_user(self.USER_KEY)
        self.assertEqual(gates._given_name(history, self.USER_KEY), "Vandy")

    def test_a_fresh_disclosure_after_the_wipe_counts_again(self) -> None:
        """The mark must not pin them to re-disclosing forever."""
        history = self._old_thread()
        gates._forget_user(self.USER_KEY)
        gates._mark_disclosure_sent(self.USER_KEY, "session-after-wipe")
        self.assertTrue(gates._disclosure_was_sent(history, self.USER_KEY))
        self.assertIsNone(
            consent_gate(history, "what did you have?", user_key=self.USER_KEY)
        )

    def test_forgetting_keeps_a_timestamp_and_nothing_else(self) -> None:
        gates._update_onboarding(self.USER_KEY, name="Vandy", age=31, minor=False)
        gates._forget_user(self.USER_KEY)
        record = gates._onboarding(self.USER_KEY)
        self.assertEqual(set(record), {"forgotten_at"})
        self.assertIsInstance(record["forgotten_at"], float)

    def test_an_untouched_user_still_reads_their_transcript(self) -> None:
        """The fallback is still the fallback for everyone who never asked."""
        history = self._old_thread()
        gates._forget_user(self.USER_KEY)
        self.assertTrue(gates._disclosure_was_sent(history, self.UNTOUCHED))
        self.assertEqual(gates._given_name(history, self.UNTOUCHED), "Vandy")


class SessionRecordCannotRegrantConsentTest(unittest.TestCase):
    """The second half of the 3 Sep erasure failure.

    Clearing the user key was never enough. A WhatsApp thread keeps its
    session id through a wipe and through having every message deleted, and
    that id had its own entry in the consent list from 2 Sep. `_capture_turn`
    read it, wrote consent back onto the user key, and the reply gate then
    inserted a disclosure into the empty history on the strength of it — so
    no disclosure went out, and the scripted opener was skipped too, because
    a prepared start needs a history that is genuinely empty.
    """

    SESSION = "20260902_164400_cc233467"
    USER_KEY = "whatsapp:sha256:cbf8ffc790890dc7ffa6f11d91a70647fca0cf4c119ec238ed5827b6eabe8c71"

    def setUp(self) -> None:
        for target in (
            patch.object(gates, "_ONBOARDING_STATE", {}),
            patch.object(gates, "_persist_onboarding_state"),
            patch.object(gates, "_DISCLOSURE_SENT_KEYS", {self.SESSION}),
            patch.object(gates, "_persist_disclosure_state"),
            patch.object(gates, "_user_state_key", lambda *a, **k: self.USER_KEY),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.addCleanup(self._drop_context)

    def _drop_context(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def _capture(self, user_message: str = "hi"):
        _capture_turn(
            platform="whatsapp",
            session_id=self.SESSION,
            sender_id="144504426369026@lid",
            conversation_history=[],
            user_message=user_message,
        )
        with gates._TURN_LOCK:
            return dict(gates._TURN_CONTEXT[self.SESSION])

    def test_the_session_record_still_counts_for_someone_who_never_asked(self) -> None:
        """Unchanged for everyone else: this is how a pre-user-key thread keeps
        its consent instead of re-asking a user who was properly told."""
        self.assertTrue(self._capture()["disclosure_sent"])
        self.assertIn(self.USER_KEY, gates._DISCLOSURE_SENT_KEYS)

    def test_the_session_record_does_not_survive_an_erasure(self) -> None:
        gates._forget_user(self.USER_KEY)
        self.assertFalse(self._capture()["disclosure_sent"])
        self.assertNotIn(self.USER_KEY, gates._DISCLOSURE_SENT_KEYS)

    def test_the_scripted_opener_still_fires_after_an_erasure(self) -> None:
        """The injected disclosure made the history non-empty, which is what
        swallowed the opener and let the model answer in its own words."""
        gates._forget_user(self.USER_KEY)
        self._capture("Okay Ted, let's do this!")
        self.assertEqual(
            _transform_live_response(
                platform="whatsapp",
                session_id=self.SESSION,
                response_text="hey Vandy 🙌 meal tracking i can absolutely help with",
            ),
            OPENING_MESSAGE,
        )

    def test_a_real_re_disclosure_after_the_wipe_ends_the_asking(self) -> None:
        gates._forget_user(self.USER_KEY)
        gates._mark_disclosure_sent(self.USER_KEY, self.SESSION)
        self.assertTrue(self._capture()["disclosure_sent"])


class DeletionQuestionIsRecognisedTest(unittest.TestCase):
    """The erasure Ted promises must not turn on a synonym.

    3 Sep, 15:53: a user asked to be deleted, Ted asked "you want me to
    permanently wipe everything I have on you, profile, targets, logs, all of
    it?", the user said "Yes", and the gate refused because the literal word
    "delete" was missing. The account survived and the user was told nothing
    was gone. Erasure is promised in the disclosure text itself.
    """

    def asked(self, said: str) -> bool:
        return gates._ted_asked_about_deletion([message("assistant", said)])

    def test_the_live_3_sep_question_is_accepted(self) -> None:
        self.assertTrue(
            self.asked(
                "just to make sure, you want me to permanently wipe everything I "
                "have on you, profile, targets, logs, all of it? no undo once "
                "it's done. say the word and I'll do it."
            )
        )

    def test_the_words_a_model_actually_reaches_for(self) -> None:
        for said in (
            "this wipes everything, no undo. delete?",
            "delete everything i have on you?",
            "want me to erase all of it? there's no undo",
            "shall i clear all your data?",
            "remove everything, permanently? say yes and it's gone",
            "you want your whole history gone?",
        ):
            with self.subTest(said=said):
                self.assertTrue(self.asked(said))

    def test_a_narrow_question_still_cannot_wipe_an_account(self) -> None:
        """The reason the strict version existed, and it still has to hold."""
        for said in (
            "shall i delete that meal?",
            "want me to remove the dosa from today?",
            "should i clear that one entry?",
            "i'll wipe that last log, ok?",
        ):
            with self.subTest(said=said):
                self.assertFalse(self.asked(said))

    def test_a_statement_is_not_a_question(self) -> None:
        self.assertFalse(self.asked("i can delete everything you've logged."))

    def test_an_unrelated_question_is_not_a_deletion_question(self) -> None:
        for said in (
            "how did everything go today?",
            "want me to log all of it?",
        ):
            with self.subTest(said=said):
                self.assertFalse(self.asked(said))


class GateOwnsTheDeletionQuestionTest(unittest.TestCase):
    """Reading Ted's prose to decide whether Ted asked failed twice on 3 Sep.

    15:53 — Ted asked "you want me to permanently wipe everything I have on
    you ... all of it?" and the check wanted the literal word "delete".
    16:02 — Ted wrote `reply with the single word "delete" if you mean it.`
    and the check wanted a question mark. Both times the user had asked to be
    erased, answered clearly, and been told nothing was deleted. The gate now
    asks the question itself and remembers that it did.
    """

    SESSION = "session-delete-owned"
    USER_KEY = "whatsapp:sha256:deleter"

    def setUp(self) -> None:
        for target in (
            patch.object(gates, "_ONBOARDING_STATE", {}),
            patch.object(gates, "_persist_onboarding_state"),
        ):
            target.start()
            self.addCleanup(target.stop)
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [message("assistant", DISCLOSURE_MESSAGE)],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": self.USER_KEY,
            }
        self.addCleanup(self._drop)

    def _drop(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def ask(self, said: str, reply: str = "sure thing") -> str | None:
        return gates.transform_response(
            history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message=said,
            response_text=reply,
            user_key=self.USER_KEY,
        )

    def confirm(self, said: str) -> dict:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION]["user_message"] = said
        with patch.object(gates, "_convex_request", lambda *a, **k: {"success": True}):
            with patch.object(gates, "_forget_user"):
                return json.loads(
                    gates._delete_user_data({"confirmed": True}, session_id=self.SESSION)
                )

    def test_the_request_gets_the_gate_s_own_question(self) -> None:
        self.assertEqual(self.ask("delete my data"), gates.DELETE_CONFIRMATION_QUESTION)
        self.assertTrue(gates._delete_is_pending(self.USER_KEY))

    def test_the_word_the_question_asks_for_is_accepted(self) -> None:
        """Ted told a user to reply "delete"; "Delete" was then refused."""
        self.ask("delete my data")
        self.assertTrue(self.confirm("Delete")["success"])

    def test_the_erasure_completes_without_reading_ted_s_wording(self) -> None:
        self.ask("delete my data")
        for word in ("yes", "Yes", "confirm", "go ahead", "haan"):
            with self.subTest(word=word):
                gates._mark_delete_pending(self.USER_KEY)
                self.assertTrue(self.confirm(word)["success"])

    def test_a_request_is_still_never_its_own_confirmation(self) -> None:
        self.ask("delete my data")
        result = self.confirm("delete my data")
        self.assertFalse(result["success"])
        self.assertIn("not an explicit confirmation", result["error"])

    def test_nothing_is_deleted_when_the_gate_never_asked(self) -> None:
        result = self.confirm("yes")
        self.assertFalse(result["success"])
        self.assertIn("Nothing has been deleted", result["error"])

    def test_editing_one_meal_is_not_an_erasure_request(self) -> None:
        for said in (
            "delete that meal",
            "remove the dosa from today",
            "clear that last entry",
        ):
            with self.subTest(said=said):
                self.assertNotEqual(
                    self.ask(said), gates.DELETE_CONFIRMATION_QUESTION
                )
                self.assertFalse(gates._delete_is_pending(self.USER_KEY))

    def test_the_question_stops_being_live_once_they_talk_about_something_else(
        self,
    ) -> None:
        """A "yes" three turns later must not land on a question nobody
        remembers being asked."""
        self.ask("delete my data")
        self.ask("actually, logged a dosa for lunch")
        self.assertFalse(gates._delete_is_pending(self.USER_KEY))
        self.assertFalse(self.confirm("yes")["success"])

    def test_a_stale_question_expires(self) -> None:
        self.ask("delete my data")
        gates._update_onboarding(
            self.USER_KEY,
            delete_asked_at=time.time() - gates._DELETE_PENDING_SECONDS - 1,
        )
        self.assertFalse(gates._delete_is_pending(self.USER_KEY))
        self.assertFalse(self.confirm("yes")["success"])

    def test_the_ways_people_ask_to_be_forgotten(self) -> None:
        for said in (
            "delete my data",
            "Delete my data",
            "delete my account",
            "erase everything",
            "wipe my data please",
            "remove all my information",
            "forget me",
        ):
            with self.subTest(said=said):
                gates._clear_delete_pending(self.USER_KEY)
                self.assertEqual(
                    self.ask(said), gates.DELETE_CONFIRMATION_QUESTION
                )


class MacrosMustAgreeWithCaloriesTest(unittest.TestCase):
    """The gate guarantees the figure it prints is the figure in the database.

    It does not guarantee the figure is possible. Nutrition is a language
    model's guess with no food database behind it, and an impossible meal
    would be stored and shown in the same confident block as a good one.
    This is the cheapest floor under it: protein and carbs at 4 kcal a gram,
    fat at 9, with a loose tolerance because the sum is an approximation and
    this is not here to grade an estimate.
    """

    def reason(self, **meal) -> str:
        full = {
            "proteinGrams": 0.0,
            "carbohydrateGrams": 0.0,
            "fatGrams": 0.0,
            "fiberGrams": 0.0,
            "calories": 0.0,
        }
        full.update(meal)
        return gates._macros_contradict_calories(full)

    def test_the_two_real_meals_from_3_sep_pass(self) -> None:
        """Both of Pradosh's, before and after he corrected the oats."""
        self.assertEqual(
            self.reason(
                calories=390, proteinGrams=33, carbohydrateGrams=34, fatGrams=14
            ),
            "",
        )
        self.assertEqual(
            self.reason(
                calories=610, proteinGrams=41, carbohydrateGrams=72, fatGrams=17
            ),
            "",
        )

    def test_a_partial_estimate_is_not_a_contradiction(self) -> None:
        """"380 kcal, 19g protein" is an ordinary meal. The first version of
        this check refused it, and an existing test caught that."""
        self.assertEqual(self.reason(calories=380, proteinGrams=19), "")

    def test_a_calorie_figure_far_above_its_macros_is_refused(self) -> None:
        self.assertIn(
            "not 1200",
            self.reason(
                calories=1200, proteinGrams=10, carbohydrateGrams=20, fatGrams=5
            ),
        )

    def test_a_calorie_figure_far_below_its_macros_is_refused(self) -> None:
        self.assertIn(
            "not 100",
            self.reason(
                calories=100, proteinGrams=50, carbohydrateGrams=50, fatGrams=20
            ),
        )

    def test_macros_with_no_calorie_figure_are_refused(self) -> None:
        self.assertIn("calories is 0", self.reason(proteinGrams=30, fatGrams=10))

    def test_calories_alone_are_left_alone(self) -> None:
        """An estimate with nothing to contradict is not a wrong one."""
        self.assertEqual(self.reason(calories=450), "")

    def test_ordinary_rounding_is_not_a_contradiction(self) -> None:
        for calories in (380, 400, 394, 350, 440):
            with self.subTest(calories=calories):
                self.assertEqual(
                    self.reason(
                        calories=calories,
                        proteinGrams=33,
                        carbohydrateGrams=34,
                        fatGrams=14,
                    ),
                    "",
                )

    def test_a_small_meal_gets_the_flat_margin_not_the_percentage(self) -> None:
        """30% of a 60 kcal meal is 18, which would fail on rounding alone."""
        self.assertEqual(self.reason(calories=60, proteinGrams=5, fatGrams=2), "")

    def test_the_impossible_meal_never_reaches_convex(self) -> None:
        session = "session-macro-guard"
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[session] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": "whatsapp:sha256:macro",
            }
        self.addCleanup(
            lambda: gates._TURN_CONTEXT.pop(session, None)
        )
        sent = {}

        def fake_request(action, user_key, facts=None, body=None):
            sent["called"] = True
            return {"success": True}

        with patch.object(gates, "_convex_request", fake_request):
            raw = gates._log_daily_entry(
                {
                    "entry_type": "meal",
                    "meal": {
                        "items": ["protein shake"],
                        "calories": 100,
                        "protein_grams": 50,
                        "carbohydrate_grams": 50,
                        "fat_grams": 20,
                    },
                },
                session_id=session,
            )
        result = json.loads(raw)
        self.assertFalse(result["success"])
        self.assertNotIn("called", sent)
        self.assertIn("Do not tell them it is logged", result["error"])


class FoodTableTest(unittest.TestCase):
    """Composition is a lookup, not a recollection.

    On 3 Sep a user told Ted a scoop of whey was "definitely not 120 kcal".
    Ted's number was reasonable and it folded anyway, because a recollection
    is all it had to stand on. The table is what it stands on now.
    """

    def look(self, items) -> dict:
        return json.loads(gates._food_lookup({"items": items}))

    def test_every_entry_is_physically_possible(self) -> None:
        """The same check the gate applies to a logged meal, applied to the
        reference data itself. A table that fails it would feed the gate
        numbers the gate would then refuse."""
        self.assertTrue(gates._FOOD_TABLE, "food table failed to load")
        for food in gates._FOOD_TABLE:
            with self.subTest(food=food["name"]):
                per = food["per_100g"]
                self.assertEqual(
                    gates._macros_contradict_calories(
                        {
                            "calories": per["calories"],
                            "proteinGrams": per["protein"],
                            "carbohydrateGrams": per["carbs"],
                            "fatGrams": per["fat"],
                        }
                    ),
                    "",
                )

    def test_the_meal_that_started_this(self) -> None:
        """100g oats, a 30g scoop, 20g nuts and seeds. Ted said 610 from
        memory; the table is what decides now."""
        result = self.look(
            [
                {"name": "oats", "grams": 100},
                {"name": "protein powder", "grams": 30},
                {"name": "nuts and seeds", "grams": 20},
            ]
        )
        self.assertEqual(result["unmatched"], [])
        total = result["total"]
        self.assertGreater(total["calories"], 550)
        self.assertLess(total["calories"], 680)
        self.assertGreater(total["protein_grams"], 35)

    def test_a_missing_weight_is_assumed_and_says_so(self) -> None:
        row = self.look([{"name": "banana"}])["items"][0]
        self.assertTrue(row["portionAssumed"])
        self.assertEqual(row["grams"], 120)

    def test_a_given_weight_is_used_and_not_flagged(self) -> None:
        row = self.look([{"name": "banana", "grams": 200}])["items"][0]
        self.assertFalse(row["portionAssumed"])
        self.assertEqual(row["calories"], 178)

    def test_the_words_people_actually_use(self) -> None:
        for said, expected in (
            ("chapati", "roti"),
            ("dahi", "curd"),
            ("chana", "chana, cooked"),
            ("black coffee", "coffee, black"),
            ("boiled egg", "egg, whole"),
            ("whey", "whey protein powder"),
        ):
            with self.subTest(said=said):
                self.assertEqual(self.look([{"name": said}])["items"][0]["food"], expected)

    def test_an_unknown_food_is_reported_not_guessed(self) -> None:
        result = self.look([{"name": "ras malai"}])
        self.assertEqual(result["unmatched"], ["ras malai"])
        self.assertFalse(result["items"][0]["found"])
        self.assertEqual(result["total"]["calories"], 0)

    def test_the_total_only_counts_what_was_found(self) -> None:
        result = self.look(
            [{"name": "banana", "grams": 100}, {"name": "ras malai", "grams": 100}]
        )
        self.assertEqual(result["total"]["calories"], 89)
        self.assertEqual(result["unmatched"], ["ras malai"])

    def test_a_lookup_writes_nothing_and_needs_no_user(self) -> None:
        """It reads a file. No turn context, no Convex, no user key."""
        with patch.object(gates, "_convex_request") as convex:
            self.assertTrue(self.look([{"name": "rice"}])["success"])
        convex.assert_not_called()

    def test_an_empty_request_is_refused(self) -> None:
        self.assertFalse(json.loads(gates._food_lookup({"items": []}))["success"])

    def test_the_total_it_returns_would_pass_the_macro_guard(self) -> None:
        """The two halves have to agree, or Ted looks food up and is then
        refused for logging what it was told."""
        total = self.look(
            [
                {"name": "rice", "grams": 150},
                {"name": "dal", "grams": 150},
                {"name": "roti", "grams": 80},
            ]
        )["total"]
        self.assertEqual(
            gates._macros_contradict_calories(
                {
                    "calories": total["calories"],
                    "proteinGrams": total["protein_grams"],
                    "carbohydrateGrams": total["carbohydrate_grams"],
                    "fatGrams": total["fat_grams"],
                }
            ),
            "",
        )


class TedsVoiceSurvivesTheFigureStripTest(unittest.TestCase):
    """The block owns the numbers. It was also taking the words with them.

    Splitting on `.!?` alone assumed prose Ted does not write. It writes short
    lines, emoji, and frequently no full stop, so a reply whose middle line
    held the figures was one sentence containing figures and was removed
    whole. The user received a bare block of numbers and not one word.
    """

    PRADOSH = (
        "Today · 2 meals\n"
        "615 / kcal · 41g protein\n"
        "good breakfast lineup, coffee barely counts anyway ☕"
    )

    def test_the_real_3_sep_reply_keeps_its_words(self) -> None:
        kept = gates.words_without_figures(self.PRADOSH)
        self.assertIn("good breakfast lineup", kept)
        self.assertNotIn("41g protein", kept)
        self.assertNotIn("615", kept)

    def test_the_figures_still_only_come_from_the_block(self) -> None:
        out = gates._with_meal_breakdown(
            self.PRADOSH,
            {
                "calories": 614,
                "proteinGrams": 40.6,
                "carbohydrateGrams": 74.1,
                "fatGrams": 18.0,
                "fiberGrams": 11.7,
            },
            {"calories": 619, "proteinGrams": 40.8},
        )
        self.assertIn("good breakfast lineup", out)
        self.assertIn("Calories: 614 kcal", out)
        # The model's own numbers appear nowhere, so nothing is printed twice.
        self.assertNotIn("615", out)
        # "41g protein" is the model's phrasing and is stripped; "protein 41g"
        # is the block's own. It can legitimately appear twice — the meal and
        # the day round to the same figure on the first meal of the day.
        self.assertNotIn("41g protein", out)
        self.assertIn("Protein: 41g", out)
        self.assertLess(out.index("good breakfast"), out.index("Calories: 614"))

    def test_a_line_of_pure_numbers_still_goes(self) -> None:
        self.assertEqual(gates.words_without_figures("1,340 cal, 58g protein"), "")

    def test_sentence_splitting_within_a_line_still_works(self) -> None:
        self.assertEqual(
            gates.words_without_figures("nice one. 614 kcal, 41g protein. good start"),
            "nice one. good start",
        )

    def test_ordinary_replies_are_untouched(self) -> None:
        for said in (
            "ooh cheela 😍",
            "proper breakfast food",
            "that's a solid start to the day",
            "want me to remind you at 8?",
        ):
            with self.subTest(said=said):
                self.assertEqual(gates.words_without_figures(said), said)

    def test_a_whole_line_wrapped_around_a_number_still_goes(self) -> None:
        """Not fixed, and deliberately: a clause-level cut mangles prose, and
        the block says what the sentence said."""
        self.assertEqual(
            gates.words_without_figures("ooh power bowl 💪 that is 614 kcal"), ""
        )


class TheOpenerIsOneGreetingAndOneQuestionTest(unittest.TestCase):
    """One line, one question, and no pitch.

    The four-paragraph opener this replaces explained the product to people
    who had just read the product on the landing page. A tester's first
    reaction to it on 3 Sep was "keep it short".

    The old opener was also the only place that told anyone photos and voice
    notes work, and a tester spent forty minutes typing before someone else
    mentioned voice. That coverage does not disappear: the last test here
    holds the capability knowledge to SOUL.md, where Ted offers those inputs
    at the moment they would help rather than in a greeting.
    """

    def test_it_is_one_short_line(self) -> None:
        self.assertNotIn("\n", gates.OPENING_MESSAGE)
        self.assertLessEqual(len(gates.OPENING_MESSAGE), 60)

    def test_it_asks_exactly_one_question(self) -> None:
        self.assertEqual(gates.OPENING_MESSAGE.count("?"), 1)

    def test_it_still_ends_on_the_name_question(self) -> None:
        """The opener counts as asking for the name, so it has to still ask."""
        self.assertTrue(gates.OPENING_MESSAGE.rstrip().endswith("?"))
        self.assertIn("call you", gates.OPENING_MESSAGE)

    def test_it_does_not_pitch_the_product(self) -> None:
        opener = gates.OPENING_MESSAGE.lower()
        for pitch in ("here's the deal", "recap", "keep score", "nudge"):
            self.assertNotIn(pitch, opener)

    def test_soul_md_still_carries_photos_and_voice(self) -> None:
        soul = (
            Path(gates.__file__).resolve().parent.parent / "SOUL.md"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("voice note", soul)
        self.assertIn("photo", soul)

    def test_a_prepared_start_still_gets_it_verbatim(self) -> None:
        self.assertEqual(
            transform_response(
                history=[message("user", "Okay Ted, let's do this!")],
                user_message="Okay Ted, let's do this!",
                response_text="something the model made up instead.",
            ),
            gates.OPENING_MESSAGE,
        )


class RemindersActuallyGetScheduledTest(unittest.TestCase):
    """A stored preference is not a booked message, and now one becomes one.

    3 Sep, 16:35: a tester asked for a 10:30 supplement nudge. The row saved
    perfectly, as a separate item, exactly as designed. Nothing scheduled it,
    so it could never have arrived. Ted's own guard — never claim a reminder
    is set on the strength of that row — was the right rule about the wrong
    problem.
    """

    SESSION = "session-scheduling"
    USER_KEY = "whatsapp:sha256:scheduled"
    CHAT = "150319677886614@lid"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": self.USER_KEY,
                "chat_id": self.CHAT,
            }
        self.addCleanup(self._drop)
        self.calls: list[list[str]] = []
        for target in (
            patch.object(gates, "_run_cron_cli", self._fake_cron),
            patch.object(gates, "_convex_request", lambda *a, **k: {"success": True}),
            patch.object(gates, "_load_cron_jobs", lambda: self.jobs),
            patch.object(gates, "_user_time_zone", lambda key: ZoneInfo("Europe/London")),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.jobs: list[dict] = []

    def _fake_cron(self, args) -> bool:
        self.calls.append(list(args))
        return True

    def _drop(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def created(self) -> list[list[str]]:
        return [call for call in self.calls if call and call[0] == "create"]

    def test_a_supplement_nudge_becomes_a_real_job(self) -> None:
        raw = gates._set_reminder(
            {
                "items": [
                    {
                        "reminderId": "supplements_morning",
                        "commitmentId": "supplements",
                        "localTime": "10:30",
                        "enabled": True,
                    }
                ]
            },
            session_id=self.SESSION,
        )
        self.assertIn("supplements_morning", json.loads(raw)["scheduled"])
        create = self.created()[0]
        self.assertIn(f"whatsapp:{self.CHAT}", create)
        self.assertIn("supplements", " ".join(create))

    def test_the_job_fires_at_the_users_clock_not_the_laptops(self) -> None:
        """The scheduler runs in Asia/Kolkata. Pradosh is in London. 10:30
        means 10:30 where he is."""
        gates._sync_reminder_jobs(
            self.USER_KEY,
            self.CHAT,
            {
                "items": [
                    {
                        "reminderId": "supplements_morning",
                        "commitmentId": "supplements",
                        "localTime": "10:30",
                        "enabled": True,
                    }
                ]
            },
        )
        expression = self.created()[0][1]
        london = datetime(2026, 9, 3, 10, 30, tzinfo=ZoneInfo("Europe/London"))
        here = london.astimezone()
        self.assertEqual(expression, f"{here.minute} {here.hour} * * *")

    def test_the_daily_review_time_is_scheduled_too(self) -> None:
        gates._sync_reminder_jobs(
            self.USER_KEY, self.CHAT, {"dailyReviewTime": "22:00"}
        )
        self.assertEqual(len(self.created()), 1)

    def test_a_disabled_reminder_is_not_scheduled(self) -> None:
        gates._sync_reminder_jobs(
            self.USER_KEY,
            self.CHAT,
            {
                "items": [
                    {
                        "reminderId": "off",
                        "commitmentId": "x",
                        "localTime": "09:00",
                        "enabled": False,
                    }
                ]
            },
        )
        self.assertEqual(self.created(), [])

    def test_saving_the_same_preference_twice_does_not_stack_jobs(self) -> None:
        item = {
            "reminderId": "supplements_morning",
            "commitmentId": "supplements",
            "localTime": "10:30",
            "enabled": True,
        }
        gates._sync_reminder_jobs(self.USER_KEY, self.CHAT, {"items": [item]})
        expression = self.created()[0][1]
        # The job now exists, with that schedule.
        self.jobs = [
            {
                "id": "abc123",
                "name": gates._reminder_job_name(self.USER_KEY, "supplements_morning"),
                "schedule_display": expression,
            }
        ]
        self.calls.clear()
        gates._sync_reminder_jobs(self.USER_KEY, self.CHAT, {"items": [item]})
        self.assertEqual(self.calls, [])

    def test_changing_the_time_replaces_the_job_rather_than_adding_one(self) -> None:
        self.jobs = [
            {
                "id": "abc123",
                "name": gates._reminder_job_name(self.USER_KEY, "supplements_morning"),
                "schedule_display": "0 5 * * *",
            }
        ]
        gates._sync_reminder_jobs(
            self.USER_KEY,
            self.CHAT,
            {
                "items": [
                    {
                        "reminderId": "supplements_morning",
                        "commitmentId": "supplements",
                        "localTime": "11:00",
                        "enabled": True,
                    }
                ]
            },
        )
        self.assertEqual(self.calls[0][:2], ["remove", "abc123"])
        self.assertEqual(len(self.created()), 1)

    def test_a_reminder_the_user_removed_stops_firing(self) -> None:
        self.jobs = [
            {
                "id": "old1",
                "name": gates._reminder_job_name(self.USER_KEY, "gone"),
                "schedule_display": "0 5 * * *",
            }
        ]
        gates._sync_reminder_jobs(self.USER_KEY, self.CHAT, {"items": []})
        self.assertEqual(self.calls[0][:2], ["remove", "old1"])

    def test_changing_only_quiet_hours_cancels_nothing(self) -> None:
        """Convex leaves the items array alone when it is not sent, so this
        payload says nothing about which reminders exist. Reading its silence
        as "none" would cancel every nudge the user has."""
        self.jobs = [
            {
                "id": "keep1",
                "name": gates._reminder_job_name(self.USER_KEY, "supplements_morning"),
                "schedule_display": "0 5 * * *",
            }
        ]
        gates._sync_reminder_jobs(
            self.USER_KEY,
            self.CHAT,
            {"quietHoursStart": "23:00", "quietHoursEnd": "07:00"},
        )
        self.assertEqual(self.calls, [])

    def test_a_scheduling_failure_never_loses_the_saved_preference(self) -> None:
        with patch.object(gates, "_sync_reminder_jobs", side_effect=RuntimeError("no")):
            result = json.loads(
                gates._set_reminder({"max_per_day": 2}, session_id=self.SESSION)
            )
        self.assertTrue(result["success"])
        self.assertNotIn("scheduled", result)

    def test_a_malformed_time_is_skipped_not_scheduled(self) -> None:
        for bad in ("10:30 am", "25:00", "1030", "", "half past ten"):
            with self.subTest(bad=bad):
                self.assertIsNone(
                    gates._cron_expression(bad, ZoneInfo("Europe/London"))
                )


class ScheduledIsTheOnlyThingThatProvesAReminderTest(unittest.TestCase):
    """"8pm check-in is set" is true only when something will fire at 8pm."""

    SESSION = "session-claim-scheduled"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": "whatsapp:sha256:claims",
            }
        self.addCleanup(self._drop)

    def _drop(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def proven(self, payload: dict, tool: str = "ted_set_reminder") -> set:
        _record_tool_success(
            tool_name=tool,
            status="ok",
            args={},
            result=json.dumps(payload),
            session_id=self.SESSION,
        )
        with gates._TURN_LOCK:
            return set(gates._TURN_CONTEXT[self.SESSION]["successful_actions"])

    def test_a_stored_preference_alone_still_strips_the_claim(self) -> None:
        proven = self.proven({"success": True})
        self.assertIn("memory", proven)
        self.assertNotIn("cron", proven)
        self.assertNotIn(
            "8pm check-in is set",
            action_claim_gate("8pm check-in is set.", successful_actions=proven),
        )

    def test_a_scheduled_reminder_lets_ted_say_so(self) -> None:
        proven = self.proven({"success": True, "scheduled": ["supplements_morning"]})
        self.assertIn("cron", proven)
        # None means the gate left Ted's sentence alone, which is the whole
        # point: the claim is now true, so nothing is stripped.
        self.assertIsNone(
            action_claim_gate("10:30 nudge is set.", successful_actions=proven)
        )

    def test_an_empty_scheduled_list_proves_nothing(self) -> None:
        """Scheduling was attempted and nothing reached the crontab."""
        self.assertNotIn("cron", self.proven({"success": True, "scheduled": []}))

    def test_onboarding_can_prove_it_too(self) -> None:
        """The check-in time usually arrives through ted_save_onboarding, and
        it schedules by the same path."""
        proven = self.proven(
            {"success": True, "scheduled": ["daily_review"]}, tool="ted_save_onboarding"
        )
        self.assertIn("cron", proven)

    def test_onboarding_without_scheduling_is_still_only_memory(self) -> None:
        proven = self.proven(
            {"success": True, "remindersSaved": "defaults"}, tool="ted_save_onboarding"
        )
        self.assertIn("memory", proven)
        self.assertNotIn("cron", proven)


class EveryLineTedSaysSoundsLikeTedTest(unittest.TestCase):
    """Personality cannot live only in SOUL.md.

    Ted's messages come from three places and SOUL.md governs one of them.
    The model writes some; this gate writes fixed strings that never reach the
    model at all; Hermes writes its own gateway notices. Every reliability fix
    on 3 Sep moved *more* of Ted into the second category — the meal numbers,
    the deletion question, the busy acknowledgements — which is exactly why it
    read as more robotic the more correct it became. So the gate's own lines
    are held to the voice here, by a test, instead of drifting one merge at a
    time back towards "I haven't completed that action."
    """

    #: Everything a user can actually receive, written by this gate.
    SPOKEN = (
        "OPENING_MESSAGE",
        "GOAL_QUESTION",
        "ALREADY_STARTED_MESSAGE",
        "NAME_NOT_USABLE_MESSAGE",
        "AGE_QUESTION",
        "UNDER_18_REFUSAL",
        "CLAIM_NOT_DONE",
        "STORAGE_NOT_SAVED",
        "REPORT_CONFIRMATION",
        "REPORT_NOT_SAVED",
        "UNREADABLE_DOCUMENT_REPLY",
        "REVIEW_TIME_QUESTION",
        "WEEKLY_REVIEW_OFFER",
        "DELETE_CONFIRMATION_QUESTION",
    )

    # DISCLOSURE_MESSAGE is deliberately absent. It is a privacy notice that
    # names the product in the third person, `_DISCLOSURE_MARKER` matches its
    # opening words, and consent records going back to 1 Sep were written
    # against that exact text. It is the one line where being unmistakable
    # beats sounding like Ted.

    #: Words from a different product. None of these belong in a health app.
    MACHINE_WORDS = (
        "action", "invalid", "error", "request", "processing", "unable to",
        "task", "operation", "system", "please try again", "user",
    )

    def spoken(self):
        for name in self.SPOKEN:
            yield name, getattr(gates, name)

    def test_every_one_of_them_exists(self) -> None:
        """A renamed constant must fail here rather than quietly stop being
        checked."""
        for name, value in self.spoken():
            with self.subTest(name=name):
                self.assertTrue(value and isinstance(value, str))

    def test_none_of_them_talk_like_a_machine(self) -> None:
        for name, value in self.spoken():
            for word in self.MACHINE_WORDS:
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, value.lower())

    def test_they_start_in_lower_case_like_ted_does(self) -> None:
        for name, value in self.spoken():
            with self.subTest(name=name):
                first = value.lstrip()[0]
                self.assertTrue(
                    first.islower() or not first.isalpha(),
                    f"{name} opens with a capital: {value[:40]!r}",
                )

    def test_none_of_them_shout(self) -> None:
        """One "hey!" is warmth. Two is breathless, and capitals are shouting.

        The first version of this banned exclamation marks outright and failed
        on the opener's "hey!", which is the one thing in it doing any work.
        """
        for name, value in self.spoken():
            with self.subTest(name=name):
                self.assertLessEqual(value.count("!"), 1, f"{name} is breathless")
                shouted = [
                    word
                    for word in re.findall(r"[A-Za-z]{3,}", value)
                    if word.isupper()
                ]
                self.assertEqual(shouted, [], f"{name} shouts: {shouted}")

    def test_a_refusal_still_says_what_and_why(self) -> None:
        """Voice must not cost clarity. These two say no to something, and a
        person has to be able to tell what and why."""
        self.assertIn("adults", gates.UNDER_18_REFUSAL)
        self.assertIn("calorie", gates.UNDER_18_REFUSAL)
        self.assertIn("pdf", gates.UNREADABLE_DOCUMENT_REPLY.lower())

    def test_the_deletion_question_is_still_unmistakable(self) -> None:
        """The one place warmth must not soften the meaning."""
        for word in ("delete", "everything", "no undo"):
            with self.subTest(word=word):
                self.assertIn(word, gates.DELETE_CONFIRMATION_QUESTION.lower())

    def test_the_disclosure_says_the_three_things_it_has_to_say(self) -> None:
        """Rewritten in Ted's voice on 4 Sep; the content is what is fixed.

        What is kept, where the detail is, and how to make it all go. The
        wording moved from terms-of-service English into Ted's own, which is
        why this asserts the substance rather than the sentence.
        """
        text = gates.DISCLOSURE_MESSAGE
        self.assertIn(gates.PRIVACY_URL, text)
        for kept in ("profile", "messages", "plans", "logs", "uploads"):
            with self.subTest(kept=kept):
                self.assertIn(kept, text)
        self.assertIn("delete my data", text)

    def test_the_scan_still_recognises_the_old_disclosure(self) -> None:
        """Every transcript before 4 Sep carries the old sentence.

        The durable record answers this for anyone who has one. For anyone
        who does not, losing the old wording would re-disclose them forever.
        """
        old_wording = (
            "Ted stores your profile, messages, plans, logs and uploads. "
            f"Read more: {gates.PRIVACY_URL}. Send \u201cdelete my data\u201d "
            "anytime to delete everything."
        )
        for text in (old_wording, gates.DISCLOSURE_MESSAGE):
            with self.subTest(text=text[:30]):
                self.assertTrue(
                    gates._disclosure_was_sent([message("assistant", text)])
                )


class NoAssistantSpeakTest(unittest.TestCase):
    """The furniture that makes a message read as a chatbot.

    On 2 Sep a real user got a markdown nutrient table — bold heading, bullet
    rows, "Let me know if there's anything else you need!" on the end. SOUL.md
    describes Ted's voice in adjectives and then spends forty-five rules on
    what Ted must never claim; adjectives lose that argument, and they lose to
    twenty protected examples of the model's own last twenty replies. Code
    cannot write warmth. It can take the furniture off.
    """

    def strip(self, text: str) -> str:
        return gates.strip_assistant_speak(text)

    def test_the_real_2_sep_message(self) -> None:
        out = self.strip(
            "Got it! Let's adjust the breakdown for just 1 Ragi Roti:\n\n"
            "**Nutrient Breakdown**\n"
            "- Ragi Roti (1) - Calories: ~105\n"
            "- Dal (1 cup) - Calories: ~120\n\n"
            "Let me know if there's anything else you need!"
        )
        self.assertNotIn("**", out)
        self.assertNotIn("- Ragi", out)
        self.assertNotIn("Let me know", out)
        # The content survives; only the packaging goes.
        self.assertIn("Ragi Roti", out)
        self.assertIn("~105", out)

    def test_the_closers_that_are_never_ted(self) -> None:
        for closer in (
            "Let me know if there's anything else!",
            "let me know if you need anything.",
            "I'd be happy to help with that.",
            "Feel free to reach out.",
            "Hope this helps!",
            "Is there anything else I can help with?",
        ):
            with self.subTest(closer=closer):
                self.assertEqual(self.strip(f"logged that 👍\n{closer}"), "logged that 👍")

    def test_markdown_furniture_goes_and_words_stay(self) -> None:
        for raw, expected in (
            ("## Your day", "Your day"),
            ("- sprouts bowl", "sprouts bowl"),
            ("* sprouts bowl", "sprouts bowl"),
            ("1. sprouts bowl", "sprouts bowl"),
            ("**protein** is fine", "protein is fine"),
            ("__protein__ is fine", "protein is fine"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.strip(raw), expected)

    def test_ordinary_ted_is_left_completely_alone(self) -> None:
        for said in (
            "ooh cheela and ketchup 😍 proper breakfast food",
            "arre it happens, yesterday's gone. one meal today and we're square",
            "core and cardio, nice 💪 logged it for yesterday",
            "can't read PDFs yet 😅 screenshot it?",
            "want me to remind you at 8?",
        ):
            with self.subTest(said=said):
                self.assertEqual(self.strip(said), said)

    def test_a_hyphen_mid_sentence_is_not_a_bullet(self) -> None:
        self.assertEqual(
            self.strip("logged - that's 2 meals today"),
            "logged - that's 2 meals today",
        )

    def test_a_real_sentence_containing_a_closer_word_survives(self) -> None:
        """Whole-sentence match, so this is not swept up."""
        said = "let me know your weight when you get a chance and i'll set a target"
        self.assertEqual(self.strip(said), said)

    def test_a_reply_that_is_only_furniture_is_not_emptied(self) -> None:
        """Sending nothing is worse than sending something over-polished."""
        self.assertNotEqual(self.strip("Let me know if there's anything else!"), "")

    def test_it_runs_on_every_reply_not_just_gated_ones(self) -> None:
        out = transform_response(
            history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="what did i have today?",
            response_text="here you go:\n\n- sprouts bowl\n\nLet me know if there's anything else!",
            user_key="whatsapp:sha256:voice",
        )
        self.assertIsNotNone(out)
        self.assertNotIn("Let me know", out)
        self.assertNotIn("- sprouts", out)
        self.assertIn("sprouts bowl", out)

    def test_a_clean_reply_still_returns_none(self) -> None:
        """None means "leave it alone", and a reply needing nothing must not
        start reporting itself as replaced on every single turn."""
        self.assertIsNone(
            transform_response(
                history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message="hey",
                response_text="hey! how's the day going?",
                user_key="whatsapp:sha256:voice",
            )
        )


class TheDayLineIsWrittenOnceTest(unittest.TestCase):
    """"Daily Overview:" arrived between Ted's sentence and the block.

    3 Sep, 17:36. The block already said "day so far 670 cal, 28g protein"
    two lines below it. It was not caught by the figure strip because it
    carries no kcal and no grams, so what reached the phone read like a
    person and a dashboard talking over each other.
    """

    MEAL = {
        "calories": 250,
        "proteinGrams": 8,
        "carbohydrateGrams": 30,
        "fatGrams": 10,
        "fiberGrams": 4,
    }
    DAY = {"calories": 670, "proteinGrams": 28}

    def test_the_real_17_36_reply(self) -> None:
        out = gates._with_meal_breakdown(
            "that veggie peanut toast is a nice light one, decent crunch and "
            "fiber from the peanuts 👍\nToday · 3 meals",
            self.MEAL,
            self.DAY,
        )
        self.assertIn("veggie peanut toast", out)
        # The model's own day line goes; the block's heading is the only one.
        self.assertNotIn("Today · 3 meals", out)
        self.assertEqual(out.count("Daily Overview"), 1)

    def test_the_shapes_a_model_reaches_for(self) -> None:
        for said in (
            "Daily Overview:",
            "Today: 2 meals logged",
            "today — 4 meals",
            "you're at 3 meals now",
            "day so far 670 cal",
        ):
            with self.subTest(said=said):
                self.assertEqual(gates.words_without_figures(said), "")

    def test_an_ordinary_sentence_starting_with_today_survives(self) -> None:
        for said in (
            "today's been a solid one",
            "today you actually hit it",
        ):
            with self.subTest(said=said):
                self.assertEqual(gates.words_without_figures(said), said)


class TheVoiceRidesOnEveryTurnTest(unittest.TestCase):
    """SOUL.md is six hundred lines from where the reply is written.

    Compression protects the last twenty messages verbatim, so twenty
    examples of flat output sit beside generation while the adjectives sit
    far away. SOUL.md lost that fight twice on 3 Sep. Stripping furniture
    cannot win it either — that is subtraction, and nobody subtracts their
    way to a personality. A few examples, nearer, is the only thing that
    competes with twenty examples.
    """

    def test_it_is_examples_not_adjectives(self) -> None:
        """Adjectives are what already failed."""
        self.assertGreaterEqual(gates.VOICE_CARD.count('"'), 12)

    def test_it_carries_the_real_failures_as_the_never_list(self) -> None:
        for tell in (
            "Let me know if there's anything else",
            "Daily Overview:",
            "Perfect!",
        ):
            with self.subTest(tell=tell):
                self.assertIn(tell, gates.VOICE_CARD)

    def test_it_tells_the_model_the_numbers_are_not_its_job(self) -> None:
        """The one instruction that stops a sentence being deleted with the
        figures it was wrapped around."""
        self.assertIn("appended under your reply by code", gates.VOICE_CARD)

    def test_it_stays_short_enough_to_pay_for_every_turn(self) -> None:
        """It rides on every message, so it is charged for on every message."""
        self.assertLess(len(gates.VOICE_CARD), 1800)

    def test_its_own_examples_would_survive_the_gates(self) -> None:
        """A card whose examples the gate would strip is teaching the model
        to write things that get deleted."""
        for line in gates.VOICE_CARD.splitlines():
            said = line.strip().strip('"')
            if not said.startswith(("ooh", "core and", "arre", "can't", "sprouts")):
                continue
            with self.subTest(said=said):
                self.assertEqual(gates.strip_assistant_speak(said), said)


class HermesPatchesAreCheckedOnEveryBootTest(unittest.TestCase):
    """Six of Ted's fixes live outside this repo and can vanish silently.

    `hermes update` stashes local changes, pulls, and re-applies; when that
    conflicts it resets hard and leaves the work in a stash. Nothing is
    destroyed and nothing says so — the gateway just goes back to leaking
    model names into WhatsApp and announcing every deploy to whoever is
    mid-conversation. `npm run gates:guard` has always caught it, and relied
    on somebody remembering to run it after an upgrade.
    """

    def test_the_shared_definition_is_readable_and_populated(self) -> None:
        payload = json.loads(gates._PATCH_DATA.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload["patches"]), 6)
        for patch in payload["patches"]:
            with self.subTest(patch=patch["file"]):
                self.assertTrue(patch["what"])
                self.assertTrue(patch["checks"])

    def test_the_guard_script_and_the_gate_read_the_same_file(self) -> None:
        """Two definitions would eventually disagree about whether Ted is
        patched, and the quiet one would be the one that mattered."""
        guard = Path("scripts/hermes-patch-guard.py").read_text(encoding="utf-8")
        self.assertIn("patches.json", guard)
        self.assertTrue(gates._PATCH_DATA.name == "patches.json")

    def test_a_dropped_patch_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gateway").mkdir()
            (root / "gateway" / "run.py").write_text("nothing ted asked for")
            with patch.object(gates, "_HERMES_AGENT", root):
                missing = gates._missing_hermes_patches()
        self.assertTrue(missing)

    def test_a_reverted_patch_is_reported_even_with_the_new_string_present(
        self,
    ) -> None:
        """An `absent` string coming back is a revert, however much else
        survived — a half-restored file must not read as applied."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gateway").mkdir()
            (root / "gateway" / "run.py").write_text(
                "one sec, finishing the last one first\n"
                "suppressing gateway shutdown notice\n"
                "⚡ Interrupting current task\n"
            )
            with patch.object(gates, "_HERMES_AGENT", root):
                missing = gates._missing_hermes_patches()
        self.assertIn("the busy/interrupt acknowledgements in Ted's voice", missing)

    def test_a_missing_hermes_checkout_is_not_an_error(self) -> None:
        """Absent files are skipped. A boot must not fail over this."""
        with TemporaryDirectory() as tmp:
            with patch.object(gates, "_HERMES_AGENT", Path(tmp)):
                self.assertEqual(gates._missing_hermes_patches(), [])

    def test_unreadable_patch_data_is_not_an_error_either(self) -> None:
        with patch.object(gates, "_PATCH_DATA", Path("/nope/patches.json")):
            self.assertEqual(gates._missing_hermes_patches(), [])

    def test_the_live_machine_is_currently_patched(self) -> None:
        """Not a unit test — a check on this machine, which is the point."""
        if not gates._HERMES_AGENT.exists():
            self.skipTest("no Hermes checkout on this machine")
        self.assertEqual(gates._missing_hermes_patches(), [])


# The real inbound strings from the failed 3 Sep 22:51-22:59 session, copied
# out of ~/.hermes/logs/agent.log rather than imagined. `[Replying to: "..."]`
# is gateway/run.py:12057; the quoted body is the message it was a reply to.
QUOTED_DISCLOSURE_PRAISE = (
    '[Replying to: "hey UD \U0001f642\n\n'
    "Ted stores your profile, messages, plans, logs and uploads. Read more: "
    "https://heyted.vercel.app/privacy. Send “delete my data” anytime to "
    "delete everything.\n\n"
    'what’s one thing you want to change?"]\n\n'
    "i love this. this is a really good thing about security you've done"
)
QUOTED_NAME_QUESTION = (
    '[Replying to: "hey \U0001f44b what should i call you?"]\n\n'
    "this should have some personality like, i don't know what you're saying "
    "i think you're confusing me with someone else or something like a more "
    "human personality"
)


class QuotedTextCannotTriggerAnythingTest(unittest.TestCase):
    """The bug that erased a real account.

    22:58:41 on 3 Sep: a tester replied to the privacy disclosure with praise.
    Hermes prepends the quoted message to the user's turn, so the string that
    reached `_asks_to_delete` opened with Ted's own sentence, 'Send "delete my
    data" anytime to delete everything.' The regex matched inside the quote,
    22:58:44 logged `ted_delete_confirmation_asked`, the tester typed the word
    Ted had just asked for, and 22:59:03 logged
    `ted_user_data_deleted ... users: 1`. "no wait" arrived five seconds late.
    """

    USER_KEY = "quoted-intent-test"

    def setUp(self) -> None:
        reset_user(self.USER_KEY)
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)

    def tearDown(self) -> None:
        reset_user(self.USER_KEY)
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)

    def test_the_newest_text_is_what_is_read(self) -> None:
        self.assertEqual(
            gates._user_written_text(QUOTED_DISCLOSURE_PRAISE),
            "i love this. this is a really good thing about security you've done",
        )

    def test_praise_for_the_disclosure_does_not_ask_to_delete(self) -> None:
        self.assertFalse(gates._asks_to_delete(QUOTED_DISCLOSURE_PRAISE))

    def test_the_whole_turn_does_not_open_a_deletion(self) -> None:
        gates._mark_disclosure_sent(self.USER_KEY)
        gates._remember_name(self.USER_KEY, "UD")
        reply = transform_response(
            history=[
                message("assistant", f"hey UD \U0001f642\n\n{DISCLOSURE_MESSAGE}"),
                message("user", QUOTED_DISCLOSURE_PRAISE),
            ],
            user_message=QUOTED_DISCLOSURE_PRAISE,
            response_text="glad it makes sense \U0001f642",
            user_key=self.USER_KEY,
        )
        self.assertNotEqual(reply, gates.DELETE_CONFIRMATION_QUESTION)
        self.assertFalse(gates._delete_is_pending(self.USER_KEY))

    def test_a_real_request_still_opens_one(self) -> None:
        """The gate must not have been turned off, only pointed at the user."""
        gates._mark_disclosure_sent(self.USER_KEY)
        self.assertEqual(
            transform_response(
                history=[message("user", "delete my data")],
                user_message="delete my data",
                response_text="sure",
                user_key=self.USER_KEY,
            ),
            gates.DELETE_CONFIRMATION_QUESTION,
        )

    def test_a_quoted_question_is_not_the_users_answer(self) -> None:
        """`_given_name` reads the user turn after a name question."""
        self.assertEqual(
            gates._user_written_text(QUOTED_NAME_QUESTION),
            "this should have some personality like, i don't know what you're "
            "saying i think you're confusing me with someone else or something "
            "like a more human personality",
        )
        history = [
            message("assistant", "hey \U0001f44b what should i call you?"),
            message("user", QUOTED_NAME_QUESTION),
        ]
        self.assertIsNone(gates._given_name(history, self.USER_KEY))

    def test_a_photo_of_the_words_cannot_delete_an_account(self) -> None:
        """A vision description is text the user did not write either."""
        seen = (
            "[The user sent an image~ Here's what I can see:\n"
            "A screenshot of a chat. The message reads: delete my data]\n\n"
            "is this the right screenshot?"
        )
        self.assertFalse(gates._asks_to_delete(seen))
        self.assertEqual(gates._user_written_text(seen), "is this the right screenshot?")

    def test_a_note_that_never_closes_fails_closed(self) -> None:
        """Text we cannot parse must not be able to answer an erasure."""
        broken = '[Replying to: "delete my data'
        self.assertEqual(gates._user_written_text(broken), "")
        self.assertFalse(gates._asks_to_delete(broken))

    def test_a_transcript_is_the_user_writing(self) -> None:
        """Voice notes arrive as a bare quoted line and must survive intact."""
        spoken = '"delete my data"'
        self.assertEqual(gates._user_written_text(spoken), '"delete my data"')
        self.assertTrue(gates._asks_to_delete(spoken))

    def test_an_ordinary_bracket_is_left_alone(self) -> None:
        self.assertEqual(gates._user_written_text("[maybe] paneer"), "[maybe] paneer")

    def test_the_document_note_still_reaches_its_own_gate(self) -> None:
        """`unreadable_document_gate` is the one gate that reads a note."""
        note = (
            "[The user sent a document: 'plan.pdf'. It is saved at: /tmp/p.pdf. "
            "Its text is not inlined here (it's a binary format such as PDF or "
            "DOCX).]\n\nset my calories from this"
        )
        gates._mark_disclosure_sent(self.USER_KEY)
        self.assertEqual(
            transform_response(
                history=[message("assistant", DISCLOSURE_MESSAGE)],
                user_message=note,
                response_text="your target is 1800 calories.",
                user_key=self.USER_KEY,
            ),
            gates.UNREADABLE_DOCUMENT_REPLY,
        )


class FeedbackIsNotAnAnswerTest(unittest.TestCase):
    """A name is a noun phrase, not a sentence about Ted.

    The old rule was "40 characters or fewer". "keep it short" is thirteen,
    and Ted would have greeted this person as "keep it short" every morning
    after that.
    """

    def test_feedback_is_not_taken_as_a_name(self) -> None:
        for feedback in (
            "that's a good start vandana, but keep it short",
            "i like this as well. it's just a smaller feedback",
            "keep it short",
            "make it more human",
            "this should have some personality",
            "i think you should look at how poke.com does onboarding",
        ):
            with self.subTest(feedback=feedback):
                self.assertIsNone(gates._clean_name(feedback))

    def test_real_names_still_land(self) -> None:
        for given, expected in (
            ("UD", "UD"),
            ("Vandana", "Vandana"),
            ("i'm Vandy", "Vandy"),
            ("call me V", "V"),
            ("just call me UD", "UD"),
            ("my name is Priya Sharma", "Priya Sharma"),
            ("Dr Ankit", "Dr Ankit"),
            # Kept explicitly: the allowlist must not become an English filter.
            ("Dr. Ankit", "Dr. Ankit"),
            ("O'Brien", "O'Brien"),
            ("Jean-Luc", "Jean-Luc"),
            ("Ana María", "Ana María"),
            ("जया", "जया"),
        ):
            with self.subTest(given=given):
                self.assertEqual(gates._clean_name(given), expected)

    def test_anything_that_is_not_a_name_is_refused(self) -> None:
        """Every one of these was accepted and used as somebody's name.

        The old test asked whether the answer matched a list of sentences we
        had thought of. These are the ones we had not: an attachment
        placeholder, a dodge, an age, a workout, a goal. Each was stored and
        spoken back to a real person between 3 and 4 Sep 2026.
        """
        for text, why in (
            ("[image received]", "attachment placeholder"),
            ("[ptt received]", "voice note placeholder"),
            ("Kuch bi yaar", "a dodge, not a person"),
            ("31", "an age answering the wrong question"),
            ("and 20 min run", "a workout"),
            ("weight and healthy lifestyle", "a goal"),
            ("Can I send you voice notes", "a question, transcribed without the ?"),
            ("we will discuss pos15th sept", "a deferral"),
            ("nudge me on 15th sept", "a request"),
            ("You tell me", "a dodge"),
            ("whatever", "a dodge"),
            ("2 rotis and dal", "a meal"),
        ):
            with self.subTest(text=text, why=why):
                self.assertIsNone(gates._clean_name(text))


class TheProfileIsReadBackFirstTest(unittest.TestCase):
    """No calorie number until the profile has been said back once.

    The per-field check catches doubt Ted can see — a hedge, a range, a unit.
    It cannot catch a confident misread. On 4 Sep "5 feet 4 and a half inches"
    parsed cleanly to 152.4 cm and produced 1,520 instead of 1,610, inside the
    sentence that promises it used only her numbers. One glance at her own
    numbers would have caught it; nothing in the gate would.
    """

    FULL = [message("user", "i am 31, female, 164 cm, 63.5 kg, sedentary")]

    def test_the_summary_comes_before_the_number(self) -> None:
        key = "whatsapp:sha256:sum1"

        reply = calorie_gate(
            self.FULL, "what's my calorie target?",
            "let's start from maintenance.", user_key=key
        )

        self.assertNotIn("maintenance", reply or "")
        self.assertIn("31", reply or "")
        self.assertIn("female", reply or "")
        self.assertIn("164 cm", reply or "")
        self.assertIn("63.5 kg", reply or "")
        self.assertIn("desk", reply or "")
        self.assertIn("anything off", reply or "")

    def test_agreeing_either_way_round_releases_the_number(self) -> None:
        """"anything off?" is answered by both "yes" and "no"."""
        for agreement in ("yes", "no", "all good", "looks right", "nope"):
            with self.subTest(agreement=agreement):
                key = f"whatsapp:sha256:agree{agreement}"
                first = calorie_gate(
            self.FULL, "what's my calorie target?",
            "let's start from maintenance.", user_key=key
        )
                history = self.FULL + [message("assistant", first)]

                reply = calorie_gate(
                    history, agreement, "let's start from maintenance.",
                    user_key=key
                )

                self.assertIn("1,610", reply or "")
                self.assertNotIn("deficit", reply or "")

    def test_a_correction_shows_the_summary_again(self) -> None:
        key = "whatsapp:sha256:sumfix"
        first = calorie_gate(
            self.FULL, "what's my calorie target?",
            "let's start from maintenance.", user_key=key
        )
        history = self.FULL + [
            message("assistant", first),
            message("assistant", "and your weight? i only work from numbers you give me."),
        ]

        reply = calorie_gate(
            history, "70 kg", "let's start from maintenance.", user_key=key
        )

        self.assertIn("anything off", reply or "")
        self.assertIn("70 kg", reply or "")
        self.assertNotIn("maintenance", reply or "")

    def test_the_summary_is_not_repeated_once_agreed(self) -> None:
        key = "whatsapp:sha256:once"
        first = calorie_gate(
            self.FULL, "what's my calorie target?",
            "let's start from maintenance.", user_key=key
        )
        history = self.FULL + [message("assistant", first)]
        calorie_gate(
            history, "yes", "let's start from maintenance.", user_key=key
        )

        again = calorie_gate(
            history, "what's my calorie target again?",
            "let's start from maintenance.", user_key=key
        )

        self.assertIn("1,610", again or "")
        self.assertNotIn("anything off", again or "")

    def test_a_minor_never_reaches_the_summary(self) -> None:
        """The under-18 refusal sits above all of this and stays there."""
        minor = [message("user", "i am 15, female, 164 cm, 63.5 kg, sedentary")]

        reply = calorie_gate(
            minor, "what's my calorie target?",
            "let's start from maintenance.", user_key="whatsapp:sha256:kid"
        )

        self.assertEqual(reply, gates.UNDER_18_REFUSAL)


class LaterMeansLaterTest(unittest.TestCase):
    """A deferral stops the questions and the scheduler both.

    Jaya, 4 Sep: "nudge me on 15th sept and then we can start the routine" at
    11:00, "we will discuss pos15th sept" at 11:02. Between and after them Ted
    asked four more onboarding questions, because acknowledging a deferral and
    then asking anyway was all it knew how to do.
    """

    def test_her_actual_words_read_as_a_deferral(self) -> None:
        for text in (
            "nudge me on 15th sept and then we can start the routine",
            "we will discuss pos15th sept",
            "lets talk next week",
            "can we pick this up tomorrow",
            "not right now",
        ):
            with self.subTest(text=text):
                self.assertTrue(gates._asks_to_defer(text))

    def test_an_ordinary_reminder_request_is_not_a_deferral(self) -> None:
        """"remind me at 8pm" wants a nudge, not silence."""
        for text in (
            "remind me at 8pm",
            "what did i eat today",
            "ping me tomorrow morning about water",
        ):
            with self.subTest(text=text):
                self.assertFalse(gates._asks_to_defer(text))

    def test_the_date_is_parsed_not_kept_as_words(self) -> None:
        """A pause held as "15th sept" can never end, so it drops the person."""
        today = date(2026, 9, 4)
        for text in (
            "nudge me on 15th sept and then we can start the routine",
            "we will discuss pos15th sept",
            "sept 15",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    gates._defer_until_date(text, today), date(2026, 9, 15)
                )

    def test_the_reply_says_it_back_and_asks_nothing(self) -> None:
        reply = gates._deferral_reply(date(2026, 9, 15))
        self.assertIn("15th Sep", reply)
        self.assertNotIn("?", reply)

    def test_a_pause_expires_on_its_own(self) -> None:
        key = "whatsapp:sha256:paused"
        gates._mark_paused(key, date(2026, 9, 15))
        self.assertEqual(gates._paused_until(key, date(2026, 9, 10)), "2026-09-15")
        self.assertIsNone(gates._paused_until(key, date(2026, 9, 15)))
        self.assertIsNone(gates._paused_until(key, date(2026, 9, 20)))


class APromiseWithATimeInItTest(unittest.TestCase):
    """A confirmation carrying a time is a scheduling claim.

    Two real users were told something was set that was not. Pradosh, 3 Sep
    16:39: "got it, 9am morning check-in it is" — no tool ran. Jaya, 4 Sep
    11:01 and 11:03: "sure, 15th it is" and "I'll catch you on the 15th" —
    nothing scheduled, and on the 15th she will hear nothing. Neither sentence
    had a save verb for the old patterns to find.
    """

    def test_a_confirmation_with_a_time_is_a_claim(self) -> None:
        for text in (
            "got it, 9am morning check-in it is. evening one stays at 10pm",
            "sure, 15th it is 📅 but tell me, what's this routine for",
            "alright, that's onboarding sorted for now, I'll catch you on the 15th",
            "koi na, we'll sort the details on the 15th 🙌",
            "tomorrow it is",
        ):
            with self.subTest(text=text):
                self.assertIn("cron", gates._claim_types(text))

    def test_a_confirmation_about_anything_else_is_not(self) -> None:
        """The time is what makes it a promise. Without one it is just agreeing."""
        for text, why in (
            ("black it is, we're good then 👍", "Jaya, about coffee"),
            ("150g it is, updated 👍", "Wellness Monk, about dal"),
            ("consistency it is, that's the one that moves the needle", "a goal"),
            ("catch you later yaar", "a sign-off with no when"),
            ("chalo, deal 🤝 phone charging outside the room tonight, karega?", "a nudge to them"),
        ):
            with self.subTest(text=text, why=why):
                self.assertNotIn("cron", gates._claim_types(text))


class BeSureOrAskTest(unittest.TestCase):
    """A measurement is kept only when the answer was a settled fact.

    On 4 Sep 2026 the weight question accepted, silently and as current fact:
    "around 60-65" (60), "63 or 64, not sure" (63), "i was 70 last year" (70),
    "goal is 59" (59) — a target read as a current weight — and "154 lbs",
    stored as 154 kg, which roughly doubles the maintenance figure.

    The model's reading of the sentence is not what gets stored. This parse
    is. So the doubt has to surface here.
    """

    BASE = [
        message("user", "i am 31, female, 164 cm, sedentary, calorie target?"),
        message("assistant", "and your weight? i only work from numbers you give me."),
    ]

    def ask(self, answer, user_key):
        return calorie_gate(self.BASE, answer, "sure.", user_key=user_key)

    def test_a_clean_answer_is_not_second_guessed(self) -> None:
        """Confirming everything is its own kind of pestering.

        A clean answer goes straight to the whole-profile summary. It does not
        earn its own extra round trip first.
        """
        for answer in ("63.5 kg", "63", "63.5kgs"):
            with self.subTest(answer=answer):
                reply = self.ask(answer, f"whatsapp:sha256:clean{answer}")
                self.assertIn("anything off", reply or "")
                self.assertNotIn("confirming", reply or "")

    def test_a_hedged_number_is_read_back_before_it_is_kept(self) -> None:
        for answer, shown in (
            ("around 60-65", "60"),
            ("63 or 64, not sure", "63"),
            ("i was 70 last year", "70"),
            ("goal is 59", "59"),
            ("70 but after lunch", "70"),
        ):
            with self.subTest(answer=answer):
                key = f"whatsapp:sha256:hedge{answer}"
                reply = self.ask(answer, key)
                self.assertIn(shown, reply or "")
                self.assertIn("confirming", reply or "")
                self.assertNotIn("maintenance", reply or "")
                # Nothing is filed until they say yes.
                self.assertIsNone(gates._stored_measurement(key, "weight_kg"))

    def test_pounds_and_stone_are_converted_and_declared(self) -> None:
        for answer in ("154 lbs", "154 pounds", "11 stone"):
            with self.subTest(answer=answer):
                reply = self.ask(answer, f"whatsapp:sha256:conv{answer}")
                self.assertIn("69.9 kg", reply or "")
                self.assertNotIn("154", reply or "")

    def test_a_yes_commits_the_number(self) -> None:
        key = "whatsapp:sha256:yes"
        first = self.ask("154 lbs", key)
        history = self.BASE + [
            message("user", "154 lbs"), message("assistant", first)
        ]

        reply = calorie_gate(history, "yes", "sure.", user_key=key)

        self.assertEqual(gates._stored_measurement(key, "weight_kg"), 69.9)
        # The converted figure is carried into the summary, with its origin.
        self.assertIn("69.9 kg", reply or "")
        self.assertIn("154 lbs", reply or "")

    def test_a_correction_replaces_the_doubted_number(self) -> None:
        """The doubted value must not survive in the transcript and win."""
        for correction, expected in (
            ("no, 63", 63.0),
            ("63 kg", 63.0),
            ("no it's 65", 65.0),
        ):
            with self.subTest(correction=correction):
                key = f"whatsapp:sha256:corr{correction}"
                first = self.ask("around 60-65", key)
                history = self.BASE + [
                    message("user", "around 60-65"),
                    message("assistant", first),
                ]

                calorie_gate(history, correction, "ok.", user_key=key)

                self.assertEqual(
                    gates._stored_measurement(key, "weight_kg"), expected
                )

    def test_neither_a_yes_nor_a_number_keeps_nothing(self) -> None:
        key = "whatsapp:sha256:nope"
        first = self.ask("around 60-65", key)
        history = self.BASE + [
            message("user", "around 60-65"), message("assistant", first)
        ]

        reply = calorie_gate(history, "nope", "ok.", user_key=key)

        self.assertIsNone(gates._stored_measurement(key, "weight_kg"))
        self.assertIn("your weight", reply or "")

    def test_the_confirmation_names_the_field_it_is_about(self) -> None:
        """Otherwise the correction under it is anchored to no question."""
        self.assertIn(
            "weight", gates._confirm_measurement_reply("weight_kg", 70, None)
        )
        self.assertIn(
            "height", gates._confirm_measurement_reply("height_cm", 164, None)
        )

    def test_a_hedge_far_from_any_number_is_not_a_hedged_answer(self) -> None:
        """"what's my calorie target?" contains "target" and hedges nothing."""
        self.assertFalse(
            gates._answer_is_uncertain("what should my calorie target be?")
        )
        self.assertFalse(gates._answer_is_uncertain("i want to lose 5kg fast"))
        self.assertTrue(gates._answer_is_uncertain("goal is 59"))

    def test_a_measurement_survives_the_next_turn(self) -> None:
        """Given once should not mean asked twice — the window compacts."""
        key = "whatsapp:sha256:persist"
        calorie_gate(self.BASE, "63.5 kg", "sure.", user_key=key)
        self.assertEqual(gates._stored_measurement(key, "weight_kg"), 63.5)

    def test_erasure_clears_the_kept_measurements(self) -> None:
        key = "whatsapp:sha256:wipe"
        calorie_gate(self.BASE, "63.5 kg", "sure.", user_key=key)
        gates._forget_user(key)
        self.assertIsNone(gates._stored_measurement(key, "weight_kg"))


class TheNameIsAskedOnceTest(unittest.TestCase):
    """22:57:45 "hey 👋 what should i call you?" and 22:57:52 "cool, glad it
    landed 🙂 so, what should i call you?" — the same question, seven seconds
    apart, with feedback in between and "UD" arriving on top of it.
    """

    USER_KEY = "one-name-ask-test"

    def setUp(self) -> None:
        reset_user(self.USER_KEY)

    def tearDown(self) -> None:
        reset_user(self.USER_KEY)

    def test_the_reaction_survives_and_the_repeat_question_goes(self) -> None:
        history = [
            message("assistant", "hey \U0001f44b what should i call you?"),
            message("user", "i like this as well. it's just a smaller feedback"),
        ]
        self.assertEqual(
            gates.repeat_name_ask_gate(
                history,
                "cool, glad it landed \U0001f642 so, what should i call you?",
                self.USER_KEY,
            ),
            "cool, glad it landed \U0001f642",
        )

    def test_the_first_ask_is_left_alone(self) -> None:
        self.assertIsNone(
            gates.repeat_name_ask_gate(
                [message("user", "hi")],
                "hey \U0001f44b what should i call you?",
                self.USER_KEY,
            )
        )

    def test_an_answered_question_is_never_asked_again(self) -> None:
        gates._remember_name(self.USER_KEY, "UD")
        self.assertEqual(
            gates.repeat_name_ask_gate(
                [message("user", "UD")],
                "arre nice one, that's a solid start. so what should i call you?",
                self.USER_KEY,
            ),
            "arre nice one, that's a solid start.",
        )

    def test_a_two_word_fragment_is_not_a_reply(self) -> None:
        """"nice one." on its own is not worth sending. Answer instead."""
        gates._remember_name(self.USER_KEY, "UD")
        self.assertEqual(
            gates.repeat_name_ask_gate(
                [message("user", "UD")],
                "nice one. so what should i call you?",
                self.USER_KEY,
            ),
            "you\u2019re UD \U0001f642",
        )

    def test_the_opener_counts_as_an_ask_even_though_the_transcript_hides_it(
        self,
    ) -> None:
        """Hermes records the model's text, not the opener the gate sent."""
        gates._record_name_ask(self.USER_KEY)  # the opener
        gates._record_name_ask(self.USER_KEY)  # one re-ask
        gates._record_name_ask(self.USER_KEY)  # and a third
        transcript_shows_no_question = [message("assistant", "hi there")]
        self.assertEqual(
            gates.repeat_name_ask_gate(
                transcript_shows_no_question,
                "right, sorry about that. what should i call you?",
                self.USER_KEY,
            ),
            "right, sorry about that.",
        )

    def test_a_bare_repeat_to_a_known_name_is_replaced_not_blanked(self) -> None:
        """Hermes reads "" as "leave the model's text alone"."""
        gates._remember_name(self.USER_KEY, "UD")
        reply = gates.repeat_name_ask_gate(
            [message("user", "UD")], "what should i call you?", self.USER_KEY
        )
        self.assertTrue(reply)
        self.assertNotIn("call you", reply or "")

    def test_a_turn_overtaken_by_a_newer_message_asks_nothing(self) -> None:
        """The reply was written before the answer arrived. It must not ask."""
        self.assertEqual(
            gates.repeat_name_ask_gate(
                [message("user", "hi")],
                "cool cool. so what should i call you?",
                self.USER_KEY,
                stale_turn=True,
            ),
            "cool cool.",
        )

    def test_arrival_order_is_tracked_per_user(self) -> None:
        first = gates._record_turn_arrival(self.USER_KEY)
        self.assertFalse(gates._turn_is_stale(self.USER_KEY, first))
        gates._record_turn_arrival(self.USER_KEY)
        self.assertTrue(gates._turn_is_stale(self.USER_KEY, first))
        other = gates._record_turn_arrival("someone-else-entirely")
        self.assertFalse(gates._turn_is_stale("someone-else-entirely", other))
        gates._TURN_ARRIVALS.pop("someone-else-entirely", None)


class ATalkingPointIsNotAFailedActionTest(unittest.TestCase):
    """22:58:30: "i think you should really really look at how poke.com does
    onboarding it's really good" was answered with "i couldn't get that done
    just now, try me again in a minute?" — an outage notice for a remark about
    a website. Nothing had been asked for and nothing had broken.
    """

    def test_a_suggestion_does_not_read_as_an_outage(self) -> None:
        reply = action_claim_gate(
            "noted, i'll remember that.", user_asked_for_action=False
        )
        self.assertEqual(reply, gates.CLAIM_NOTHING_TO_SAVE)
        self.assertNotEqual(reply, gates.CLAIM_NOT_DONE)

    def test_an_actual_request_still_says_it_failed(self) -> None:
        self.assertEqual(
            action_claim_gate("noted, i'll remember that.", user_asked_for_action=True),
            gates.CLAIM_NOT_DONE,
        )

    def test_a_storage_outage_still_wins_either_way(self) -> None:
        self.assertEqual(
            action_claim_gate(
                "noted, i'll remember that.",
                storage_failed=True,
                user_asked_for_action=False,
            ),
            gates.STORAGE_NOT_SAVED,
        )

    def test_what_counts_as_asking_for_an_action(self) -> None:
        for text, expected in (
            ("i think you should look at how poke.com does onboarding", False),
            ("i love this. this is a really good thing about security", False),
            ("remember that i'm vegetarian", True),
            ("remind me at 8pm", True),
            ("set my protein target to 120", True),
            ("delete my data", True),
        ):
            with self.subTest(text=text):
                self.assertIs(gates._asks_for_an_action(text), expected)


class OnboardingAdvancesOnceTest(unittest.TestCase):
    """The three messages, in order, each sent once.

    Also the thing that must not happen: an existing user greeted as a
    stranger. Every branch that could reset somebody is asserted here.
    """

    USER_KEY = "onboarding-advances-once"

    def setUp(self) -> None:
        reset_user(self.USER_KEY)
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)
        self.history: list[dict[str, str]] = []

    def tearDown(self) -> None:
        reset_user(self.USER_KEY)
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)

    def turn(self, user_text: str, model_reply: str) -> str:
        self.history.append(message("user", user_text))
        gated = transform_response(
            history=list(self.history),
            user_message=user_text,
            response_text=model_reply,
            user_key=self.USER_KEY,
        )
        reply = model_reply if gated is None else gated
        self.history.append(message("assistant", reply))
        return reply

    def test_any_first_message_gets_one_greeting_and_one_question(self) -> None:
        for opener in ("Okay Ted, let's do this", "hi", "i want to lose weight"):
            with self.subTest(opener=opener):
                reset_user(self.USER_KEY)
                gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)
                self.history = []
                self.assertEqual(
                    self.turn(opener, "hello there, let me tell you all about me"),
                    OPENING_MESSAGE,
                )

    def test_the_name_brings_the_disclosure_and_question_one_once(self) -> None:
        self.turn("hi", "whatever")
        second = self.turn("UD", "nice to meet you")
        self.assertEqual(
            second,
            f"{DISCLOSURE_MESSAGE}\n\nright UD, {gates.SETUP_INTRO}\n\n"
            f"{gates._setup_question(0)}",
        )
        self.assertEqual(second.count(gates.PRIVACY_URL), 1)
        self.assertEqual(second.count("1/6"), 1)
        gates._mark_disclosure_sent(self.USER_KEY)
        third = self.turn("more energy", "good one, what time suits for a check in?")
        self.assertNotIn(gates.PRIVACY_URL, third)
        self.assertNotIn("call you", third)

    def test_feedback_does_not_advance_the_stage(self) -> None:
        self.turn("hi", "whatever")
        self.turn("keep it short, i like the lowercase", "cool, noted")
        self.assertIsNone(gates._known_name(self.USER_KEY))
        self.assertNotIn(self.USER_KEY, gates._DISCLOSURE_SENT_KEYS)

    def test_an_existing_user_is_never_greeted_as_a_stranger(self) -> None:
        for label, prepare in (
            ("name on file", lambda: gates._remember_name(self.USER_KEY, "UD")),
            (
                "disclosure on file",
                lambda: gates._mark_disclosure_sent(self.USER_KEY),
            ),
            (
                "onboarding steps on file",
                lambda: gates._update_onboarding(self.USER_KEY, done=["goal"]),
            ),
        ):
            with self.subTest(label=label):
                reset_user(self.USER_KEY)
                gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)
                prepare()
                self.assertFalse(gates._is_first_contact([], self.USER_KEY))

    def test_a_transcript_alone_is_enough_to_know_they_have_been_here(self) -> None:
        self.assertFalse(
            gates._is_first_contact(
                [message("assistant", "morning \U0001f642")], self.USER_KEY
            )
        )


class DeleteThenChangeYourMindTest(unittest.TestCase):
    """Cancelling before the confirmation must leave everything in place."""

    USER_KEY = "delete-then-cancel"

    def setUp(self) -> None:
        reset_user(self.USER_KEY)
        gates._mark_disclosure_sent(self.USER_KEY)
        gates._remember_name(self.USER_KEY, "UD")

    def tearDown(self) -> None:
        reset_user(self.USER_KEY)
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)

    def test_no_wait_closes_the_question_and_keeps_the_account(self) -> None:
        history = [message("assistant", DISCLOSURE_MESSAGE)]
        asked = transform_response(
            history=history,
            user_message="delete my data",
            response_text="ok",
            user_key=self.USER_KEY,
        )
        self.assertEqual(asked, gates.DELETE_CONFIRMATION_QUESTION)
        self.assertTrue(gates._delete_is_pending(self.USER_KEY))

        history.append(message("assistant", asked))
        transform_response(
            history=history,
            user_message="no wait",
            response_text="sure, nothing has been deleted.",
            user_key=self.USER_KEY,
        )
        self.assertFalse(gates._delete_is_pending(self.USER_KEY))
        self.assertEqual(gates._known_name(self.USER_KEY), "UD")
        self.assertIn(self.USER_KEY, gates._DISCLOSURE_SENT_KEYS)

    def test_a_later_yes_cannot_land_on_the_cancelled_question(self) -> None:
        transform_response(
            history=[message("assistant", DISCLOSURE_MESSAGE)],
            user_message="delete my data",
            response_text="ok",
            user_key=self.USER_KEY,
        )
        transform_response(
            history=[message("assistant", gates.DELETE_CONFIRMATION_QUESTION)],
            user_message="no wait",
            response_text="nothing deleted.",
            user_key=self.USER_KEY,
        )
        self.assertFalse(gates._delete_is_pending(self.USER_KEY))
        result = json.loads(
            gates._delete_user_data({"confirmed": True}, session_id="no-such-session")
        )
        self.assertFalse(result["success"])


class TheCountedFiveTest(unittest.TestCase):
    """The 4 Sep onboarding rebuild: name, then five questions, then a number.

    The old flow was reactive. It asked for height only once the model was
    already about to say a calorie number, so somebody could talk to Ted for
    days with an empty profile and then be handed four questions in a row at
    the worst possible moment. Vandy's words for the result were "people are
    a little bit in the mix".
    """

    USER_KEY = "counted-five"

    def setUp(self) -> None:
        self.reset()

    def tearDown(self) -> None:
        self.reset()

    def reset(self) -> None:
        gates._DISCLOSURE_SENT_KEYS.discard(self.USER_KEY)
        gates._forget_user(self.USER_KEY)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(self.USER_KEY, None)
        self.history: list[dict[str, str]] = []

    def turn(self, user_text: str, model_reply: str = "sure thing") -> str:
        self.history.append(message("user", user_text))
        gated = transform_response(
            history=list(self.history),
            user_message=user_text,
            response_text=model_reply,
            user_key=self.USER_KEY,
        )
        reply = model_reply if gated is None else gated
        self.history.append(message("assistant", reply))
        return reply

    def start(self) -> str:
        """Through the opener and the name, to the message carrying 1/6."""
        self.turn("hey", "hello!")
        return self.turn("Vandy", "nice to meet you")

    def through_setup(self, activity: str = "desk most of it",
                      goal: str = "lose fat") -> str:
        """Answer 5/6 and 6/6, and return the read-back that follows them."""
        self.turn(activity)
        return self.turn(goal)

    def test_five_questions_means_five(self) -> None:
        """The count is a promise, and these are the five that keep it.

        Exactly the Mifflin-St Jeor inputs, which is what makes "five
        questions" literally true rather than a rounded-down guess. A sixth
        would be a lie, so the city and the check-in time are asked later,
        when the first reminder is actually being set.
        """
        self.assertEqual(len(gates.SETUP_QUESTIONS), 6)
        self.assertEqual(
            [field for field, _ in gates.SETUP_QUESTIONS],
            ["age", "height_cm", "weight_kg", "sex", "activity", "goal"],
        )
        for index in range(6):
            with self.subTest(index=index):
                self.assertTrue(
                    gates._setup_question(index).startswith(f"*{index + 1}/6*")
                )

    def test_the_name_leads_straight_into_question_one(self) -> None:
        delivered = self.start()
        self.assertTrue(delivered.startswith(DISCLOSURE_MESSAGE))
        self.assertIn("right Vandy", delivered)
        self.assertTrue(delivered.endswith(gates._setup_question(0)))
        # The old open goal question is gone from here.
        self.assertNotIn(GOAL_QUESTION, delivered)

    def test_the_notice_never_carries_the_name(self) -> None:
        """A mis-parsed name used to land inside the privacy notice.

        "hey Can I send you voice notes 🙂" is a real one. `_clean_name` is an
        allowlist now, but the notice keeping its own message is what makes
        that structural rather than a thing the parser has to get right.
        """
        self.assertNotIn("{", DISCLOSURE_MESSAGE)
        self.assertNotIn("Vandy", DISCLOSURE_MESSAGE)
        delivered = self.start()
        notice, _, rest = delivered.partition("\n\n")
        self.assertEqual(notice, DISCLOSURE_MESSAGE)
        self.assertIn("Vandy", rest)

    def test_the_count_walks_from_one_to_five(self) -> None:
        self.start()
        for answer, expected_index in (
            ("33", 1),
            ("170cm", 2),
            ("62kg", 3),
            ("female", 4),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    self.turn(answer), gates._setup_question(expected_index)
                )

    def test_every_offered_answer_to_question_five_parses(self) -> None:
        """5/5 offers three choices, so all three have to be readable.

        People answer a multiple choice by echoing one of the choices. Until
        4 Sep none of the three parsed, which is the same mistake as asking
        for a birthday the parser cannot use.
        """
        for phrase in ("desk most of it", "on your feet", "training regularly"):
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(gates._find_activity([phrase]))

    def test_the_read_back_comes_before_the_number(self) -> None:
        """The step that would have caught Pallavi's height."""
        self.start()
        self.turn("33")
        self.turn("170cm")
        self.turn("62kg")
        self.turn("female")
        summary = self.through_setup()
        self.assertIn("here's what i've got:", summary)
        self.assertIn("170 cm", summary)
        self.assertNotIn("1,630", summary)
        payoff = self.turn("yep")
        self.assertIn("1,630", payoff)
        self.assertIn("maintenance", payoff)
        # The goal is question 6/6 now, so it is answered before here. The
        # payoff speaks to it and offers a bounded target to choose between.
        self.assertNotIn(GOAL_QUESTION, payoff)
        self.assertIn("to lose", payoff)
        # A named cut, and it is never below resting energy or the floor.
        profile = gates.CalorieProfile(
            age=33, height_cm=170, weight_kg=62, sex="female",
            activity="sedentary", goal="loseWeight",
        )
        target = gates._loss_target(profile)
        self.assertIn(f"{target:,}", payoff)
        self.assertGreaterEqual(target, gates._resting_energy(profile))
        self.assertGreaterEqual(target, gates._LOSS_FLOOR_KCAL["female"])
        self.assertLess(target, gates._estimated_maintenance(profile))

    def test_the_number_is_maintenance_and_never_a_cut(self) -> None:
        """The one thing not to take from Rex Nutribot.

        Rex drops to 80% of TDEE against a goal weight and a date. A deficit
        is the exact thing Ted must never hand anybody, so the payoff says
        what the number is and that nothing moves at it.
        """
        profile = gates.CalorieProfile(
            age=33, height_cm=170.0, weight_kg=62.0, sex="female",
            activity="sedentary",
        )
        payoff = gates._setup_payoff(profile)
        self.assertIn(f"{gates._estimated_maintenance(profile):,}", payoff)
        self.assertIn("maintenance", payoff)
        for cut in ("deficit", "lose", "target weight", "goal weight"):
            with self.subTest(cut=cut):
                self.assertNotIn(cut, payoff.lower())

    def test_a_minor_never_finishes_the_five(self) -> None:
        """The five end in a calorie number, so the refusal has to be here."""
        self.start()
        self.assertEqual(self.turn("i'm 15"), gates.UNDER_18_REFUSAL)
        self.assertNotEqual(gates._setup_state(self.USER_KEY), "running")
        # And it stays refused on the next turn.
        self.assertEqual(
            transform_response(
                history=list(self.history),
                user_message="but what's my calorie number",
                response_text="about 1,800 a day",
                user_key=self.USER_KEY,
            ),
            gates.UNDER_18_REFUSAL,
        )

    def test_a_hedged_answer_is_read_back_inside_the_flow(self) -> None:
        """Certainty is decided in one place, not twice.

        `setup_gate` and `calorie_gate` share `_resolve_measurements`, so a
        hedge during the counted five gets the same read-back it would get in
        a target conversation three weeks later.
        """
        self.start()
        self.turn("33")
        self.turn("170cm")
        reply = self.turn("around 60-65")
        self.assertIn("60", reply)
        self.assertIn("weight", reply.lower())
        # Nothing was stored on the strength of a range.
        self.assertIsNone(gates._stored_measurement(self.USER_KEY, "weight_kg"))

    def test_pounds_are_converted_and_declared_inside_the_flow(self) -> None:
        self.start()
        self.turn("33")
        self.turn("170cm")
        reply = self.turn("154 lbs")
        self.assertIn("69.9", reply)
        self.assertIn("weight", reply.lower())
        # The original words survive to the read-back, so "69.9 kg" is
        # recognisable to somebody who thinks in pounds.
        self.turn("yes")
        self.turn("female")
        summary = self.through_setup()
        self.assertIn("you said 154 lbs", summary)

    def test_ted_stops_asking_after_three_tries(self) -> None:
        """The same bound the name question has, for the same reason.

        On 3 Sep Ted asked J for a name over and over because nothing counted
        the asking. A counted question repeats just as badly.
        """
        self.start()  # asks 1/5 once
        self.assertEqual(self.turn("what do you do?"), gates._setup_question(0))
        self.assertEqual(self.turn("i dont get it"), gates._setup_question(0))
        # Given up on. The model's own reply goes out untouched.
        self.assertEqual(self.turn("hmm", "ask me anything!"), "ask me anything!")
        self.assertEqual(gates._setup_state(self.USER_KEY), "stalled")

    def test_giving_up_on_the_five_does_not_give_up_on_the_age_rule(self) -> None:
        """Nothing unsafe follows from a stalled setup.

        The estimate is lost, which is a thing this person has now declined
        three times. The refusal is not: `calorie_gate` still has no age.
        """
        self.start()
        self.turn("what do you do?")
        self.turn("i dont get it")
        self.turn("hmm", "ask me anything!")
        self.assertEqual(gates._setup_state(self.USER_KEY), "stalled")
        self.assertEqual(
            transform_response(
                history=list(self.history),
                user_message="what's my daily calorie target?",
                response_text="you're looking at about 1,900 a day.",
                user_key=self.USER_KEY,
            ),
            gates.AGE_QUESTION,
        )

    def test_the_read_back_does_not_repeat_forever(self) -> None:
        """An unbounded re-ask is the pestering loop with a friendlier face."""
        self.start()
        self.turn("33")
        self.turn("170cm")
        self.turn("62kg")
        self.turn("female")
        self.through_setup()  # summary, first showing
        # Neither a recognised yes nor a correction, three times over.
        seen = [self.turn("hmm") for _ in range(3)]
        self.assertIn("here's what i've got:", seen[0])
        self.assertIn("1,630", seen[-1])
        self.assertEqual(gates._setup_state(self.USER_KEY), "done")

    def test_the_five_do_not_run_for_someone_who_finished_them(self) -> None:
        self.start()
        self.turn("33")
        self.turn("170cm")
        self.turn("62kg")
        self.turn("female")
        self.turn("desk most of it")
        self.turn("lose fat")
        self.turn("yep")
        self.assertEqual(gates._setup_state(self.USER_KEY), "done")
        # Ted's own words survive again now the five are done.
        self.assertEqual(self.turn("3 rotis and dal", "nice one."), "nice one.")

    def test_a_correction_wins_over_the_model_repeating_the_wrong_number(
        self,
    ) -> None:
        """The transcript is not where the correction lives.

        Found by replaying the flow through `_transform_live_response` rather
        than calling the gate directly, which is the difference that matters:
        Hermes writes the *model's* text to the transcript, never the gate's.
        So Ted's confirmation ("so your weight's 60 kg?") is not in the
        history at all — what is there is whatever the model wrote instead.

        On 4 Sep that was "ok, noting 60kg". The old reader anchored to a
        question it could not find, fell back to scanning, and read 60 back
        out of the model's own sentence. "63 actually" was discarded and the
        doubted number stood, inside the one mechanism built to stop exactly
        that.
        """
        self.start()
        self.turn("33")
        self.turn("170cm")
        # Ted asks for confirmation; the model, meanwhile, writes the number
        # it wrongly believes — and that is the line the history keeps.
        self.history.append(message("user", "around 60-65"))
        transform_response(
            history=list(self.history),
            user_message="around 60-65",
            response_text="ok, noting 60kg",
            user_key=self.USER_KEY,
        )
        self.history.append(message("assistant", "ok, noting 60kg"))
        self.assertEqual(
            gates._pending_measurement(self.USER_KEY)["value"], 60.0
        )

        self.history.append(message("user", "63 actually"))
        transform_response(
            history=list(self.history),
            user_message="63 actually",
            response_text="great, and are you male or female?",
            user_key=self.USER_KEY,
        )
        self.assertEqual(gates._stored_measurement(self.USER_KEY, "weight_kg"), 63.0)

    def test_a_bare_correction_is_read_without_an_anchor(self) -> None:
        """A pending measurement already names its field.

        So the number does not need a question above it to be unambiguous,
        which is what lets the correction be read from the user's own words.
        """
        for reply, expected in (
            ("63 actually", 63.0),
            ("no, 63", 63.0),
            ("actually 63", 63.0),
            ("63 kg", 63.0),
            ("154 lbs", 69.9),
        ):
            with self.subTest(reply=reply):
                self.assertEqual(gates._correction_value("weight_kg", reply), expected)
        # A number that is not a weight is not a correction.
        self.assertIsNone(gates._correction_value("weight_kg", "i had 2 rotis"))
        self.assertIsNone(gates._correction_value("weight_kg", "nope"))

    def test_an_answer_belongs_to_the_question_ted_asked(self) -> None:
        """Found live, on a real user, twelve minutes after going live.

        Ted asked "*1/6* how old are you?". Hermes wrote the *model's* text to
        the transcript instead — and the model, which has not been told the
        gate is asking anything, ran its own onboarding underneath: "and your
        weight?". He answered "33". The bare number anchored to the model's
        question and 33 was filed as his weight in kilograms, which would have
        built his maintenance figure from a 33 kg body.

        The transcript cannot decide what a counted answer answers. Ted knows
        which question he asked.
        """
        self.start()
        self.history.append(message("user", "33"))
        transform_response(
            history=list(self.history),
            # What the model wrote while Ted was asking question one.
            user_message="33",
            response_text="got it! and your weight?",
            user_key=self.USER_KEY,
        )
        self.assertEqual(gates._stored_age(self.USER_KEY), 33)
        self.assertIsNone(gates._stored_measurement(self.USER_KEY, "weight_kg"))

    def test_the_model_running_ahead_cannot_fill_any_of_the_five(self) -> None:
        """The same shape for every field, not just the one that was caught."""
        self.start()
        for answer, model_text in (
            ("33", "and your weight? also your height?"),
            ("182cm", "great — male or female? and how active are you?"),
        ):
            self.history.append(message("user", answer))
            transform_response(
                history=list(self.history),
                user_message=answer,
                response_text=model_text,
                user_key=self.USER_KEY,
            )
            self.history.append(message("assistant", model_text))
        record = gates._onboarding(self.USER_KEY)
        self.assertEqual(gates._stored_measurement(self.USER_KEY, "height_cm"), 182.0)
        self.assertIsNone(gates._stored_measurement(self.USER_KEY, "weight_kg"))
        self.assertIsNone(record.get("sex"))
        self.assertIsNone(record.get("activity"))
        # And the count has not skipped anything: weight is still next.
        self.assertEqual(gates._setup_asking(self.USER_KEY), "weight_kg")

    def test_an_age_stated_anywhere_still_reaches_the_refusal(self) -> None:
        """The one field read broadly on purpose.

        Every misread age makes the under-18 refusal more likely to fire, not
        less. Errors there fail safe; a weight read wrong fails dangerous.
        """
        self.start()
        self.history.append(message("user", "my mum says i'm 15 and too young for this"))
        self.assertEqual(
            transform_response(
                history=list(self.history),
                user_message="my mum says i'm 15 and too young for this",
                response_text="sure, here's a plan",
                user_key=self.USER_KEY,
            ),
            gates.UNDER_18_REFUSAL,
        )

    def test_a_desk_day_with_exercise_in_it_is_not_sedentary(self) -> None:
        """Harshal's answer, twice, on 4 Sep, and it parsed neither time.

        He wrote "Mostly desk with 1 hr walking/yoga/exercise" and Ted asked
        again. On the third ask he gave up and echoed the option back — one
        more and the bound would have given up on him. He is not sedentary,
        and a table that matches one phrase and stops could never say so.
        """
        self.assertEqual(
            gates._find_activity(["Mostly desk with 1 hr walking/yoga/exercise"]),
            "light",
        )
        self.assertEqual(gates._find_activity(["desk job but i run 3x a week"]), "light")
        # A desk and nothing else is still a desk.
        for plain in ("Desk most of it", "desk all day", "sitting all day"):
            with self.subTest(plain=plain):
                self.assertEqual(gates._find_activity([plain]), "sedentary")

    def test_the_guess_is_conservative(self) -> None:
        """Light, not moderate. The factor is what the number is built from,
        and guessing high hands somebody more than their day earns."""
        self.assertEqual(
            gates._find_activity(["desk, plus the gym every single day"]), "light"
        )

    def _to_summary(self) -> str:
        self.start()
        self.turn("33")
        self.turn("170cm")
        self.turn("62kg")
        self.turn("female")
        return self.through_setup()

    def test_saying_it_is_wrong_asks_which_bit(self) -> None:
        """Amit sent exactly "its wrong" on 4 Sep and got the same four lines
        back. That answers nobody — he had already read them, which is how he
        knew they were wrong."""
        self.assertIn("here's what i've got:", self._to_summary())
        reply = self.turn("its wrong")
        self.assertEqual(reply, gates.SUMMARY_FIX_QUESTION)
        self.assertNotIn("here's what i've got:", reply)

    def test_the_correction_is_taken_and_the_numbers_go_back_up(self) -> None:
        self._to_summary()
        self.turn("its wrong")
        reply = self.turn("weight is 90 kg not 62")
        self.assertIn("90 kg", reply)
        self.assertIn("here's what i've got:", reply)
        self.assertEqual(gates._stored_measurement(self.USER_KEY, "weight_kg"), 90.0)

    def test_a_correction_lands_without_being_asked_which_bit(self) -> None:
        """Harshal did not wait to be asked — he wrote the right number
        straight back. Taking it is the whole reason the numbers are shown."""
        self._to_summary()
        reply = self.turn("Weight is 90 kg not 62 kg")
        self.assertEqual(gates._stored_measurement(self.USER_KEY, "weight_kg"), 90.0)
        self.assertIn("90 kg", reply)

    def test_every_line_of_the_summary_can_be_corrected(self) -> None:
        for text, field, expected in (
            ("my height is 175", "height_cm", 175.0),
            ("age is 34", "age", 34),
            ("im male actually", "sex", "male"),
            ("i'm on my feet all day", "activity", "light"),
        ):
            with self.subTest(text=text):
                self.assertEqual(gates._summary_correction(text).get(field), expected)

    def test_a_bare_number_after_a_summary_is_not_guessed(self) -> None:
        """Four lines carry numbers, so "90" names none of them. Guessing
        which is the family of bugs this whole flow exists to stop."""
        self.assertEqual(gates._summary_correction("90"), {})

    def test_a_weight_equal_to_the_age_is_not_a_weight(self) -> None:
        """Belt and braces for the 4 Sep failure.

        The weight range starts at 30, so every adult age from 30 to 99 sits
        inside it. Two real users answered "33" to "how old are you?" and had
        33 kg filed against them.
        """
        self.start()
        self.turn("33")
        profile = gates.CalorieProfile(age=33, weight_kg=33.0)
        settled, _ = gates._resolve_measurements(profile, [], "33", self.USER_KEY)
        self.assertIsNone(settled.weight_kg)

    def test_saying_the_unit_means_you_meant_it(self) -> None:
        """Somebody who is 33 and weighs 33 kg is telling Ted something."""
        self.start()
        self.turn("33")
        profile = gates.CalorieProfile(age=33, weight_kg=33.0)
        settled, _ = gates._resolve_measurements(profile, [], "33 kg", self.USER_KEY)
        self.assertEqual(settled.weight_kg, 33.0)

    def test_a_bare_number_answers_question_one(self) -> None:
        """Everyone answers "how old are you?" with a number and nothing else.

        `_find_age` needs "i'm 33" or a year on purpose, because a stray 33
        anywhere in a conversation is not an age. Under a counted question it
        is nothing else, and requiring the sentence would have looped 1/5
        forever.
        """
        for reply, expected in (("32", 32), ("29", 29), ("i am 33", 33), ("15", 15)):
            with self.subTest(reply=reply):
                self.assertEqual(gates._setup_answer("age", reply), expected)

    def test_eighteen_plus_is_not_an_age(self) -> None:
        """A real user answered 1/5 by echoing the question's own "beta's 18+".

        She is 32. Read as an age it says 18 — the one number that switches
        the under-18 refusal off — so a minor echoing the same three
        characters would walk through it. It is a category, not an age.
        """
        self.assertIsNone(gates._setup_answer("age", "18+"))
        self.assertIsNone(gates._setup_answer("age", "beta's 18+"))

    def test_five_point_seven_feet_is_five_foot_seven(self) -> None:
        """Read as seven feet until 4 Sep 2026.

        "5.7 ft" failed to match at the 5 — ".7 " is not whitespace — so the
        engine slid along and matched the 7 instead. A 170 cm user was stored
        at 213.36 cm; she followed it with "170 cm", which is 5 foot 7 exactly
        and is how that phrasing is meant.
        """
        self.assertEqual(gates._find_height_cm(["5.7 ft"]), 170.18)
        self.assertEqual(gates._find_height_cm(["5.11"]), 180.34)
        # The forms that already worked still do.
        for text, expected in (
            ("5ft 11 inches", 180.34),
            ("5 foot 11", 180.34),
            ("5'11", 180.34),
            ("175 cm", 175.0),
            ("5 feet 4 and a half inches", 163.83),
        ):
            with self.subTest(text=text):
                self.assertEqual(gates._find_height_cm([text]), expected)

    def test_training_on_its_own_is_an_answer(self) -> None:
        """PG answered 5/5 three times — "Training 4-5 days a week mostly",
        "Training", "Training" — and none of them read. The bound gave up on
        him with a complete profile except for this one field."""
        self.assertEqual(gates._find_activity(["Training 4-5 days a week mostly"]), "active")
        self.assertEqual(gates._find_activity(["gym 5x a week"]), "active")
        # No frequency named, so not the top factor.
        self.assertEqual(gates._find_activity(["Training"]), "moderate")
        self.assertEqual(gates._find_activity(["i lift weights"]), "moderate")

    def test_feet_and_inches_with_no_unit_answer_question_two(self) -> None:
        """"5 11" and "5 2”" are heights once Ted knows he asked for one.

        Refused everywhere else, and rightly: two numbers side by side could
        be a date, a weight, a time. Under "*2/6* how tall are you?" they are
        nothing else. Two real users typed exactly these on 4 Sep and were
        asked again; one of them ran out of asks over it.
        """
        for text, expected in (
            ("5 2”", 157.48),
            ("5 11", 180.34),
            ("5'2", 157.48),
            ("5 2", 157.48),
        ):
            with self.subTest(text=text):
                self.assertEqual(gates._setup_answer("height_cm", text), expected)

    def test_two_numbers_that_are_not_a_height_are_still_refused(self) -> None:
        for text in ("12 30", "5 2 3", "2024 11"):
            with self.subTest(text=text):
                self.assertIsNone(gates._bare_feet_inches(text))

    def test_the_forms_that_already_worked_still_do(self) -> None:
        for text, expected in (
            ("175 cm", 175.0),
            ("5ft 11 inches", 180.34),
            ("5.7 ft", 170.18),
            ("170", 170.0),
        ):
            with self.subTest(text=text):
                self.assertEqual(gates._setup_answer("height_cm", text), expected)

    def test_agreement_is_read_anywhere_in_the_sentence(self) -> None:
        """A real user said it three ways and got the same four lines back.

        "you can go ahead", then "You can do the maths", which is Ted's own
        closing phrase from the question she was answering. Neither counted,
        because agreement had to *be* the whole reply. People do not answer
        "anything off?" with a single token.
        """
        for reply in (
            "you can go ahead",
            "You can do the maths",
            "yeah go ahead please",
            "all good, do the maths",
            "sure, looks right to me",
            "ok proceed",
        ):
            with self.subTest(reply=reply):
                self.assertTrue(gates._agrees_to_summary(reply))

    def test_a_complaint_outranks_an_agreement_inside_it(self) -> None:
        """"no that's wrong, go ahead and fix it" carries "go ahead" and is
        not a yes. The dispute is checked first for exactly this reason."""
        self._to_summary()
        reply = self.turn("no thats not right, go ahead and fix it")
        self.assertEqual(reply, gates.SUMMARY_FIX_QUESTION)

    def test_a_correction_still_outranks_both(self) -> None:
        self._to_summary()
        reply = self.turn("weight is 90 not 62, go ahead after that")
        self.assertEqual(gates._stored_measurement(self.USER_KEY, "weight_kg"), 90.0)
        self.assertIn("90 kg", reply)

    def test_getting_on_with_it_actually_gets_on_with_it(self) -> None:
        self._to_summary()
        payoff = self.turn("you can go ahead")
        self.assertIn("all six", payoff)
        self.assertIn("1,630", payoff)
        self.assertEqual(gates._setup_state(self.USER_KEY), "done")


class TheDisputeMatcherIsNotTooEagerTest(unittest.TestCase):
    """Searched anywhere in the reply, so every word in it must be unambiguous.

    Found in an audit, not by a user, and it was mine: the pattern carried a
    bare "no", "nope", "nah" and "off", so "no problem, proceed" read as a
    complaint. Bare "no" answering "anything off?" means nothing is off, which
    is the opposite. A loose word in a searched pattern is the same mistake as
    a strict pattern in a whole string match, pointing the other way.
    """

    def test_a_no_inside_a_sentence_is_not_a_complaint(self) -> None:
        for reply in (
            "no problem, proceed",
            "no idea, you can go ahead",
            "i have no allergies, go ahead",
            "im off to work, go ahead",
        ):
            with self.subTest(reply=reply):
                self.assertFalse(gates._says_something_is_wrong(reply))
                self.assertTrue(gates._agrees_to_summary(reply))

    def test_a_real_complaint_still_reads_as_one(self) -> None:
        for reply in (
            "its wrong",
            "no thats not right",
            "the weight is off",
            "you mixed up my height",
            "thats incorrect",
        ):
            with self.subTest(reply=reply):
                self.assertTrue(gates._says_something_is_wrong(reply))


class TheAgeIsSettledOnceTest(TheCountedFiveTest):
    """A number later in the flow must not become the age."""

    USER_KEY = "age-settled-once"

    def test_a_later_number_cannot_overwrite_a_settled_age(self) -> None:
        """Ram answered 27, then 160, then 80. His age became 80.

        The broad age read exists so a minor cannot slip past by mentioning
        their age somewhere the counted question did not reach. I argued it
        failed safe, because a wrong age makes the refusal more likely. That
        only holds for errors crossing the 18 line. 27 to 80 is adult to
        adult: no refusal, and 265 kcal off the number he was about to be
        handed.
        """
        self.start()
        self.turn("27")
        self.assertEqual(gates._stored_age(self.USER_KEY), 27)
        self.turn("160")
        self.turn("80")
        self.assertEqual(gates._stored_age(self.USER_KEY), 27)

    def test_a_minor_mentioned_anywhere_is_still_caught(self) -> None:
        """The safety property the broad read was there for, still intact."""
        self.start()
        self.turn("33")
        self.history.append(message("user", "my son is 15 and asks a lot"))
        self.assertEqual(
            transform_response(
                history=list(self.history),
                user_message="actually i'm 15, i lied earlier",
                response_text="sure, 1800 a day",
                user_key=self.USER_KEY,
            ),
            gates.UNDER_18_REFUSAL,
        )


class DeficitPhrasingTest(unittest.TestCase):
    """The no-deficit rule must not depend on how the model worded it.

    Live, 4 Sep 2026 at 20:43:25, to a real user with no height, no sex and
    no activity on file:

        "for weight loss at your stats, something like 1300 to 1400 kcal a
        day is a sensible target, keeps it sustainable. want me to lock that
        in?"

    That went out intact. `_TARGET_FLOW_TERMS` listed "calories a day" but
    not "kcal a day", and "calorie target" but not a bare "target", so
    `calorie_gate` decided no target conversation was happening and returned
    None before any rule could read the sentence. Nothing had been
    calculated: with three of the five inputs missing there was no formula to
    run, and the range is the proof. Every figure the gate produces is a
    single integer out of `_estimated_maintenance`.
    """

    LIVE = (
        "for weight loss at your stats, something like 1300 to 1400 kcal a "
        "day is a sensible target, keeps it sustainable. want me to lock "
        "that in?"
    )

    def _user(self, name: str) -> str:
        user_key = f"{name}-{id(self)}"
        self.addCleanup(reset_user, user_key)
        gates._mark_disclosure_sent(user_key)
        gates._update_onboarding(user_key, name="P")
        return user_key

    def test_the_live_deficit_never_reaches_the_user(self):
        user_key = self._user("live-deficit")
        out = transform_response(
            history=[message("user", "i want to lose weight")],
            user_message="i want to lose weight",
            response_text=self.LIVE,
            user_key=user_key,
        )
        self.assertIsNotNone(out)
        self.assertNotIn("1300", out)
        self.assertNotIn("1400", out)

    def test_every_phrasing_of_a_deficit_is_caught(self):
        """The point of the fix: shape, not vocabulary."""
        for label, reply in (
            ("kcal a day", "something like 1300 kcal a day is sensible."),
            ("calories a day", "for weight loss, about 1300 calories a day."),
            ("the word deficit", "i'd put you in a small deficit, 1300 a day."),
            ("aim for", "aim for 1300 kcal and the weight comes off."),
            ("eat around", "eat around 1300 and you'll drop steadily."),
            ("keep it under", "keep it under 1400 calories and you're set."),
            ("a range", "somewhere between 1300 to 1400 kcal works."),
        ):
            with self.subTest(label):
                user_key = self._user(f"phrasing-{label}")
                out = transform_response(
                    history=[message("user", "i want to lose weight")],
                    user_message="i want to lose weight",
                    response_text=reply,
                    user_key=user_key,
                )
                self.assertIsNotNone(out, f"{label} passed straight through")
                self.assertNotIn("1300", out)
                self.assertNotIn("1400", out)

    def test_a_per_food_estimate_still_passes_through(self):
        """The gate must not swallow ordinary nutrition answers."""
        user_key = self._user("per-food")
        gates._update_onboarding(user_key, age=30)
        out = transform_response(
            history=[message("user", "how many calories in a roti")],
            user_message="how many calories in a roti",
            response_text="that roti is about 120 kcal, and the dal maybe 180.",
            user_key=user_key,
        )
        self.assertIsNone(out)

    def test_a_logged_meal_reply_is_not_hijacked(self):
        """"615 kcal for the day so far" describes a plate, it sets nothing."""
        user_key = self._user("meal-reply")
        gates._update_onboarding(user_key, age=30)
        out = transform_response(
            history=[message("user", "logged my lunch")],
            user_message="logged my lunch",
            response_text="nice, that's 615 kcal for the day so far.",
            user_key=user_key,
            logged_meal={"items": ["dal", "rice"]},
            day_summary={"calories": 615},
        )
        self.assertNotIn("how old are you", out or "")

    def test_offering_to_set_a_target_is_not_setting_one(self):
        """The regression the first version of this fix caused.

        Real, 3 Sep: a day summary that reports a plate and offers a target
        states neither, and must not be replaced.
        """
        user_key = self._user("offer-target")
        gates._update_onboarding(user_key, age=30)
        out = transform_response(
            history=[message("user", "how am i doing")],
            user_message="how am i doing",
            response_text=(
                "420 cal and 20g protein logged, no target set yet so "
                "nothing to measure against. wanna set a calorie target?"
            ),
            user_key=user_key,
        )
        self.assertNotIn("how old are you", out or "")

    def test_whatsapp_bold_does_not_hide_a_deficit(self):
        """Live, 4 Sep 2026 21:37, to a user who had just finished the five.

        "fat loss, solid choice 🔥 knocked it down to *1,650 kcal* a day for
        you, decent steady deficit without starving yourself."

        The gate replaced it, but only because "deficit" is in the old phrase
        list. The shape check missed it: the asterisk sits between the unit and
        "a day", exactly where the pattern wanted whitespace. `_setup_payoff`
        writes "*1,630 kcal*" itself, so bold around a calorie figure is the
        normal case. Stripped of its giveaway word, the sentence must still be
        caught on shape alone.
        """
        for label, reply in (
            ("bold, giveaway word removed",
             "knocked it down to *1,650 kcal* a day for you, steady and kind"),
            ("italic", "aim for _1,650 kcal_ a day"),
            ("strikethrough", "stick to ~1650~ kcal"),
        ):
            with self.subTest(label):
                self.assertTrue(
                    gates._looks_like_calorie_target(reply),
                    f"{label}: markup hid the figure from the shape check",
                )
                user_key = self._user(f"markup-{label}")
                out = transform_response(
                    history=[message("user", "i want fat loss")],
                    user_message="i want fat loss",
                    response_text=reply,
                    user_key=user_key,
                )
                self.assertIsNotNone(out, f"{label} passed straight through")
                self.assertNotIn("1,650", out)
                self.assertNotIn("1650", out)


class TheCheckInTimeIsAskedOnceTest(unittest.TestCase):
    """4 Sep 2026: Parth was asked for his check-in time twice in 60 seconds.

    The model asked it conversationally and offered a default, he agreed with
    "okay", and the model never called `ted_save_onboarding`. Nothing recorded
    `dailyReview`, so `onboarding_close_gate` replaced the sign-off with its own
    question, which opens "one last thing before we start" — to a man who had
    just answered it.

    The gate was right and the sequence was still wrong, because the asking and
    the reading were owned by different things. These tests hold both halves
    here.
    """

    def _user(self, name: str) -> str:
        key = f"review-time-{name}"
        gates._DISCLOSURE_SENT_KEYS.add(key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(key, None)
        self.addCleanup(gates._DISCLOSURE_SENT_KEYS.discard, key)
        return key

    def test_the_model_may_not_ask_in_its_own_words(self) -> None:
        """Parth's exact message. It gets the gate's question instead."""
        user_key = self._user("parth")
        parth = (
            "bengaluru, easy one \U0001f604 last bit, when should i send your "
            "daily check in, evening usually works best, say around 9?"
        )
        self.assertEqual(
            gates.review_time_gate(parth, "bengaluru", user_key),
            gates.REVIEW_TIME_QUESTION,
        )
        self.assertEqual(gates._review_state(user_key), "asking")

    def test_the_gate_reads_the_answer_the_model_forgot_to_save(self) -> None:
        """The half that was missing. No tool call, and the step still closes."""
        user_key = self._user("reads")
        gates._update_onboarding(user_key, review_state="asking")
        with patch.object(gates, "_convex_request", return_value={"success": True}):
            reply = gates.review_time_gate("all set!", "9pm", user_key)
        self.assertIsNotNone(reply)
        self.assertIn("9pm", reply)
        done = set(gates._onboarding(user_key).get("done") or ())
        self.assertIn("dailyReview", done)
        self.assertEqual(gates._onboarding(user_key).get("review_time"), "21:00")

    def test_asked_once_and_then_never_again(self) -> None:
        """The whole point. A sign-off after the answer closes cleanly."""
        user_key = self._user("once")
        asked = gates.review_time_gate(
            "when should i check in?", "bengaluru", user_key
        )
        self.assertEqual(asked, gates.REVIEW_TIME_QUESTION)
        with patch.object(gates, "_convex_request", return_value={"success": True}):
            gates.review_time_gate("noted", "9", user_key)
        # The close gate is the thing that asked the second time on 4 Sep.
        self.assertIsNone(
            gates.onboarding_close_gate("you're all set.", user_key)
            if "dailyReview" not in set(gates._onboarding(user_key).get("done") or ())
            else None
        )
        again = gates.review_time_gate("what time works for your check-in?", "ok", user_key)
        self.assertIsNone(again, "the question came back after it was answered")

    def test_a_failed_write_does_not_close_the_step(self) -> None:
        """A recorded step with no row behind it is worse than asking again."""
        user_key = self._user("outage")
        gates._update_onboarding(user_key, review_state="asking")
        with patch.object(gates, "_convex_request", return_value={"success": False}):
            reply = gates.review_time_gate("all set!", "9pm", user_key)
        self.assertEqual(reply, gates.REVIEW_TIME_NOT_SAVED)
        done = set(gates._onboarding(user_key).get("done") or ())
        self.assertNotIn("dailyReview", done)

    def test_okay_is_not_a_time(self) -> None:
        """What Parth actually sent. It carries no time, so it is not an answer."""
        user_key = self._user("okay")
        gates._update_onboarding(user_key, review_state="asking")
        for reply in ("okay", "sure", "yes", "sounds good", "that works", "ok cool"):
            with self.subTest(reply=reply):
                self.assertIsNone(gates._find_review_time(reply))

    def test_the_times_people_actually_send(self) -> None:
        for written, expected in (
            ("9", "21:00"),
            ("9pm", "21:00"),
            ("9 pm", "21:00"),
            ("9:30pm", "21:30"),
            ("10:30 pm", "22:30"),
            ("21:00", "21:00"),
            ("around 9", "21:00"),
            ("9ish", "21:00"),
            ("8", "20:00"),
            ("7am", "07:00"),
            ("6:45am", "06:45"),
            ("11", "23:00"),
            ("22:15", "22:15"),
        ):
            with self.subTest(written=written):
                self.assertEqual(gates._find_review_time(written), expected)

    def test_ambiguous_and_impossible_times_are_refused(self) -> None:
        """Be sure, or ask. A guess here is a recap that never arrives."""
        for written in ("12", "0", "25pm", "99", "later", "whenever", "evening"):
            with self.subTest(written=written):
                self.assertIsNone(gates._find_review_time(written))

    def test_it_stays_out_of_the_way_once_settled(self) -> None:
        user_key = self._user("settled")
        gates._update_onboarding(user_key, done=["dailyReview"])
        self.assertIsNone(
            gates.review_time_gate("what time should i check in?", "9pm", user_key)
        )


class TheEveningReviewCanReadTheDayTest(unittest.TestCase):
    """4 Sep 2026, 21:30: the review fired and the day was unreachable.

        WARNING [cron_6f50de92d4b6_20260904_213033] agent.tool_executor:
        Tool ted_day_summary returned error (0.01s):
        {"success": false, "error": "No WhatsApp user is active"}

    Every ted_* handler takes the user from `_TURN_CONTEXT`, which is what
    stops a user id in the model's arguments redirecting a write. The cron
    branch of `_capture_turn` returned a voice card and never wrote a context,
    so the output gate could work out whose evening it was and the tools could
    not. The user got an evening review with no day in it.
    """

    JOB = "cron_6f50de92d4b6_20260904_213033"
    CHAT = "917014564886@lid"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.JOB, None)
        self.addCleanup(self._clear)

    def _clear(self) -> None:
        with gates._TURN_LOCK:
            for key in [k for k in gates._TURN_CONTEXT if k.startswith("cron_")]:
                gates._TURN_CONTEXT.pop(key, None)

    def test_the_tools_can_resolve_the_user_the_job_belongs_to(self) -> None:
        with patch.object(gates, "_cron_whatsapp_recipient", return_value=self.CHAT):
            gates._capture_turn(platform="cron", session_id=self.JOB)
        expected = gates._user_state_key("whatsapp", self.CHAT, self.JOB)
        self.assertEqual(gates._active_user_key(self.JOB, ""), expected)
        self.assertNotEqual(gates._active_user_key(self.JOB, ""), "")

    def test_a_job_with_no_whatsapp_origin_still_registers_nothing(self) -> None:
        """No recipient means no user, and guessing one would be worse."""
        with patch.object(gates, "_cron_whatsapp_recipient", return_value=None):
            self.assertIsNone(gates._capture_turn(platform="cron", session_id=self.JOB))
        self.assertEqual(gates._active_user_key(self.JOB, ""), "")

    def test_the_key_comes_from_the_job_not_the_model(self) -> None:
        """The whole safety property. A cron run reaches one user: its own."""
        with patch.object(gates, "_cron_whatsapp_recipient", return_value=self.CHAT):
            gates._capture_turn(platform="cron", session_id=self.JOB)
        mine = gates._active_user_key(self.JOB, "")
        someone_else = gates._user_state_key("whatsapp", "919999999999@lid", "")
        self.assertNotEqual(mine, someone_else)
        self.assertEqual(mine, gates._user_state_key("whatsapp", self.CHAT, self.JOB))

    def test_cron_turns_do_not_leak_forever(self) -> None:
        """A cron session id is unique per run, so an unbounded dict grows."""
        with patch.object(gates, "_cron_whatsapp_recipient", return_value=self.CHAT):
            for n in range(gates._MAX_CRON_CONTEXTS + 25):
                gates._capture_turn(
                    platform="cron", session_id=f"cron_job{n:04d}_20260904_213033"
                )
        with gates._TURN_LOCK:
            held = [k for k in gates._TURN_CONTEXT if k.startswith("cron_")]
        self.assertLessEqual(len(held), gates._MAX_CRON_CONTEXTS)
        # The newest run is the one still needed, so it must be the survivor.
        self.assertIn(
            f"cron_job{gates._MAX_CRON_CONTEXTS + 24:04d}_20260904_213033", held
        )

    def test_a_cron_run_does_not_age_a_live_turn(self) -> None:
        """_record_turn_arrival is deliberately not called on this path."""
        live = gates._user_state_key("whatsapp", self.CHAT, "")
        before = gates._record_turn_arrival(live)
        with patch.object(gates, "_cron_whatsapp_recipient", return_value=self.CHAT):
            gates._capture_turn(platform="cron", session_id=self.JOB)
        after = gates._record_turn_arrival(live)
        self.assertEqual(
            after, before + 1, "the cron run advanced the live arrival counter"
        )


class TheSameReminderTwiceTest(unittest.TestCase):
    """4 Sep 2026: Vandy got the omega 3 ping twice.

    `Omega3 reminder` and `omega3 reminder` were two separate jobs. So were
    CoQ10, B12, iron and vitamin D. Five supplements, ten jobs, four pairs
    firing at exactly the same minute; the run log has one pair 6ms apart.

    The model was not misbehaving. `ted_set_reminder` carries a time and
    nothing else, so a weekday-only reminder can only be built as a free-form
    job. What was missing was any check that it had already been built.
    """

    CHAT = "202258616737857@lid"
    SESSION = "session-dupe"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "user_key": "dupe-user", "chat_id": self.CHAT,
            }
        self.addCleanup(self._clear)

    def _clear(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def _guard(self, name: str, existing: list[dict]):
        with patch.object(gates, "_load_cron_jobs", return_value=existing):
            return gates._cron_scope_guard(
                tool_name="cronjob",
                session_id=self.SESSION,
                args={"action": "create", "name": name, "schedule": "45 8 * * 1-5"},
            )

    def _job(self, name: str) -> dict:
        return {"id": "abc123", "name": name, "deliver": f"whatsapp:{self.CHAT}"}

    def test_the_exact_pair_that_double_pinged(self) -> None:
        blocked = self._guard("omega3 reminder", [self._job("Omega3 reminder")])
        self.assertIsNotNone(blocked, "the second omega3 job was allowed again")
        self.assertEqual(blocked["action"], "block")
        self.assertEqual(blocked["message"], gates.CRON_ALREADY_SET)

    def test_every_supplement_pair_from_that_night(self) -> None:
        for existing, attempted in (
            ("CoQ10 reminder", "coq10 reminder"),
            ("B12 reminder", "b12 reminder"),
            ("Iron reminder", "iron reminder"),
            ("Vitamin D reminder", "vitamin d reminder"),
        ):
            with self.subTest(attempted=attempted):
                self.assertIsNotNone(self._guard(attempted, [self._job(existing)]))

    def test_spacing_does_not_make_a_new_reminder(self) -> None:
        self.assertIsNotNone(self._guard("  omega3   reminder ", [self._job("Omega3 reminder")]))

    def test_a_genuinely_different_reminder_still_gets_through(self) -> None:
        """The check must stay dumb. These are not the same thing."""
        for existing, attempted in (
            ("vitamin d reminder", "vitamin d3 reminder"),
            ("omega3 reminder", "omega 3 evening reminder"),
            ("iron reminder", "creatine reminder"),
        ):
            with self.subTest(attempted=attempted):
                self.assertIsNone(
                    self._guard(attempted, [self._job(existing)]),
                    f"{attempted!r} was wrongly treated as {existing!r}",
                )

    def test_someone_elses_identical_reminder_is_not_mine(self) -> None:
        """Two users may both take omega 3. Only this chat's jobs count."""
        theirs = {"id": "z", "name": "omega3 reminder", "deliver": "whatsapp:999@lid"}
        self.assertIsNone(self._guard("omega3 reminder", [theirs]))

    def test_the_first_one_is_always_allowed(self) -> None:
        self.assertIsNone(self._guard("omega3 reminder", []))


class TheCountIsAPromiseTest(unittest.TestCase):
    """Ted says a number out loud before asking that many questions.

    The intro is written out ("quick six questions") because SETUP_QUESTIONS is
    defined lower in the module than SETUP_INTRO, so it cannot interpolate the
    real count. That makes this test the only thing holding the promise to the
    questions. Add a seventh question without touching the intro and Ted starts
    lying in his first message.
    """

    def test_the_promise_and_the_count_agree(self) -> None:
        self.assertIn(gates.SETUP_COUNT_WORD, gates.SETUP_INTRO)
        self.assertEqual(gates.SETUP_COUNT, len(gates.SETUP_QUESTIONS))

    def test_every_question_carries_the_same_denominator(self) -> None:
        for index in range(gates.SETUP_COUNT):
            with self.subTest(index=index):
                self.assertIn(
                    f"/{gates.SETUP_COUNT}*", gates._setup_question(index)
                )

    def test_no_other_count_is_left_lying_around(self) -> None:
        """The old "five" must not survive anywhere a user can read it."""
        for label, text in (
            ("intro", gates.SETUP_INTRO),
            ("1/6", gates._setup_question(0)),
        ):
            with self.subTest(label):
                self.assertNotIn("five", text.lower())
                self.assertNotIn("/5", text)


class AMealIsNotACheckInTimeTest(unittest.TestCase):
    """A bare number is only a time when it is the whole answer.

    Caught by an existing test, not by a new one. With the check-in question
    outstanding, "3 rotis and dal" was read as 3pm: a meal would have silently
    become someone's review time and nothing would ever have said so. The
    reply that carries a time says so, with a colon or an am/pm marker, or it
    is the number and nothing else.
    """

    def test_the_meal_that_became_a_time(self) -> None:
        self.assertIsNone(gates._find_review_time("3 rotis and dal"))

    def test_things_people_send_that_are_not_times(self) -> None:
        for written in (
            "3 rotis and dal", "i ate 2 eggs", "walked 5 km", "2 glasses of water",
            "60 kg today", "did 20 pushups", "okay", "sounds good",
        ):
            with self.subTest(written=written):
                self.assertIsNone(gates._find_review_time(written))

    def test_things_people_send_that_are_times(self) -> None:
        for written, expected in (
            ("9", "21:00"), ("9pm", "21:00"), ("7 pm", "19:00"),
            ("around 9", "21:00"), ("9ish", "21:00"), ("at 8", "20:00"),
            ("10:30 pm", "22:30"), ("21:00", "21:00"), ("9 please", "21:00"),
        ):
            with self.subTest(written=written):
                self.assertEqual(gates._find_review_time(written), expected)

    def test_a_time_inside_a_sentence_still_counts_when_it_says_so(self) -> None:
        """An am/pm marker is unambiguous wherever it sits."""
        self.assertEqual(gates._find_review_time("let's do 9pm please"), "21:00")
        self.assertEqual(gates._find_review_time("can we say 10:30 pm"), "22:30")


class TheLosingNumberHasAFloorTest(unittest.TestCase):
    """Ted may now name a cut, and these are the bounds it can never leave.

    SCOPING.md §9 still holds: Ted does not prescribe. It names one bounded
    number and maintenance, and the user picks. What changed on 4 Sep 2026 is
    that naming nothing left someone who had just said "lose fat" holding
    maintenance, which is by definition the number where nothing moves.

    The floor is the whole safety case. "Maintenance minus 500", which is what
    every calculator on the internet does, gives Pallavi 1,100 against a
    resting burn of 1,333. That generic advice is unsafe for exactly the people
    this beta has, and it is the shape of "eat 900 calories a day".
    """

    def _p(self, **kw):
        base = dict(age=31, height_cm=163, weight_kg=63, sex="female",
                    activity="sedentary", goal="loseWeight")
        base.update(kw)
        return gates.CalorieProfile(**base)

    def test_never_below_resting_energy(self) -> None:
        for kw in ({}, {"weight_kg": 45, "height_cm": 150, "age": 55},
                   {"weight_kg": 90, "height_cm": 180, "sex": "male"},
                   {"age": 19, "weight_kg": 50, "height_cm": 155}):
            with self.subTest(**kw):
                p = self._p(**kw)
                self.assertGreaterEqual(gates._loss_target(p), gates._resting_energy(p))

    def test_never_below_the_published_floor(self) -> None:
        for sex, floor in (("female", 1200), ("male", 1500)):
            with self.subTest(sex=sex):
                p = self._p(sex=sex, weight_kg=45, height_cm=150, age=60)
                self.assertGreaterEqual(gates._loss_target(p), min(floor, gates._estimated_maintenance(p)))

    def test_never_above_maintenance(self) -> None:
        """A cut above maintenance is nonsense, and the floors can meet it."""
        for kw in ({}, {"weight_kg": 40, "height_cm": 145, "age": 65}):
            with self.subTest(**kw):
                p = self._p(**kw)
                self.assertLessEqual(gates._loss_target(p), gates._estimated_maintenance(p))

    def test_the_internet_formula_would_have_been_unsafe(self) -> None:
        """Minus 500 on Pallavi is 1,100, under her resting burn of 1,333."""
        p = self._p()
        maintenance = gates._estimated_maintenance(p)
        self.assertLess(maintenance - 500, gates._resting_energy(p))
        self.assertGreater(gates._loss_target(p), maintenance - 500)

    def test_no_safe_cut_is_said_out_loud_rather_than_invented(self) -> None:
        p = self._p(weight_kg=40, height_cm=145, age=65)
        payoff = gates._setup_payoff(p)
        self.assertIn("not going to cut under it", payoff)
        self.assertNotIn("steady place to aim", payoff)

    def test_the_user_chooses_and_the_choice_is_recorded(self) -> None:
        key = "target-choice"
        gates._update_onboarding(
            key, target_state="asking", target_lower=1360, target_maintenance=1600
        )
        self.addCleanup(gates._forget_user, key)
        reply = gates.target_choice_gate("1600", key)
        self.assertIn("1,600", reply)
        self.assertEqual(gates._onboarding(key).get("tracking_kcal"), 1600)

    def test_a_bare_yes_does_not_choose_a_calorie_target(self) -> None:
        """It used to, and nine turns later a deletion confirmation chose one."""
        key = "target-bare-yes"
        gates._update_onboarding(
            key, target_state="asking", target_lower=1360, target_maintenance=1600
        )
        self.addCleanup(gates._forget_user, key)
        self.assertIsNone(gates.target_choice_gate("yes", key))
        # And the question closes rather than staying armed for a later reply.
        self.assertEqual(gates._onboarding(key).get("target_state"), "done")
        self.assertEqual(gates._onboarding(key).get("tracking_kcal"), 1600)


class TheNudgesAreOptInTest(unittest.TestCase):
    """Vandy, 4 Sep 2026: "if they say to give water reminder then only"."""

    def test_nothing_is_set_that_was_not_asked_for(self) -> None:
        key = "picks-none"
        gates._update_onboarding(key, picks_state="asking")
        self.addCleanup(gates._forget_user, key)
        with patch.object(gates, "_convex_request") as write:
            reply = gates.picks_gate("no", key)
        write.assert_not_called()
        self.assertIn("stay quiet", reply)

    def test_water_gets_two_nudges_not_three(self) -> None:
        slots = {name: times for name, _, times in gates.REMINDER_MENU}
        self.assertEqual(slots["water"], ("11:00", "16:00"))

    def test_every_default_time_is_outside_quiet_hours(self) -> None:
        """22:00 to 07:00. A nudge inside them is one the cap would drop."""
        for name, _, times in gates.REMINDER_MENU:
            for slot in times:
                with self.subTest(name=name, slot=slot):
                    self.assertGreaterEqual(slot, "07:00")
                    self.assertLess(slot, "22:00")

    def test_a_logged_meal_is_not_a_request_for_meal_reminders(self) -> None:
        """"3 rotis and dal for lunch" carries "lunch"."""
        key = "picks-meal"
        gates._update_onboarding(key, picks_state="asking")
        self.addCleanup(gates._forget_user, key)
        with patch.object(gates, "_convex_request") as write:
            self.assertIsNone(gates.picks_gate("3 rotis and dal for lunch", key))
        # Read as an answer it would have set meal reminders. It closes instead.
        self.assertEqual(gates._onboarding(key).get("picks_state"), "done")

    def test_the_words_people_use(self) -> None:
        for written, expected in (
            ("meals and water", ("meals", "water")),
            ("pani aur khana", ("meals", "water")),
            ("just water please", ("water",)),
            ("everything", ("meals", "water", "supplements", "movement")),
            ("no", ()), ("koi nahi", ()),
        ):
            with self.subTest(written=written):
                self.assertEqual(gates._find_picks(written), expected)


class OnboardingAbandonedFieldTest(unittest.TestCase):
    """A step the model moved past without an answer is not a step it finished.

    Replays what actually happened to three testers. Each was asked for one
    thing and answered another — "Male" to a question about their city, "Male"
    to a question about their weight, "female" to a question about their city —
    and in every case the model simply moved the flow onward and never came
    back. The tool call that would have completed the field was never made, so
    the tester finished onboarding with no weight or no timezone stored, while
    the chat kept counting up to "5/6".
    """

    SESSION = "session-onboarding-abandoned"
    USER_KEY = "whatsapp:sha256:owner"

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {
                "history": [],
                "user_message": "",
                "successful_actions": set(),
                "disclosure_sent": True,
                "user_key": self.USER_KEY,
                "chat_id": "owner@s.whatsapp.net",
                "message_id": "wamid.LIVE",
            }
        self.addCleanup(self._drop_context)
        for target in (
            patch.object(gates, "_ONBOARDING_STATE", {}),
            patch.object(gates, "_persist_onboarding_state"),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _drop_context(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def _run(self, args):
        def fake_request(action, user_key, facts=None, body=None):
            return {"success": True, "created": False}

        with patch.object(gates, "_convex_request", fake_request):
            return json.loads(gates._save_onboarding(args, session_id=self.SESSION))

    def test_the_city_question_answered_with_a_gender_leaves_the_field_open(self) -> None:
        """5 Sep 2026, 12:30 IST, verbatim from the gateway store."""
        self._run(
            {
                "current_field": "timeZone",
                "completed_field": "weight",
                "profile": {"weight_kg": 66},
            }
        )
        result = self._run(
            {
                "current_field": "nutrition",
                "completed_field": "goal",
                "profile": {"goal": "gainWeight"},
            }
        )

        self.assertEqual(result["unanswered"], ["timeZone"])
        self.assertIn("Ask for each one again", result["note"])

    def test_the_weight_question_answered_with_a_gender_leaves_the_field_open(self) -> None:
        """4 Sep 2026, 14:16 IST. The model moved to weight and never returned."""
        self._run(
            {
                "current_field": "weight",
                "completed_field": "height",
                "profile": {"height_cm": 175},
            }
        )
        result = self._run({"current_field": "goal"})

        self.assertEqual(result["unanswered"], ["weight"])

    def test_a_flow_that_answers_every_question_is_never_flagged(self) -> None:
        self._run(
            {"current_field": "age", "completed_field": "name", "profile": {"name": "Vandy"}}
        )
        self._run(
            {"current_field": "height", "completed_field": "age", "profile": {"age": 32}}
        )
        result = self._run(
            {
                "current_field": "weight",
                "completed_field": "height",
                "profile": {"height_cm": 173},
            }
        )

        self.assertNotIn("unanswered", result)
        self.assertNotIn("note", result)

    def test_answering_the_skipped_question_later_clears_it(self) -> None:
        self._run({"current_field": "timeZone", "completed_field": "weight"})
        flagged = self._run({"current_field": "nutrition", "completed_field": "goal"})
        self.assertEqual(flagged["unanswered"], ["timeZone"])

        result = self._run(
            {
                "current_field": "steps",
                "completed_field": "timeZone",
                "profile": {"time_zone": "Asia/Kolkata"},
            }
        )

        self.assertNotIn("unanswered", result)

    def test_a_step_with_a_default_is_not_treated_as_a_lost_answer(self) -> None:
        """nutrition, steps, water and the reminder steps all have defaults, so
        passing one with nothing sent is ordinary, not a dropped answer."""
        self._run({"current_field": "steps", "completed_field": "nutrition"})
        result = self._run({"current_field": "water", "completed_field": "workouts"})

        self.assertNotIn("unanswered", result)


