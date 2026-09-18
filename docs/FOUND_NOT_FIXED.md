# Found, not fixed

Things noticed while working on something else. Written down so they are not
rediscovered, and deliberately **not** acted on at the time. Each one says what
was seen, how it was seen, and why it was left.

Nothing here is a roadmap task. Nothing here is urgent enough to interrupt the
task in hand, and nothing here should be trusted without re-checking: these are
observations from a moment, and the system moves.

---

## 18 Sep 2026

**~~Ted has sent no proactive message in seven days.~~ WRONG, and withdrawn the
same evening.** Ted delivers 7 to 21 reminders a day, every day. The claim came
from reading `delivery_obligations`, and **a scheduled reminder never touches
that ledger**: the cron scheduler hands it straight to the adapter and writes
one line to `agent.log`:

    Job '6e77ad1b48ab': delivered to whatsapp:115650651500637@lid via live adapter

Left here rather than deleted, because the mistake is the useful part. The
memory rule "read `delivery_obligations`, not `messages`" is true for replies
and silently incomplete for reminders, and it was followed confidently into a
wrong conclusion that was then repeated in three documents.

**What is actually true:** 60 cron jobs, 20 enabled. The 40 disabled ones are
correct — 12 users sit in `awaitingBreakReply` after ignoring four nudges and
the "want me to pause?" offer, so the gate refuses their sends anyway. Of the 8
users with enabled jobs, 5 carry a `paused_until`, leaving three receiving
reminders: Vandy, Ankiita and Protein Smoothie.

**DEFERRED BY DECISION, 18 Sep 2026.** Vandy: "the user analysis, we will do
later." Two questions are parked, on purpose, and neither is a bug to be fixed
without her:

1. Whether 36 of 56 users having no reminder job is the onboarding leak or a
   choice.
2. Whether a user who ignores the break offer should stay silent **forever**.
   Today there is no path back except them writing first. That is defensible
   and it is also how a product goes quiet one person at a time.

Do not act on either without asking. Both change what real people receive.

**Seven users are paused, one until 18 October.** `Hari` is paused until
2026-10-18, `Shreya` until 2026-09-23, four until 2026-09-20. Worth knowing
whether each of those was asked for.

**A user is stored with the name `"ted i'm genuinely confused"`.** Somebody's
frustrated sentence was captured as their name, and Ted has been addressing
them by it ever since. Paused until 2026-09-14, so currently silent either way.
Related to the name-cleanup work, not to the pause.

**Two `arpit` records on different numbers**, `arpit` and `Arpith`, both stuck
at the age question. Could be two people, could be one person on two handsets.
Deletion, drift repairs and the concurrency check all treat them as two.

**`ted-api-spend.py` leaves `:free` models unpriced.** Five rows of
`stepfun/step-3.7-flash:free`. The `:free` suffix almost certainly means free,
but the model is no longer listed on OpenRouter and this file's rule is to say
what it cannot prove. Costs nothing to leave.

**The delivery ledger only reaches back to 11 Sep 2026.** 182 rows. Anything
asking "what did users actually receive" before that date has no answer, which
limits every measurement of the kind above to a seven-day window.

---

## 19 Sep 2026

**Two people were lost on 4 September and nothing noticed for fifteen days.**
Palak and Vishwas Mishra each sent "Okay Ted, let's do this" and received no
reply, ever — not a late one, not a wrong one, silence — and neither wrote
again. Vinit answered Ted's question at 01:51 the same day and got the same
nothing. The cause is known and half of it is fixed: OpenRouter returned 402,
out of credit, on both the primary model and the fallback, and at that time a
provider failure produced no user-facing message. Hermes patch 2 and
`display.provider_messages` fixed that half in the days after.

**The unfixed half is the detection.** `ted-watch.py` watches the delivery
ledger's `abandoned` state, which catches a reply that was written and could
not be sent. Nothing watches for a turn that ended having composed nothing at
all, which is what a 402 produces. Found by `npm run ordering`, written for
T08, fifteen days late. Full evidence in `docs/T08_ORDERING.md` §4.

**Not acted on** because it needs a decision about what watches what, and
because the three affected people are fifteen days gone — a message to them now
is a product decision, not a repair, and nobody is messaged without Vandy
saying so.
