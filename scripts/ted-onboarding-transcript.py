#!/usr/bin/env python3
"""Replay a WhatsApp onboarding against the live gates and print the transcript.

Not a mock of the gates. It imports `hermes/ted_safety_gates/__init__.py` — the
same file the gateway loads through `~/.hermes/plugins/ted-safety-gates` — and
drives the same two hooks Hermes drives, `pre_llm_call` and
`transform_llm_output`, in the same order, with the same keyword arguments.

What it stands in for is the two things either side of the gates:

  * The gateway's inbound assembly. A WhatsApp reply does not arrive as the
    words the user typed: `gateway/run.py:12057` prepends
    `[Replying to: "<up to 500 chars of the quoted message>"]` and a blank
    line. `_inbound` below builds that string byte for byte, which is what
    makes the quoted-reply cases in here real rather than illustrative.
  * The model. Each turn carries the reply the model actually produced on
    3 Sep where the log recorded one, and a plausible one where it did not.
    The point of every case is what the gates do with a given model reply, so
    the model reply is an input here, not something to be discovered.

Run offline, always. State goes to a temporary directory and the Convex
variables are removed before import, so nothing here can read or write a real
user. That is also why the erasure cases stop at the confirmation question:
with no Convex the deletion tool cannot run, and what these cases are about is
the question and the cancellation, which are pure gate logic.

    .venv/bin/python scripts/ted-onboarding-transcript.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_SANDBOX = Path(tempfile.mkdtemp(prefix="ted-transcript-"))
(_SANDBOX / "state").mkdir()
(_SANDBOX / "logs").mkdir()
os.environ["TED_GATES_STATE_DIR"] = str(_SANDBOX / "state")
os.environ["TED_GATES_AGENT_LOG"] = str(_SANDBOX / "logs" / "agent.log")
os.environ["TED_GATES_DISABLE_CRON"] = "1"
os.environ.pop("TED_CONVEX_SITE_URL", None)
os.environ.pop("TED_HERMES_SHARED_SECRET", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hermes import ted_safety_gates as gates  # noqa: E402

# A number nobody has used. The gate hashes it, so the key below is derived
# the same way the gateway derives it for a real sender.
SENDER = "919812340000@lid"
SESSION = "20260904_000000_transcript"


class Thread:
    """One WhatsApp conversation, driven through the real hooks."""

    def __init__(self, case: str) -> None:
        self.case = case
        self.history: list[dict[str, str]] = []
        self.delivered: list[str] = []
        self.lines: list[str] = []
        self.user_key = gates._user_state_key("whatsapp", SENDER, SESSION)
        # A brand-new user: no state of any kind under this key.
        gates._forget_user(self.user_key)
        with gates._ONBOARDING_LOCK:
            gates._ONBOARDING_STATE.pop(self.user_key, None)
        gates._DISCLOSURE_SENT_KEYS.discard(self.user_key)
        with gates._TURN_LOCK:
            gates._TURN_ARRIVALS.pop(self.user_key, None)
            gates._TURN_CONTEXT.pop(SESSION, None)

    @staticmethod
    def _inbound(typed: str, quoting: str | None) -> str:
        """The string Hermes hands the plugin. gateway/run.py:12037-12057."""
        if quoting is None:
            return typed
        return f'[Replying to: "{quoting[:500]}"]\n\n{typed}'

    def send(self, typed: str, model_reply: str, quoting: str | None = None) -> str:
        inbound = self._inbound(typed, quoting)
        self.history.append({"role": "user", "content": inbound})

        gates._capture_turn(
            platform="whatsapp",
            session_id=SESSION,
            task_id="",
            turn_id=len(self.history),
            sender_id=SENDER,
            user_message=inbound,
            conversation_history=list(self.history),
            is_first_turn=len(self.history) == 1,
            model="anthropic/claude-sonnet-5",
        )
        gated = gates._transform_live_response(
            platform="whatsapp",
            session_id=SESSION,
            response_text=model_reply,
            model="anthropic/claude-sonnet-5",
        )
        sent = model_reply if gated is None else gated
        gates._log_disclosure(
            platform="whatsapp", session_id=SESSION, assistant_response=sent
        )
        # Hermes writes the model's own text to the transcript, not the text
        # the gate substituted. That asymmetry is real and the gates are built
        # around it, so this mirrors it rather than tidying it away.
        self.history.append({"role": "assistant", "content": model_reply})
        self.delivered.append(sent)

        if quoting is not None:
            self.lines.append(f'USER  (reply, quoting: "{_one_line(quoting)}")')
            self.lines.append(_indent(typed))
        else:
            self.lines.append("USER")
            self.lines.append(_indent(typed))
        self.lines.append("MODEL WROTE")
        self.lines.append(_indent(model_reply))
        self.lines.append(
            "TED SENT" + ("" if sent != model_reply else "  (unchanged)")
        )
        self.lines.append(_indent(sent))
        self.lines.append("")
        return sent

    def report(self) -> str:
        head = f"{'=' * 74}\nCASE: {self.case}\n{'=' * 74}"
        return "\n".join([head, ""] + self.lines)


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.split("\n"))


def _one_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= 60 else flat[:57] + "..."


def case_normal_onboarding() -> Thread:
    t = Thread("normal onboarding, brand-new user")
    t.send("hey", "hello! i'm Ted, let me tell you everything about how i work.")
    t.send("UD", "nice to meet you, what's your goal?")
    t.send("more energy in the afternoons", "good one. what time should i check in?")
    return t


def case_the_counted_five() -> Thread:
    """Name to number, the whole way, with a hedge in the middle.

    The point of running this one is that the model is writing something
    different every turn and none of it goes out: while the five are running
    the count belongs to Ted, not to whatever the model decided to ask.
    """
    t = Thread("the counted five, name to number")
    t.send("hey", "hi! what brings you here?")
    t.send("Pallavi", "lovely to meet you, what are your goals?")
    t.send("31", "got it, and your height?")
    t.send("5 foot 4", "thanks! weight next?")
    t.send("around 60-65", "ok, noting 60kg")
    t.send("63 actually", "great, and are you male or female?")
    t.send("female", "last one, activity level?")
    t.send("desk most of it", "perfect, here's your target")
    t.send("yep", "here we go")
    return t


def case_five_questions_abandoned() -> Thread:
    """Three tries and Ted stops, which is the bound the name question has."""
    t = Thread("the five, never answered")
    t.send("hey", "hi!")
    t.send("Ankie", "nice to meet you")
    t.send("what do you even do", "i'm a health coach on whatsapp!")
    t.send("i dont get it", "happy to explain anything you like")
    t.send("hmm", "ask me anything at all")
    return t


def case_quoted_bot_text() -> Thread:
    t = Thread("a WhatsApp reply quoting Ted's own message")
    t.send("hey", "hi there")
    t.send("UD", "nice to meet you")
    # The real 22:58:15 turn: a reply quoting Ted's name question.
    t.send(
        "this should have some personality like, i don't know what you're "
        "saying i think you're confusing me with someone else",
        "haha nah wrong number vibes over here, it's just me \U0001f604 so what's "
        "the one thing you want to change?",
        quoting=t.delivered[0],
    )
    return t


def case_feedback_instead_of_an_answer() -> Thread:
    t = Thread("feedback where the name should be")
    t.send("hey", "hi")
    # The real 22:57:39 and 22:57:49 turns, and the real 22:57:52 model reply.
    t.send(
        "that's a good start vandana, but keep it short. most people will come "
        "from your website so they will know about your product a little bit",
        "fair. noted \U0001f642 so what should i call you?",
    )
    t.send(
        "i like this as well. it's just a smaller feedback",
        "cool, glad it landed \U0001f642 so, what should i call you?",
    )
    return t


def case_praise_with_privacy_words() -> Thread:
    t = Thread("praise for the privacy disclosure, quoting it")
    t.send("hey", "hi")
    t.send("UD", "nice to meet you")
    disclosure = t.delivered[-1]
    # The real 22:58:41 turn, quoting the real disclosure bubble.
    t.send(
        "i love this. this is a really good thing about security you've done",
        "glad it makes sense \U0001f642 so what's the one thing you want to change?",
        quoting=disclosure,
    )
    return t


def case_repeated_name() -> Thread:
    t = Thread("the name given, then asked for again")
    t.send("hey", "hi")
    t.send("UD", "nice to meet you")
    t.send(
        "cool",
        "so what should i call you?",
    )
    t.send(
        "i already told you",
        "sorry! what should i call you?",
    )
    return t


def case_delete_then_cancel() -> Thread:
    t = Thread("delete, then cancelled before confirming")
    t.send("hey", "hi")
    t.send("UD", "nice to meet you")
    t.send("delete my data", "sure, are you certain?")
    t.send("no wait", "nothing has been deleted, it's all still here.")
    t.send("what's my name", "you're UD.")
    return t


def main() -> int:
    cases = [
        case_normal_onboarding,
        case_the_counted_five,
        case_five_questions_abandoned,
        case_quoted_bot_text,
        case_feedback_instead_of_an_answer,
        case_praise_with_privacy_words,
        case_repeated_name,
        case_delete_then_cancel,
    ]
    print(f"gates source: {gates.__file__}")
    print(f"convex reachable: {gates._convex_available()}  (offline by design)")
    print(f"user key: {gates._user_state_key('whatsapp', SENDER, SESSION)}")
    print()
    threads = []
    for case in cases:
        thread = case()
        threads.append(thread)
        print(thread.report())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
