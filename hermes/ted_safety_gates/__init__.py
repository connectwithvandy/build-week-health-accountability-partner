"""Hard safety and consent gates for Ted's live Hermes WhatsApp coach."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LOGGER = logging.getLogger("ted.safety_gates")
PRIVACY_URL = "https://heyted.vercel.app/privacy"
DISCLOSURE_MESSAGE = (
    "Ted stores your profile, messages, plans, logs and uploads. Not a doctor. "
    f"Details: {PRIVACY_URL} — send “delete my data” anytime!"
)
GOAL_QUESTION = "what’s one thing you want to change?"

_TURN_CONTEXT: dict[str, dict[str, Any]] = {}
_TURN_LOCK = threading.Lock()
_DISCLOSURE_STATE_PATH = (
    Path.home() / ".hermes" / "state" / "ted-safety-gates-disclosures.json"
)
_AGENT_LOG_PATH = Path.home() / ".hermes" / "logs" / "agent.log"
_DISCLOSURE_LOG_PATTERN = re.compile(r"consent_disclosure_sent session=([^\s]+)")


def _load_disclosure_state(
    state_path: Path = _DISCLOSURE_STATE_PATH,
    agent_log_path: Path = _AGENT_LOG_PATH,
) -> set[str]:
    """Load durable disclosure state and recover older sends from the log."""
    keys: set[str] = set()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        keys.update(str(value) for value in payload.get("user_keys", []))
        # Keep older per-session records long enough to migrate active users.
        keys.update(str(value) for value in payload.get("session_ids", []))
    except (OSError, TypeError, ValueError, AttributeError):
        pass
    try:
        keys.update(
            _DISCLOSURE_LOG_PATTERN.findall(
                agent_log_path.read_text(encoding="utf-8", errors="replace")
            )
        )
    except OSError:
        pass
    return {key for key in keys if key}


_DISCLOSURE_SENT_KEYS = _load_disclosure_state()


def _persist_disclosure_state() -> None:
    _DISCLOSURE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _DISCLOSURE_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"user_keys": sorted(_DISCLOSURE_SENT_KEYS)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(_DISCLOSURE_STATE_PATH)


def _user_state_key(platform: str, sender_id: str, session_id: str) -> str:
    """Return a stable, non-readable key for one messaging user."""
    if sender_id:
        identity = f"{platform}:{sender_id}".encode("utf-8")
        return f"{platform}:sha256:{hashlib.sha256(identity).hexdigest()}"
    return session_id


def _mark_disclosure_sent(user_key: str, session_id: str = "") -> bool:
    if not user_key:
        return False
    with _TURN_LOCK:
        if user_key in _DISCLOSURE_SENT_KEYS:
            return False
        _DISCLOSURE_SENT_KEYS.add(user_key)
        context = _TURN_CONTEXT.get(session_id)
        if context is not None:
            context["disclosure_sent"] = True
        _persist_disclosure_state()
    return True


def _send_goal_question(chat_id: str) -> bool:
    """Send the second onboarding bubble through Hermes' live adapter."""
    try:
        from tools.send_message_tool import send_message_tool

        raw_result = send_message_tool(
            {
                "action": "send",
                "target": f"whatsapp:{chat_id}",
                "message": GOAL_QUESTION,
            }
        )
        payload = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        return isinstance(payload, dict) and payload.get("success") is True
    except Exception:
        LOGGER.exception("consent_goal_question_send_failed")
        return False


def _schedule_goal_question(chat_id: str, user_key: str) -> None:
    """Send the goal as its own bubble after the transformed reply lands."""
    if not chat_id or not user_key:
        LOGGER.error("consent_goal_question_missing_chat user_key=%s", user_key)
        return

    def _deliver() -> None:
        # post_llm_call runs just before Hermes delivers the transformed reply.
        # This small delay preserves disclosure-first ordering on WhatsApp.
        time.sleep(1.0)
        if _send_goal_question(chat_id):
            LOGGER.info("consent_goal_question_sent user_key=%s", user_key)
        else:
            LOGGER.error("consent_goal_question_delivery_failed user_key=%s", user_key)

    threading.Thread(
        target=_deliver,
        name="ted-consent-goal-question",
        daemon=True,
    ).start()


@dataclass(frozen=True)
class CalorieProfile:
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    sex: str | None = None
    activity: str | None = None


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    return ""


