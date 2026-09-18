# T10 — a reminder that leaves a record

**Status: the gap is measured and the patch is written. Not applied — that is a
live change to the send path for 56 people.**

T10's definition of done:

> Every scheduled reminder or review has a final known status or a visible
> unresolved state; delivery failure cannot silently disappear.

---

## 1. The gap, exactly

Ted sends two kinds of message and only one of them is recorded.

| | replies | scheduled reminders |
| --- | --- | --- |
| goes through | the gateway's delivery ledger | straight to the adapter |
| leaves behind | a row per message, six states | one line in `agent.log` |
| survives | 7 days of retention, in `state.db` | until the log rotates |
| count, 1–18 Sep 2026 | **184 rows** | **230 sends, no rows** |

230 reminders were delivered and the only proof of any of them is a log file
that rotates on its own schedule. `agent.log.1` holds the weeks before; when it
goes, so does the evidence.

**This is not a theoretical loss.** A check that read the ledger alone reported
that Ted had sent no proactive message in seven days. It said so four times, in
three documents, while he was delivering 7 to 21 reminders a day. The class of
mistake T10 prevents is not "a message went missing" — it is "nobody could tell
either way".

## 2. What the patch does

`scripts/hermes-patches/16-cron-sends-join-the-delivery-ledger.patch`, 105
lines against `cron/scheduler.py`.

The ledger API already exists and is well made (`gateway/delivery_ledger.py`).
The patch does not invent a second one; it calls the same three functions the
gateway calls around a reply:

```
record_obligation()   before any send attempt   -> pending
mark_attempting()     immediately before it     -> attempting
mark_delivered()      at each success site      -> delivered
```

Three insertion points and a pair of helpers. Deliberately **no failure
marking**: a send that never reaches a success site stays `pending`, and
pending *is* the "visible unresolved state" T10 asks for. Marking failures at
each of the six error paths would be six more hunks for the same outcome and
six more chances to break a reminder.

**`session_key` is `cron:<platform>:<chat>`**, so a reminder is distinguishable
from a reply in the same table — which matters for anything that reads it, and
is why this is a prefix rather than a flag.

**The obligation id carries a run stamp**, `<job id>@<unix seconds>`. The job id
alone would collide across firings and the ledger would treat tonight's
reminder as a re-record of last night's. With the stamp, each firing is its own
row while retries inside one firing stay idempotent, which is what the ledger's
id is for.

**Every call swallows every exception.** That is the ledger's own contract —
*"ledger failures must never block or delay an actual send"* — and it matters
more here than for a reply: a reminder somebody set up must never fail to
arrive because bookkeeping did.

## 3. Two things this gets for free

**Stale reminders cannot be resurrected.** Putting reminders in the ledger
makes them eligible for the crash-recovery sweep, which sounds alarming until
you read Ted patch 12: `STALE_AFTER_SECONDS` is ten minutes, and anything older
is moved to `failed` and never sent. Ten minutes covers a gateway restart or a
bridge reconnect, which is exactly when a reminder is still worth delivering.
Checked before writing this, not assumed.

**Operations already watches it.** `check_dropped` in `ted-watch.py` alarms on
`abandoned`/`failed` rows with no later delivery to that chat. A failed reminder
becomes such a row, so "expose overdue or stuck messages to operations" needs no
new code.

There is a tidy consequence. `_reached_by_cron_since` exists only because cron
sends wrote no row — it reads `agent.log` so that somebody answered by a
reminder stops being reported as unanswered. After this patch the ledger says
the same thing, from the same moment. The helper becomes a second source for
one fact rather than the only source for it. It is left in place: retiring a
live alarm's input is its own change, not a footnote to this one.

## 4. What T10 still does not have

**"Delivered" here means the adapter accepted it.** That is the exact thing
T10's subtitle warns about — *"a 'sent' call is not proof that a WhatsApp
message was delivered."* Baileys has no delivery receipt to reconcile, so
`delivered` is the truest state available on this path and it is not the one
T10 wants.

The states T10 names — delivered, **read if available**, and "reconcile
asynchronous delivery callbacks" — need the Cloud API's message status webhook,
which is T06. So T10 is honestly split: the durable record and the unresolved
state land now; the real delivery receipt arrives with the migration. Recorded
here rather than claimed.

## 5. How to apply it

Not applied. Applying it edits the live gateway and needs a restart, which is an
outage for 56 people.

```bash
npm run hermes:patch:check     # shows 16 as missing, as it should today
npm run hermes:patch           # applies it
hermes gateway restart && npm run gates:guard
```

Verified before being written down: `patch -p1 --dry-run` applies cleanly
against the live `cron/scheduler.py`, the modified file parses, and the guard
reports the patch as missing rather than silently passing.

Afterwards, the first firing should produce a row:

```bash
sqlite3 ~/.hermes/state.db \
  "SELECT session_key, state, created_at FROM delivery_obligations
   WHERE session_key LIKE 'cron:%' ORDER BY created_at DESC LIMIT 5;"
```

If that returns nothing after a reminder has gone out, the patch is applied and
not working, which is worth more than a green check.
