# Found, not fixed

Things noticed while working on something else. Written down so they are not
rediscovered, and deliberately **not** acted on at the time. Each one says what
was seen, how it was seen, and why it was left.

Nothing here is a roadmap task. Nothing here is urgent enough to interrupt the
task in hand, and nothing here should be trusted without re-checking: these are
observations from a moment, and the system moves.

---

## 18 Sep 2026

**Ted has sent no proactive message in seven days.** All 178 delivered messages
between 11 and 18 Sep arrived within five minutes of the user writing. Zero
reminders reached anybody. Measured from `delivery_obligations` against the
last inbound message per chat.

The causes stack: 60 cron jobs exist and **only 20 are enabled**, so 36 of 56
users have no reminder at all; 7 users carry a `paused_until`; the rest are
skipped with `reason=dailyCap` or the agent returning `[SILENT]`.

*Why it is here and not fixed:* some of those pauses are people asking Ted to
back off, which is working as intended. Telling that apart from 36 users who
were never given a reminder is a product decision, not a bug fix. It also
interacts with T12/T32.

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
