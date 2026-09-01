import unittest

from hermes.ted_safety_gates import (
    DISCLOSURE_MESSAGE,
    action_claim_gate,
    calorie_gate,
    consent_gate,
    transform_response,
    _capture_turn,
    _record_tool_success,
    _transform_live_response,
)


def message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class TedSafetyGatesTest(unittest.TestCase):
    def test_replays_calorie_failure_without_returning_a_number(self) -> None:
        history: list[dict[str, str]] = []
        expected = "I need your age before I can give calorie numbers."

        for user_text in ("Track calories", "It's ragi roti", "It's only 1 roti"):
            history.append(message("user", user_text))
            reply = calorie_gate(history, user_text, "About 120 calories.")
            self.assertEqual(reply, expected)
            self.assertNotRegex(reply or "", r"\b120\b")
            history.append(message("assistant", reply or ""))

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
        self.assertEqual(consent_gate(history, "What is your goal?"), DISCLOSURE_MESSAGE)

        history.append(message("assistant", DISCLOSURE_MESSAGE))
        self.assertIsNone(consent_gate(history, "What is your goal?"))

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
            DISCLOSURE_MESSAGE,
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


if __name__ == "__main__":
    unittest.main()
