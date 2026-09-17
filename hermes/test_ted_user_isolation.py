"""Roadmap T02: two users, at the same time, never crossing.

The suite already proves isolation one user at a time. Nothing proved it under
concurrency, and concurrency is where a shared module-level dict actually
leaks: the gate holds every user's onboarding, disclosure, pause, language and
pending-measurement state in process globals, keyed by user, guarded by two
locks. A key built in the wrong scope, or a read outside the lock, crosses one
person's health data into another's conversation.

These tests deliberately interleave. Each one runs both users on real threads
and holds them at a barrier so both are inside the same critical section at
once, rather than trusting that a sequential pass implies a concurrent one.

The two users are built to conflict on every field a leak could travel
through: different ages, weights, goals, languages, timezones and reminder
times, so a crossed value is wrong rather than coincidentally equal.
"""

from __future__ import annotations

import threading
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

from hermes import ted_safety_gates as gates


ASHA = "whatsapp:sha256:" + "a" * 64
BILAL = "whatsapp:sha256:" + "b" * 64

# Deliberately conflicting. No field is equal, so any crossed value is visible.
PROFILES = {
    ASHA: {"name": "Asha", "age": 34, "weight_kg": 58.0, "height_cm": 160.0,
           "goal": "maintain", "language": "english"},
    BILAL: {"name": "Bilal", "age": 47, "weight_kg": 91.0, "height_cm": 178.0,
            "goal": "lose", "language": "hinglish"},
}


