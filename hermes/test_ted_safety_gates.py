import json
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


VANDY_DISCLOSURE = f"hey Vandy 🙂\n\n{DISCLOSURE_MESSAGE}"


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

    def test_disclosure_is_one_short_message_without_the_goal(self) -> None:
        self.assertEqual(
            DISCLOSURE_MESSAGE,
            "Ted stores your profile, messages, plans, logs and uploads. Read "
            "more: https://heyted.vercel.app/privacy. Send “delete my data” "
            "anytime to delete everything.",
        )
        self.assertNotIn(GOAL_QUESTION, DISCLOSURE_MESSAGE)

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
                response_text="What fitness goal are you working on?",
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

        with (
            patch.object(gates, "_persist_disclosure_state"),
            patch.object(gates, "_schedule_goal_question") as schedule,
        ):
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
            schedule.assert_called_once_with(sender_id, user_key)

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

        with (
            patch.object(gates, "_persist_disclosure_state"),
            patch.object(gates, "_schedule_goal_question"),
        ):
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

        with (
            patch.object(gates, "_persist_disclosure_state"),
            patch.object(
                gates,
                "_schedule_goal_question",
                side_effect=lambda _chat_id, _user_key: visible_replies.append(
                    GOAL_QUESTION
                ),
            ),
        ):
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
        self.assertEqual(visible_replies.count(GOAL_QUESTION), 1)
        self.assertEqual(
            visible_replies,
            [
                VANDY_DISCLOSURE,
                GOAL_QUESTION,
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

    def test_ordinary_fitness_talk_is_not_a_deletion_claim(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