def _messages(history: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    return [
        (str(message.get("role", "")), _message_text(message))
        for message in history
        if isinstance(message, dict)
    ]


def _disclosure_was_sent(history: Iterable[dict[str, Any]]) -> bool:
    return any(
        role == "assistant" and PRIVACY_URL in text
        for role, text in _messages(history)
    )


def _given_name(history: Iterable[dict[str, Any]]) -> str | None:
    waiting_for_name = False
    for role, text in _messages(history):
        lowered = text.lower()
        if role == "assistant" and any(
            phrase in lowered
            for phrase in (
                "what should i call you",
                "what can i call you",
                "what is your name",
                "what's your name",
                "your name?",
            )
        ):
            waiting_for_name = True
            continue
        if waiting_for_name and role == "user" and text:
            name = re.sub(
                r"^(?:i(?:'m| am)|my name is|call me)\s+",
                "",
                text.strip(),
                flags=re.IGNORECASE,
            )
            name = re.sub(r"\s+", " ", name).strip(" .,!?")
            if name:
                return name[:40]
    return None


def _name_was_given(history: Iterable[dict[str, Any]]) -> bool:
    return _given_name(history) is not None


def _personalized_disclosure(history: Iterable[dict[str, Any]]) -> str:
    name = _given_name(history)
    prefix = f"{name}, quick note: " if name else "quick note: "
    return prefix + DISCLOSURE_MESSAGE


def _asks_for_name(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "what should i call you",
            "what can i call you",
            "what is your name",
            "what's your name",
            "your name?",
        )
    )


def consent_gate(
    history: Iterable[dict[str, Any]], response_text: str
) -> str | None:
    """Return the mandatory disclosure when onboarding has reached the name."""
    if _disclosure_was_sent(history):
        return None
    if _name_was_given(history):
        return _personalized_disclosure(history)
    if not _asks_for_name(response_text) or _response_has_calorie_number(response_text):
        return "What should I call you?"
    return None


def _user_turns(history: Iterable[dict[str, Any]]) -> list[str]:
    return [text for role, text in _messages(history) if role == "user" and text]


def _find_age(texts: list[str]) -> int | None:
    joined = "\n".join(texts)
    labelled = re.search(
        r"(?:\bage\b|\bi\s*(?:am|'m)\b)\D{0,12}(\d{1,2})\b",
        joined,
        re.IGNORECASE,
    )
    if labelled:
        return int(labelled.group(1))
    return None


def _find_height_cm(texts: list[str]) -> float | None:
    joined = "\n".join(texts)
    cm = re.search(r"\b(1\d{2}(?:\.\d+)?)\s*cm\b", joined, re.IGNORECASE)
    if cm:
        return float(cm.group(1))
    feet = re.search(
        r"\b([4-7])\s*(?:ft|feet|foot|')\s*(?:(\d{1,2})\s*(?:in|inches|\"))?",
        joined,
        re.IGNORECASE,
    )
    if feet:
        inches = int(feet.group(1)) * 12 + int(feet.group(2) or 0)
        return round(inches * 2.54, 2)
    return None


def _find_weight_kg(texts: list[str]) -> float | None:
    joined = "\n".join(texts)
    match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*kg\b", joined, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _find_sex(texts: list[str]) -> str | None:
    joined = "\n".join(texts).lower()
    if re.search(r"\b(female|woman)\b", joined):
        return "female"
    if re.search(r"\b(male|man)\b", joined):
        return "male"
    return None


def _find_activity(texts: list[str]) -> str | None:
    joined = "\n".join(texts).lower()
    for activity in ("very active", "moderate", "light", "sedentary", "active"):
        if re.search(rf"\b{re.escape(activity)}\b", joined):
            return activity
    return None


def _age_from_answer_context(history: Iterable[dict[str, Any]]) -> int | None:
    turns = _messages(history)
    for index, (role, text) in enumerate(turns[:-1]):
        if role != "assistant" or "age" not in text.lower():
            continue
        next_role, answer = turns[index + 1]
        if next_role != "user":
            continue
        candidates = [int(value) for value in re.findall(r"\b(\d{1,2})\b", answer)]
        candidates = [value for value in candidates if 10 <= value <= 99]
        if candidates:
            return candidates[0]
    return None


def extract_calorie_profile(history: Iterable[dict[str, Any]]) -> CalorieProfile:
    texts = _user_turns(history)
    return CalorieProfile(
        age=_find_age(texts) or _age_from_answer_context(history),
        height_cm=_find_height_cm(texts),
        weight_kg=_find_weight_kg(texts),
        sex=_find_sex(texts),
        activity=_find_activity(texts),
    )