def both(work) -> list:
    """Run `work(user_key)` for both users on threads, interleaved at a barrier.

    The barrier is the point. Without it the two threads usually run one after
    the other and the test proves nothing about concurrency.
    """
    gate = threading.Barrier(2, timeout=5)
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def run(key: str) -> None:
        try:
            gate.wait()
            results[key] = work(key)
        except BaseException as error:  # noqa: BLE001 - re-raised below
            errors.append(error)

    threads = [threading.Thread(target=run, args=(k,)) for k in (ASHA, BILAL)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    if errors:
        raise errors[0]
    return [results.get(ASHA), results.get(BILAL)]


class ConcurrentUserIsolationTest(unittest.TestCase):
    """Two people, same instant, separate state."""

    def setUp(self) -> None:
        for key in (ASHA, BILAL):
            gates._forget_user(key)
        self.addCleanup(lambda: [gates._forget_user(k) for k in (ASHA, BILAL)])

    def test_concurrent_onboarding_keeps_each_profile_whole(self) -> None:
        def write(key: str) -> None:
            profile = PROFILES[key]
            gates._remember_name(key, profile["name"])
            gates._remember_age(key, profile["age"])
            for field in ("weight_kg", "height_cm"):
                gates._remember_measurement(key, field, profile[field])
            gates._update_onboarding(key, goal=profile["goal"])

        both(write)

        for key, profile in PROFILES.items():
            with self.subTest(user=profile["name"]):
                self.assertEqual(gates._known_name(key), profile["name"])
                self.assertEqual(gates._stored_age(key), profile["age"])
                self.assertEqual(gates._stored_measurement(key, "weight_kg"),
                                 profile["weight_kg"])
                self.assertEqual(gates._stored_measurement(key, "height_cm"),
                                 profile["height_cm"])
                self.assertEqual(gates._onboarding(key).get("goal"), profile["goal"])

    def test_a_pending_measurement_is_never_answered_by_the_other_user(self) -> None:
        """Both say a bare number at once. Each must land on their own row."""
        def stage(key: str) -> None:
            gates._set_pending_measurement(key, "weight_kg",
                                           PROFILES[key]["weight_kg"])

        both(stage)

        for key, profile in PROFILES.items():
            with self.subTest(user=profile["name"]):
                pending = gates._pending_measurement(key)
                self.assertIsNotNone(pending)
                self.assertEqual(pending["value"], profile["weight_kg"])

    def test_concurrent_corrections_do_not_overwrite_the_other_user(self) -> None:
        """"actually i'm 30" from one person, at the same moment as the other."""
        both(lambda key: gates._remember_age(key, PROFILES[key]["age"]))
        both(lambda key: gates._remember_age(key, PROFILES[key]["age"] + 1))

        self.assertEqual(gates._stored_age(ASHA), PROFILES[ASHA]["age"] + 1)
        self.assertEqual(gates._stored_age(BILAL), PROFILES[BILAL]["age"] + 1)

    def test_a_pause_by_one_user_does_not_pause_the_other(self) -> None:
        today = date(2026, 9, 17)
        gates._mark_paused(ASHA, date(2026, 9, 20))

        self.assertIsNotNone(gates._paused_until(ASHA, today))
        self.assertIsNone(gates._paused_until(BILAL, today))

    def test_language_preference_does_not_cross(self) -> None:
        """One writes English, one code-switches, at the same time.

        English needs `_ENGLISH_EVIDENCE_NEEDED` messages before it is a
        preference; Hinglish needs one. So the two users are driven to the two
        settled ends rather than to the shared "not decided yet" both start in.
        """
        def talk(key: str) -> None:
            if key == BILAL:
                gates._note_language(key, "kal dinner mein dal chawal tha yaar")
            else:
                for _ in range(gates._ENGLISH_EVIDENCE_NEEDED):
                    gates._note_language(key, "had dal and rice for dinner")

        both(talk)

        self.assertEqual(gates._language_preference(ASHA), "writes_english")
        self.assertEqual(gates._language_preference(BILAL), "")
        # and the underlying marks never crossed either
        self.assertTrue(gates._onboarding(BILAL).get("writes_hinglish"))
        self.assertFalse(gates._onboarding(ASHA).get("writes_hinglish"))

    def test_deleting_one_user_while_the_other_is_active_leaves_the_other_whole(self) -> None:
        """T02's explicit case: erasure during a live conversation."""
        both(lambda key: gates._remember_name(key, PROFILES[key]["name"]))
        both(lambda key: gates._remember_age(key, PROFILES[key]["age"]))

        ready = threading.Barrier(2, timeout=5)
        surviving: dict[str, object] = {}

        def erase() -> None:
            ready.wait()
            gates._forget_user(ASHA, history_length=12)

        def keep_talking() -> None:
            ready.wait()
            for _ in range(40):
                gates._update_onboarding(BILAL, goal=PROFILES[BILAL]["goal"])
            surviving["age"] = gates._stored_age(BILAL)
            surviving["name"] = gates._known_name(BILAL)

        threads = [threading.Thread(target=erase), threading.Thread(target=keep_talking)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        # the deleted user keeps only the tombstone
        self.assertIsNone(gates._stored_age(ASHA))
        self.assertEqual(sorted(gates._onboarding(ASHA)),
                         ["forgotten_at", "forgotten_at_index"])
        # the active user is untouched throughout
        self.assertEqual(surviving.get("age"), PROFILES[BILAL]["age"])
        self.assertEqual(surviving.get("name"), PROFILES[BILAL]["name"])
        self.assertEqual(gates._stored_age(BILAL), PROFILES[BILAL]["age"])

    def test_a_burst_from_one_user_never_writes_under_the_other_key(self) -> None:
        """Rapid-fire messages: the loser of a race must still be the right row."""
        def burst(key: str) -> None:
            for index in range(60):
                gates._update_onboarding(key, burst_marker=f"{key[-3:]}-{index}")

        both(burst)

        self.assertTrue(gates._onboarding(ASHA)["burst_marker"].startswith("aaa-"))
        self.assertTrue(gates._onboarding(BILAL)["burst_marker"].startswith("bbb-"))

    def test_an_empty_user_key_never_reads_or_writes_anybody(self) -> None:
        """The failure that would make every test above pass by accident."""
        gates._remember_name("", "Nobody")
        gates._remember_age("", 30)
        gates._update_onboarding("", goal="lose")

        self.assertEqual(gates._onboarding(""), {})
        for key in (ASHA, BILAL):
            self.assertIsNone(gates._known_name(key))


class FileBoundaryTest(unittest.TestCase):
    """Roadmap T01, expressed as a test rather than a note in a document.

    An isolation suite that passes while a chat user can reach the file tool
    is proving the wrong thing. This fails until the lock is applied, so the
    state of T01 is something the test run reports rather than something
    somebody has to remember.
    """

    CONFIG = Path.home() / ".hermes" / "config.yaml"
    ALLOWED = {"cronjob", "ted", "vision"}

    def whatsapp_toolsets(self) -> list[str] | None:
        try:
            lines = self.CONFIG.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        try:
            top = next(i for i, line in enumerate(lines) if line == "platform_toolsets:")
            start = next(i for i in range(top + 1, len(lines))
                         if lines[i] == "  whatsapp:")
        except StopIteration:
            return None
        found = []
        for line in lines[start + 1:]:
            if not line.startswith("    - "):
                break
            found.append(line.removeprefix("    - ").strip())
        return found

    def test_whatsapp_cannot_reach_the_file_tool(self) -> None:
        toolsets = self.whatsapp_toolsets()
        if toolsets is None:
            self.skipTest("no live ~/.hermes/config.yaml on this machine")
        extra = sorted(set(toolsets) - self.ALLOWED)
        self.assertEqual(
            extra, [],
            f"WhatsApp users can reach {extra}. Apply the lock: "
            "python3 scripts/ted-lock-whatsapp-tools.py --apply",
        )


if __name__ == "__main__":
    unittest.main()


class VisionPathBoundaryTest(unittest.TestCase):
    """T01's second door: vision_analyze takes a path, and the lock misses it.

    The half that must keep working is tested first and hardest. A guard that
    stops food photos is not a fix, it is an outage with a security rationale.
    """

    SESSION = "sess-whatsapp-1"

    def setUp(self) -> None:
        self.cache = Path(gates._MEDIA_CACHE_ROOTS[0])
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[self.SESSION] = {"chat_id": "918888888888@lid"}
        self.addCleanup(self._drop_context)

    def _drop_context(self) -> None:
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT.pop(self.SESSION, None)

    def guard(self, source: str, session: str | None = None):
        return gates._vision_scope_guard(
            tool_name="vision_analyze",
            session_id=self.SESSION if session is None else session,
            args={"image_url": source, "question": "what is this"},
        )

    # --- the photos that must keep working -------------------------------

    def test_a_photo_sent_to_ted_is_allowed(self) -> None:
        self.assertIsNone(self.guard(str(self.cache / "images" / "img_9f76b832f3d5.jpg")))

    def test_every_media_cache_root_is_allowed(self) -> None:
        for root in gates._MEDIA_CACHE_ROOTS:
            with self.subTest(root=root.name):
                self.assertIsNone(self.guard(str(Path(root) / "photo.jpg")))

    def test_a_voice_note_path_is_allowed(self) -> None:
        self.assertIsNone(self.guard(str(self.cache / "audio" / "voice_abc.ogg")))

    def test_a_file_url_into_the_cache_is_allowed(self) -> None:
        self.assertIsNone(self.guard("file://" + str(self.cache / "images" / "a.jpg")))

    def test_a_data_url_is_allowed(self) -> None:
        """Inline bytes never touch this disk."""
        self.assertIsNone(self.guard("data:image/png;base64,iVBORw0KGgo="))

    def test_an_http_url_is_left_to_hermes(self) -> None:
        for url in ("https://example.com/a.jpg", "http://example.com/a.jpg"):
            with self.subTest(url=url):
                self.assertIsNone(self.guard(url))

    def test_a_missing_source_is_left_to_hermes_own_error(self) -> None:
        self.assertIsNone(self.guard(""))

    # --- the reads that must not happen ----------------------------------

    def test_a_photo_elsewhere_on_the_laptop_is_refused(self) -> None:
        blocked = self.guard(str(Path.home() / "Pictures" / "family.jpg"))
        self.assertEqual(blocked, {"action": "block",
                                   "message": gates.VISION_OUT_OF_SCOPE})

    def test_walking_out_of_the_cache_is_refused(self) -> None:
        """`..` is resolved before it is compared, never matched as text."""
        escape = str(self.cache / "images" / ".." / ".." / ".." / "Pictures" / "x.jpg")
        self.assertIsNotNone(self.guard(escape))

    def test_a_path_that_only_looks_like_the_cache_is_refused(self) -> None:
        self.assertIsNotNone(self.guard(str(Path.home() / ".hermes-evil" / "cache" / "x.jpg")))

    def test_a_bare_relative_name_is_refused(self) -> None:
        """Hermes accepts "pic.png" and resolves it against its own cwd."""
        self.assertIsNotNone(self.guard("pic.png"))

    def test_a_credential_file_is_refused_here_too(self) -> None:
        """Hermes blocks these as well. Two locks on one door is correct."""
        for secret in ("~/.hermes/.env", str(Path.home() / ".hermes" / "auth.json")):
            with self.subTest(path=secret):
                self.assertIsNotNone(self.guard(secret))

    def test_a_system_path_is_refused(self) -> None:
        for path in ("/etc/passwd", "/Users/vandana.agarwal/Documents", "~/Desktop/a.png"):
            with self.subTest(path=path):
                self.assertIsNotNone(self.guard(path))

    # --- scope of the guard itself ---------------------------------------

    def test_other_tools_are_untouched(self) -> None:
        self.assertIsNone(gates._vision_scope_guard(
            tool_name="ted_log_entry", session_id=self.SESSION,
            args={"image_url": "/etc/passwd"}))

    def test_a_non_whatsapp_turn_is_left_alone(self) -> None:
        """The CLI owns this machine. Guarding it would break unrelated work."""
        self.assertIsNone(self.guard("/etc/passwd", session="sess-cli-unknown"))

    def test_the_guard_is_registered_on_pre_tool_call(self) -> None:
        """A guard nobody wired in is a comment."""
        hooks: list[tuple[str, object]] = []

        class Ctx:
            def register_hook(self, name, fn):
                hooks.append((name, fn))
            def __getattr__(self, _name):
                return lambda *a, **k: None

        try:
            gates.register(Ctx())
        except Exception:  # noqa: BLE001 - register does more than hooks
            pass
        self.assertIn(("pre_tool_call", gates._vision_scope_guard), hooks)


class ConvexScopeIsolationTest(unittest.TestCase):
    """T02, the stores past the gate's own dicts.

    Every Convex read and write is scoped by `user_key`. Nothing proved that
    the memory cache in front of it keeps two users apart, and that cache is a
    single process-wide dict read under a lock, which is exactly the shape
    that leaks under concurrency.
    """

    def setUp(self) -> None:
        with gates._TURN_LOCK:
            gates._MEMORY_CACHE.clear()
        self.addCleanup(self._clear)

    def _clear(self) -> None:
        with gates._TURN_LOCK:
            gates._MEMORY_CACHE.clear()

    def answers_per_user(self):
        """A fake Convex that returns the caller's own key in the payload."""
        asked: list[str] = []

        def responder(action, user_key, **_):
            asked.append(user_key)
            return {"success": True, "facts": [{"key": "owner", "value": user_key}]}

        return responder, asked

    def test_two_users_reading_at_once_each_get_their_own_facts(self) -> None:
        responder, _asked = self.answers_per_user()
        with unittest.mock.patch.object(gates, "_convex_request", responder):
            results = both(gates._cached_user_memory)

        for result, key in zip(results, (ASHA, BILAL)):
            self.assertEqual(result["facts"][0]["value"], key)

    def test_the_cache_holds_a_separate_entry_per_user(self) -> None:
        responder, _ = self.answers_per_user()
        with unittest.mock.patch.object(gates, "_convex_request", responder):
            both(gates._cached_user_memory)

        with gates._TURN_LOCK:
            cached = dict(gates._MEMORY_CACHE)
        self.assertEqual(set(cached), {ASHA, BILAL})
        for key, (_when, payload) in cached.items():
            self.assertEqual(payload["facts"][0]["value"], key)

    def test_a_cached_read_never_serves_the_other_user(self) -> None:
        """Asha's cached answer must not satisfy Bilal's read."""
        responder, asked = self.answers_per_user()
        with unittest.mock.patch.object(gates, "_convex_request", responder):
            gates._cached_user_memory(ASHA)
            gates._cached_user_memory(ASHA)          # served from cache
            bilal = gates._cached_user_memory(BILAL)  # must go to the backend

        self.assertEqual(bilal["facts"][0]["value"], BILAL)
        self.assertEqual(asked, [ASHA, BILAL])

    def test_invalidating_one_user_leaves_the_other_cached(self) -> None:
        responder, asked = self.answers_per_user()
        with unittest.mock.patch.object(gates, "_convex_request", responder):
            gates._cached_user_memory(ASHA)
            gates._cached_user_memory(BILAL)
            gates._invalidate_user_memory(ASHA)
            gates._cached_user_memory(ASHA)   # re-read
            gates._cached_user_memory(BILAL)  # still cached

        self.assertEqual(asked, [ASHA, BILAL, ASHA])

    def test_a_failed_read_is_never_cached_for_anyone(self) -> None:
        calls: list[str] = []

        def failing(action, user_key, **_):
            calls.append(user_key)
            return {"success": False, "storage_error": True}

        with unittest.mock.patch.object(gates, "_convex_request", failing):
            gates._cached_user_memory(ASHA)
            gates._cached_user_memory(ASHA)

        self.assertEqual(calls, [ASHA, ASHA])
        with gates._TURN_LOCK:
            self.assertNotIn(ASHA, gates._MEMORY_CACHE)

    def test_a_write_carries_the_callers_key_and_no_other(self) -> None:
        seen: list[tuple[str, str]] = []

        def responder(action, user_key, **_):
            seen.append((action, user_key))
            return {"success": True}

        with unittest.mock.patch.object(gates, "_convex_request", responder):
            both(lambda key: gates._convex_write("save", key))

        self.assertEqual(sorted(k for _a, k in seen), sorted([ASHA, BILAL]))


class LogContentTest(unittest.TestCase):
    """Roadmap T35: operational logs must not become a second health store.

    Inspection said the reply-handling log lines carry `user_key` and never
    the words. This pushes a marker through the functions that actually take
    the user's text and asserts it never reaches the log.
    """

    MARKER = "zzmarkerzz-two-rotis-and-dal-at-nine-pm"

    def test_the_users_own_words_never_reach_the_log(self) -> None:
        key = ASHA
        gates._forget_user(key)
        self.addCleanup(gates._forget_user, key)

        with self.assertLogs("ted.safety_gates", level="DEBUG") as captured:
            gates.LOGGER.info("ted_probe_marker_anchor user_key=%s", key)
            gates._note_language(key, self.MARKER)
            gates._capture_name_answer(key, self.MARKER)
            gates.unreadable_document_gate(self.MARKER)
            gates._remember_age(key, 34)
            gates._remember_measurement(key, "weight_kg", 58.0)

        blob = "\n".join(captured.output)
        self.assertNotIn(self.MARKER, blob)
        self.assertIn("ted_probe_marker_anchor", blob)  # the capture really ran

    def test_a_blocked_vision_path_is_logged_without_the_users_text(self) -> None:
        """The one log line added today. It carries a path, never a message."""
        session = "sess-log-test"
        with gates._TURN_LOCK:
            gates._TURN_CONTEXT[session] = {"chat_id": "918888888888@lid"}
        self.addCleanup(lambda: gates._TURN_CONTEXT.pop(session, None))

        with self.assertLogs("ted.safety_gates", level="INFO") as captured:
            gates._vision_scope_guard(
                tool_name="vision_analyze", session_id=session,
                args={"image_url": "/etc/passwd", "question": self.MARKER})

        blob = "\n".join(captured.output)
        self.assertIn("ted_vision_path_blocked", blob)
        self.assertNotIn(self.MARKER, blob)


class DegradedSafetyStateTest(unittest.TestCase):
    """Roadmap T03: the safety asset is unreadable, so Ted must not answer.

    The file holds the 18+ blocks and nothing else does. It used to return {}
    for every failure, so a corrupt file emptied every block while the plugin
    still imported and the guard still reported "Gates are on".

    The two normal empty states must never trip this, because the blast radius
    of a false positive is every user at once.
    """

    def setUp(self) -> None:
        self.original = gates._STATE_DEGRADED
        self.addCleanup(setattr, gates, "_STATE_DEGRADED", self.original)

    def load(self, tmp_path: Path, body: str | None):
        path = Path(tmp_path) / "ted-safety-gates-onboarding.json"
        if body is not None:
            path.write_text(body, encoding="utf-8")
        with unittest.mock.patch.object(gates, "_ONBOARDING_STATE_PATH", path):
            state = gates._load_onboarding_state()
        return state, gates._STATE_DEGRADED

    # --- the normal states, which must NOT be called degraded -------------

    def test_no_file_at_all_is_a_first_run_not_a_fault(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(Path(tmp), None)
        self.assertEqual(state, {})
        self.assertEqual(degraded, "")

    def test_a_valid_file_with_no_users_is_not_a_fault(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(Path(tmp), '{"users": {}}')
        self.assertEqual(state, {})
        self.assertEqual(degraded, "")

    def test_a_good_file_loads_and_is_not_degraded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(
                Path(tmp), '{"users": {"' + ASHA + '": {"age": 15}}}')
        self.assertEqual(state[ASHA]["age"], 15)
        self.assertEqual(degraded, "")

    # --- the faults, which must be caught ---------------------------------

    def test_unparseable_json_is_degraded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(Path(tmp), '{"users": {not json')
        self.assertEqual(state, {})
        self.assertIn("unparseable", degraded)

    def test_a_truncated_file_is_degraded(self) -> None:
        """What a torn write actually looks like."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(
                Path(tmp), '{"users": {"' + ASHA + '": {"age": 1')
        self.assertEqual(state, {})
        self.assertIn("unparseable", degraded)

    def test_the_wrong_shape_is_degraded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for body in ('{"people": {}}', '[]', '"a string"', 'null'):
                with self.subTest(body=body):
                    state, degraded = self.load(Path(tmp), body)
                    self.assertEqual(state, {})
                    self.assertTrue(degraded, f"{body!r} should be degraded")

    def test_an_empty_file_is_degraded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state, degraded = self.load(Path(tmp), "")
        self.assertIn("unparseable", degraded)

    # --- and what the user is told ----------------------------------------

    def test_a_degraded_gate_refuses_to_answer(self) -> None:
        gates._STATE_DEGRADED = "unparseable: test"
        reply = gates.transform_response(
            history=[], user_message="i had 2 rotis and dal",
            response_text="that's about 400 calories, logged!", user_key=ASHA)
        self.assertEqual(reply, gates.STATE_UNAVAILABLE)

    def test_the_refusal_does_not_leak_the_model_s_answer(self) -> None:
        """The whole point: an unguarded reply must not reach the user."""
        gates._STATE_DEGRADED = "unparseable: test"
        reply = gates.transform_response(
            history=[], user_message="how many calories should i eat",
            response_text="eat 1200 calories a day to lose weight fast",
            user_key=ASHA)
        self.assertNotIn("1200", reply)
        self.assertNotIn("calories a day", reply)

    def test_a_healthy_gate_is_completely_unaffected(self) -> None:
        gates._STATE_DEGRADED = ""
        reply = gates.transform_response(
            history=[], user_message="hello", response_text="hey!", user_key=ASHA)
        self.assertNotEqual(reply, gates.STATE_UNAVAILABLE)

    def test_the_refusal_is_logged_without_the_users_words(self) -> None:
        gates._STATE_DEGRADED = "unparseable: test"
        with self.assertLogs("ted.safety_gates", level="ERROR") as captured:
            gates.transform_response(
                history=[], user_message="zzsecretzz i had rotis",
                response_text="ok", user_key=ASHA)
        blob = "\n".join(captured.output)
        self.assertIn("ted_reply_refused_state_degraded", blob)
        self.assertNotIn("zzsecretzz", blob)


class PrivilegePostureTest(unittest.TestCase):
    """Roadmap T01, first bullet, as far as it can be tested on this machine.

    T01 asks for a dedicated low-privilege account or a container. TED runs as
    the machine's owner instead, so that bullet is genuinely open and belongs
    with T04, where the move to always-on hosting provides the boundary once
    rather than twice.

    What can be pinned now is the posture that makes the gap survivable: the
    process is not root, and the data directory is not readable by any other
    account on the box. Both were true on 17 Sep 2026 and neither is obvious
    enough to stay true by accident.
    """

    def test_the_gateway_does_not_run_as_root(self) -> None:
        import subprocess
        found = subprocess.run(
            ["pgrep", "-f", "hermes_cli.main gateway"],
            capture_output=True, text=True)
        pids = [p for p in found.stdout.split() if p.isdigit()]
        if not pids:
            self.skipTest("no gateway running on this machine")
        owner = subprocess.run(
            ["ps", "-o", "uid=", "-p", pids[0]], capture_output=True, text=True)
        uid = (owner.stdout or "").strip()
        self.assertTrue(uid.isdigit(), f"could not read the owner: {owner.stdout!r}")
        self.assertNotEqual(int(uid), 0, "the gateway is running as root")

    def test_the_hermes_directory_is_private_to_its_owner(self) -> None:
        home = Path.home() / ".hermes"
        if not home.is_dir():
            self.skipTest("no ~/.hermes on this machine")
        mode = home.stat().st_mode & 0o777
        self.assertEqual(
            mode & 0o077, 0,
            f"~/.hermes is {oct(mode)}; another account on this machine can reach it")

    def test_the_secrets_file_is_private(self) -> None:
        env = Path.home() / ".hermes" / ".env"
        if not env.is_file():
            self.skipTest("no ~/.hermes/.env on this machine")
        mode = env.stat().st_mode & 0o777
        self.assertEqual(mode & 0o077, 0, f"~/.hermes/.env is {oct(mode)}")
