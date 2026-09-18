# T08 — one person's messages, in the order they sent them

**Status: the mechanism was already there; the evidence was not. It is now.**

T08's definition of done:

> A burst of ordered messages for one user produces deterministic state, while
> concurrent users are processed independently.

---

## 1. Nothing needed writing

The roadmap asks for "a per-user queue/lock/sequence key". Four already exist,
and three of them are upstream:

| layer | where | what it serializes |
| --- | --- | --- |
| adapter busy guard | `_active_sessions` | per routing key |
| runner guard | `_running_agents` | per routing key |
| turn lease | `gateway/turn_lease.py` | per **resolved session id**, covering the load-history → run → flush region |
| follow-up mode | `~/.hermes/config.yaml` | `busy_input_mode: queue` |

The fourth is ours and it is a decision rather than code. `queue` was chosen
after 3 Sep, when a tester sent five messages in eighty seconds and `interrupt`
aborted the turn already in flight. The config comment records the reasoning:
*"`queue` leaves the running turn alone and cascades the follow-up after it, so
a reply written before an answer arrived can never be delivered after it."*

Follow-ups cascade through a FIFO that gives each message its own turn in
arrival order. Rapid fragments inside 0.35s merge into one turn instead, which
is also right: somebody typing in bursts is making one point.

`turn_lease.py` is worth reading once. It exists because two routing keys can
map to one session id, so no per-key guard ever sees the collision, and the two
turns then interleave their flushes on one transcript — **rows persisting in
completion order instead of arrival order.** That sentence is what this task's
check looks for.

## 2. The evidence, 30 days to 19 Sep 2026

`npm run ordering`:

```
30 days, 58 people, 1457 messages from them.
  119 arrived while Ted was mid-turn — the case T08 is about.
  2 were one message split into two rows, not two messages.
  ok  every message was answered in the order it arrived.
```

**119 real overlaps and zero ordering faults.** The concurrency T08 worries
about is not hypothetical here — it happens four times a day — and the queue
holds every time.

### Two things that looked like faults and are not

Both were found by making the mistake first, against the live database.

**104 "violations" in 14 days that were the feature working.** An assistant row
followed by a user row with an *earlier* timestamp is a person typing while Ted
composes. The row is persisted after the reply and carries its real arrival
time. Reading row order as arrival order turns every successful queue into a
bug report.

**13 "unanswered" messages that were 5.** Grouping by `session_id` splits one
conversation across sessions, so a reply in the next session looks like
silence. The unit T08 is about is the person, so the check groups by `chat_id`.

## 3. What the check does look for

`scripts/ted-ordering-check.py`, read-only, no writes anywhere.

- **arrival order** — per person, a user message processed before one that
  arrived earlier. Rows less than a second apart are exempt: a document's
  injected text and its caption arrive together (Ankiita's PDF, 11ms) and are
  one message, not two.
- **nothing dropped** — a user message with no reply after it, anywhere for
  that person, cross-checked against `delivery_obligations` so a reply Ted
  wrote and could not deliver is named as a failed delivery rather than as
  silence.
- **overlaps seen** — printed always. A run that found no fault and a run that
  found no traffic must not look alike, which is the lesson from the reminder
  count that read a sixth of the traffic and reported it as clean.

## 4. The four who got nothing, and why

The check fails today on four messages. They are not ordering faults, and the
cause is worth keeping written down.

| when | who | what they sent |
| --- | --- | --- |
| 4 Sep 01:51 | Vinit | "Build muscle And lose bmi" |
| 4 Sep 16:43 | Palak | "Okay Ted, let's do this 💪" |
| 4 Sep 16:44 | Palak | "Done" |
| 4 Sep 17:24 | Vishwas Mishra | "Okay Ted, let's do this" |

**Palak and Vishwas never received a single reply in their entire history.**
They arrived, said hello, were met with silence, and never wrote again. Vinit
had a real conversation and then answered Ted's question at 01:51 — a proper
answer, "build muscle and lose bmi" — and that was the end of it.

The gateway received all of it. Palak's message is in the log at 16:43:25,
sixteen seconds after the bridge reconnected, and a turn started. Then:

```
agent.credential_pool: marking OPENROUTER_API_KEY exhausted (status=402), rotating
agent.credential_pool: no available entries (all exhausted or empty)
agent.conversation_loop: Non-retryable client error: Error code: 402
```

Both the primary model and the fallback returned **402, out of credit**. Ted
composed nothing and, at that time, said nothing either.

**That half is fixed.** Hermes patch 2 plus `display.provider_messages` in
config.yaml means a provider failure now produces a reply in Ted's voice — *"it's
not you, it's me 🙈 rough patch on my end. don't break up with me yet, give it
another go in a minute?"* — which is exactly the text sitting in the one
abandoned obligation from 11 Sep. Neither existed on 4 Sep.

**What was not fixed is that nobody knew.** Two people were lost on a Thursday
afternoon and it took a check written for a different task, fifteen days later,
to find them. `ted-watch.py` watched the abandoned state in the ledger; nothing
watched for a turn that ended without composing anything at all.

*Closed 19 Sep 2026.* `check_silent` in `ted-watch.py` is that watcher, running
every fifteen minutes and alerting off WhatsApp. It calls `unanswered` in this
file rather than restating it, so there is one definition of an unanswered
message, and it reports only the messages with no delivery obligation after
them — a written reply that could not be sent stays `check_dropped`'s, so one
person cannot raise two alarms saying different things.

These four age out of the window on 4 October, at which point this check goes
green on its own. That is the wrong reason for a check to go green, so it is
written here rather than suppressed.

## 5. Still open

- **The bursts the roadmap names are not in the data.** It asks for multi-photo
  bursts, "actually…" corrections and "done/later" responses to be tested. 119
  overlaps were found, but no multi-photo burst and no correction among them.
  Those need staging on the test number rather than waiting for a user.
- **Cross-user independence is measured by T02, not here.** `npm run
  concurrency` checks 32 overlap episodes for routing and leakage. What neither
  checks is whether one person's slow turn *delays* another's, as opposed to
  crossing it. No delay has been observed; nothing proves it cannot happen.

## Re-verify

```bash
npm run ordering            # 30 days
npm run ordering -- --days 7
npm run concurrency         # T02, the cross-user half
```