def _calorie_flow_active(history: Iterable[dict[str, Any]], user_message: str) -> bool:
    recent = _user_turns(history)[-6:] + [user_message]
    joined = " ".join(recent).lower()
    return any(
        term in joined
        for term in ("calorie", "kcal", "maintenance", "deficit", "track calories")
    )


def _response_has_calorie_number(response_text: str) -> bool:
    return bool(
        re.search(
            r"(?:\b\d[\d,.]*\s*(?:kcal|calories?)\b|"
            r"\b(?:maintenance|deficit|target)\D{0,30}\d[\d,.]*)",
            response_text,
            re.IGNORECASE,
        )
    )


def _maintenance_or_target_flow(user_message: str, response_text: str) -> bool:
    joined = f"{user_message}\n{response_text}".lower()
    return any(term in joined for term in ("maintenance", "deficit", "calorie target"))


def _missing_profile_reply(profile: CalorieProfile) -> str | None:
    missing = (
        (profile.height_cm, "I need your height before I can estimate maintenance calories."),
        (profile.weight_kg, "I need your weight before I can estimate maintenance calories."),
        (profile.sex, "I need the sex you want used in the formula before I can estimate maintenance calories."),
        (profile.activity, "I need your activity level before I can estimate maintenance calories."),
    )
    for value, reply in missing:
        if value is None:
            return reply
    return None


def _estimated_maintenance(profile: CalorieProfile) -> int:
    assert profile.age is not None
    assert profile.height_cm is not None
    assert profile.weight_kg is not None
    assert profile.sex is not None
    assert profile.activity is not None
    sex_adjustment = 5 if profile.sex == "male" else -161
    resting = (
        10 * profile.weight_kg
        + 6.25 * profile.height_cm
        - 5 * profile.age
        + sex_adjustment
    )
    factors = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very active": 1.9,
    }
    return int(round(resting * factors[profile.activity] / 10) * 10)


def calorie_gate(
    history: Iterable[dict[str, Any]], user_message: str, response_text: str
) -> str | None:
    """Block or replace calorie output using only user-supplied values."""
    active = _calorie_flow_active(history, user_message)
    if not active and not _response_has_calorie_number(response_text):
        return None

    profile = extract_calorie_profile(history)
    if profile.age is None:
        return "I need your age before I can give calorie numbers."
    if profile.age < 18:
        return "I can’t provide calorie numbers because this beta is only for adults."

    if not _maintenance_or_target_flow(user_message, response_text):
        return None

    missing_reply = _missing_profile_reply(profile)
    if missing_reply:
        return missing_reply

    estimate = _estimated_maintenance(profile)
    return (
        f"Your estimated maintenance is roughly {estimate:,} calories a day, "
        "based only on the values you gave me."
    )


_MEMORY_CLAIM = re.compile(
    r"\b(saved|logged|updated|noted|recorded)\b|"
    r"\bI(?:'ll| will)\s+(?:save|log|note|record|update)\b",
    re.IGNORECASE,
)
_CRON_CLAIM = re.compile(
    r"\b(?:reminder|alarm|schedule)\b.{0,24}\b(?:set|scheduled|updated)\b|"
    r"\bI(?:'ll| will)\s+(?:schedule|set|remind|send)\b",
    re.IGNORECASE,
)
_DELETE_CLAIM = re.compile(
    r"\bI(?:'ve| have)\s+deleted\b|\b(?:data|entry|reminder|job)\b.{0,20}\bdeleted\b",
    re.IGNORECASE,
)


def _claim_types(text: str) -> set[str]:
    claims: set[str] = set()
    if _MEMORY_CLAIM.search(text):
        claims.add("memory")
    if _CRON_CLAIM.search(text):
        claims.add("cron")
    if _DELETE_CLAIM.search(text):
        claims.add("delete")
    return claims


def action_claim_gate(
    response_text: str,
    action_succeeded: bool = False,
    successful_actions: set[str] | None = None,
) -> str | None:
    """Remove action claims unless a tool succeeded in the same turn."""
    claims = _claim_types(response_text)
    if not claims:
        return None
    allowed = set(successful_actions or ())
    if action_succeeded:
        allowed.update(claims)
    if claims.issubset(allowed):
        return None
    kept_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", response_text.strip())
        if sentence.strip() and _claim_types(sentence).issubset(allowed)
    ]
    if kept_sentences:
        cleaned = re.sub(r"^(?:But|And)\s+", "", " ".join(kept_sentences))
        return cleaned[:1].upper() + cleaned[1:]
    return "I haven’t completed that action."


