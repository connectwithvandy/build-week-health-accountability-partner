import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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


VANDY_DISCLOSURE = f"hey Vandy 🙂\n\n{DISCLOSURE_MESSAGE}\n\n{GOAL_QUESTION}"


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
        self.assertEqual(after_age, "before i can do that maths — how tall are you?")

    def test_blocks_under_18(self) -> None:
        history = [message("user", "I am 17 and want to track calories")]
        self.assertEqual(
            calorie_gate(history, history[0]["content"], "Try 1,400 calories."),
            "I can’t provide calorie numbers because this beta is only for adults.",
        )

    def test_requires_one_missing_maintenance_input(self) -> None:
        history = [message("user", "I am 33, 5 ft, 58 kg and female")]
        self.assertEqual(
            calorie_gate(history, "Estimate maintenance calories", "2,300 calories"),
            "last one — how active is a normal day? desk most of it, on your feet, "
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
            "rough maintenance is about 2,080 calories a day — "
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

    def test_disclosure_and_goal_go_out_as_one_message(self) -> None:
        """SCOPING.md §3.4: both in the same message, so neither can be lost."""
        self.assertEqual(
            DISCLOSURE_MESSAGE,
            "Ted stores your profile, messages, plans, logs and uploads. Read "
            "more: https://heyted.vercel.app/privacy. Send “delete my data” "
            "anytime to delete everything.",
        )
        # The constant stays the disclosure alone; the two are joined at
        # send time so the privacy text has exactly one definition.
        self.assertNotIn(GOAL_QUESTION, DISCLOSURE_MESSAGE)
        delivered = gates._personalized_disclosure("Vandy")
        self.assertIn(DISCLOSURE_MESSAGE, delivered)
        self.assertIn(GOAL_QUESTION, delivered)
        self.assertTrue(delivered.endswith(GOAL_QUESTION))
        # No background sender left to stall.
        self.assertFalse(hasattr(gates, "_schedule_goal_question"))
        self.assertFalse(hasattr(gates, "_send_goal_question"))

    def test_calorie_gate_does_not_skip_name_or_disclosure(self) -> None:
        first_turn = [message("user", "Track calories")]
        self.assertIsNone(
            transform_response(
                history=first_turn,
                user_message="Track calories",
                response_text="What should I call you?",
            )
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
            "What should I call you?",
        )

    def test_new_chat_cannot_advance_to_another_question_before_the_name(self) -> None:
        history = [message("user", "Hi")]
        self.assertEqual(
            transform_response(
                history=history,
                user_message="Hi",
                response_text="What health goal are you working on?",
            ),
            "What should I call you?",
        )

    def test_removes_unproven_save_claim_but_keeps_the_real_question(self) -> None:
        self.assertEqual(
            action_claim_gate(
                "Good to know, 33 noted. But losing, maintaining, or building—which one?",
                action_succeeded=False,
            ),
            "Losing, maintaining, or building—which one?",
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
            "I haven’t completed that action.",
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
            "I haven’t completed that action.",
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
            "I haven’t completed that action.",
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
        self.assertIsNone(
            _transform_live_response(
                platform="whatsapp",
                session_id=session_id,
                response_text="routine is broad—what should look different?",
            )
        )
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
            self.assertIsNone(
                _transform_live_response(
                    platform="whatsapp",
                    session_id=second_session,
                    response_text="routine is broad—what should look different?",
                )
            )
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
        # The goal question rides inside the disclosure now, so it is asked
        # exactly once and never as a second bubble that can fail alone.
        self.assertEqual(sum(GOAL_QUESTION in reply for reply in visible_replies), 1)
        self.assertEqual(
            visible_replies,
            [
                VANDY_DISCLOSURE,
                model_replies[1],
                model_replies[2],
                model_replies[3],
            ],
        )
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
        self.assertEqual(replies[3:], [None, None])

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
            "I haven’t completed that action.",
        )

    def test_the_check_in_claim_no_longer_slips_through(self) -> None:
        """The false claim the cron gate was built to catch, and missed."""
        self.assertEqual(
            action_claim_gate("chalo, 8pm check-in is set."),
            "I haven’t completed that action.",
        )

    def test_other_scheduling_promises_are_caught(self) -> None:
        for reply in (
            "I'll remind you at 8pm.",
            "I'll ping you tomorrow morning.",
            "that's on for tomorrow morning.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), "I haven’t completed that action."
                )

    def test_real_scheduling_replies_from_the_2_sep_thread(self) -> None:
        """Both slipped the gate live; both are true, so both need a tool."""
        for reply in (
            "all 5 pings are set — coq10 8:45am, omega3+b12 10:30am 💊",
            "done, one-off ping at 5pm today for the vitamin 👍",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), "I haven’t completed that action."
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
            "I haven’t completed that action.",
        )

    def test_other_ways_of_confirming_a_deletion_are_caught(self) -> None:
        for reply in (
            "all cleared, fresh start whenever you want.",
            "that's wiped — nothing left on my side.",
            "your data's gone.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    action_claim_gate(reply), "I haven’t completed that action."
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
        """Run a tool handler, returning the payload it would send to Convex."""
        sent: dict[str, object] = {}

        def fake_request(action, user_key, facts=None, body=None):
            sent.update({"action": action, "user_key": user_key, "body": body or {}})
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
        # One message carries both, so there is no window in which the
        # disclosure has landed and the goal question is still owed.
        self.assertIn(gates.PRIVACY_URL, delivered)
        self.assertIn(GOAL_QUESTION, delivered)
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

        # 2. The name. Disclosure and goal question arrive as ONE message.
        disclosure = self.turn("Vandy", "nice to meet you")
        self.assertEqual(disclosure, VANDY_DISCLOSURE)
        self.assertIn(gates.PRIVACY_URL, disclosure)
        self.assertIn(GOAL_QUESTION, disclosure)

        # 3. The goal, then the check-in time. Ted's own words survive.
        self.assertEqual(
            self.turn("eat more protein", "good one. what time should i check in?"),
            "good one. what time should i check in?",
        )
        self.assertEqual(self.turn("8pm, Bangalore", "locked."), "locked.")

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

        # 8. "delete my data" — claiming deletion with no tool behind it is
        #    replaced, however confidently the model said it.
        refused = self.turn("delete my data", "Done, everything has been deleted.")
        self.assertEqual(refused, gates.CLAIM_NOT_DONE)

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
            self.assertIn(gates._DISCLOSURE_MARKER, reply or "")
            self.assertIn(GOAL_QUESTION, reply or "")
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
        self.addCleanup(gates._forget_user, self.KEY)
        self.addCleanup(gates._forget_user, self.ADULT)

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
