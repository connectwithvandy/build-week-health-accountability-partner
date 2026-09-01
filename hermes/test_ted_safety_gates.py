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
        expected = "I need your age before I can give calorie numbers."

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
        meal_gate = transform_response(
            history=history,
            user_message="Meal and steps",
            response_text="roughly 280 calories, 14g protein.",
        )
        self.assertEqual(meal_gate, "I need your age before I can give calorie numbers.")
        history.append(message("assistant", meal_gate or ""))
        self.assertIsNone(
            transform_response(
                history=history,
                user_message="33",
                response_text="got it — what's your daily step target?",
            )
        )

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
            "I need your activity level before I can estimate maintenance calories.",
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
            "Your estimated maintenance is roughly 2,080 calories a day, based only on the values you gave me.",
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
            [{"key": "name", "value": "Vandy"}],
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


if __name__ == "__main__":
    unittest.main()