def transform_response(
    *,
    history: Iterable[dict[str, Any]],
    user_message: str,
    response_text: str,
    action_succeeded: bool = False,
    successful_actions: set[str] | None = None,
) -> str | None:
    disclosure = consent_gate(history, response_text)
    if disclosure:
        return disclosure
    if not _disclosure_was_sent(history):
        return None
    calorie = calorie_gate(history, user_message, response_text)
    if calorie:
        return calorie
    return action_claim_gate(
        response_text,
        action_succeeded=action_succeeded,
        successful_actions=successful_actions,
    )


def _capture_turn(**kwargs: Any) -> None:
    if kwargs.get("platform") != "whatsapp":
        return None
    platform = str(kwargs.get("platform") or "")
    session_id = str(kwargs.get("session_id") or "")
    if not session_id:
        return None
    sender_id = str(kwargs.get("sender_id") or "")
    user_key = _user_state_key(platform, sender_id, session_id)
    history = list(kwargs.get("conversation_history") or [])
    disclosure_sent = (
        user_key in _DISCLOSURE_SENT_KEYS
        or session_id in _DISCLOSURE_SENT_KEYS
        or _disclosure_was_sent(history)
    )

    # Migrate a prior session/log record to the stable user key on first sight.
    if disclosure_sent and user_key not in _DISCLOSURE_SENT_KEYS:
        _mark_disclosure_sent(user_key)

    with _TURN_LOCK:
        _TURN_CONTEXT[session_id] = {
            "history": history,
            "user_message": str(kwargs.get("user_message") or ""),
            "successful_actions": set(),
            "disclosure_sent": disclosure_sent,
            "user_key": user_key,
            # Hermes passes the WhatsApp sender JID as sender_id. It is also
            # the direct-chat delivery target for the follow-up bubble.
            "chat_id": sender_id,
        }
    return None


def _transform_live_response(**kwargs: Any) -> str | None:
    if kwargs.get("platform") != "whatsapp":
        return None
    session_id = str(kwargs.get("session_id") or "")
    with _TURN_LOCK:
        context = _TURN_CONTEXT.get(session_id, {})
    history = list(context.get("history", []))
    if context.get("disclosure_sent") and not _disclosure_was_sent(history):
        history.insert(0, {"role": "assistant", "content": DISCLOSURE_MESSAGE})
    return transform_response(
        history=history,
        user_message=str(context.get("user_message", "")),
        response_text=str(kwargs.get("response_text") or ""),
        successful_actions=set(context.get("successful_actions", set())),
    )


def _record_tool_success(**kwargs: Any) -> None:
    if kwargs.get("status") != "ok":
        return None
    tool_name = str(kwargs.get("tool_name") or "")
    args = kwargs.get("args") or {}
    result = kwargs.get("result")
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return None

    proven: set[str] = set()
    if tool_name == "memory" and not payload.get("staged"):
        proven.add("memory")
        if isinstance(args, dict) and args.get("action") == "remove":
            proven.add("delete")
    elif tool_name == "cronjob":
        action = args.get("action") if isinstance(args, dict) else None
        if action in {"create", "update", "pause", "resume"}:
            proven.add("cron")
        elif action == "remove":
            proven.update({"cron", "delete"})
    if not proven:
        return None

    session_id = str(kwargs.get("session_id") or "")
    with _TURN_LOCK:
        context = _TURN_CONTEXT.get(session_id)
        if context is not None:
            context["successful_actions"].update(proven)
    return None


def _log_disclosure(**kwargs: Any) -> None:
    if kwargs.get("platform") != "whatsapp":
        return None
    if PRIVACY_URL in str(kwargs.get("assistant_response") or ""):
        session_id = str(kwargs.get("session_id") or "")
        with _TURN_LOCK:
            context = dict(_TURN_CONTEXT.get(session_id, {}))
        user_key = str(context.get("user_key") or session_id)
        first_send = _mark_disclosure_sent(user_key, session_id)
        if first_send:
            _schedule_goal_question(
                str(context.get("chat_id") or ""),
                user_key,
            )
        LOGGER.info(
            "consent_disclosure_sent session=%s user_key=%s privacy_url=%s",
            session_id,
            user_key,
            PRIVACY_URL,
        )
    return None


def register(ctx: Any) -> None:
    ctx.register_hook("pre_llm_call", _capture_turn)
    ctx.register_hook("post_tool_call", _record_tool_success)
    ctx.register_hook("transform_llm_output", _transform_live_response)
    ctx.register_hook("post_llm_call", _log_disclosure)
