# T14 — memory layers, what is stored on 19 September 2026

**Status: sorted and diagnosed, not yet layered. The design is proposed at the
end and needs a decision before anything is built.**

T14's definition of done:

> A representative task receives only the memory it needs, and
> corrections/temporary instructions behave predictably across sessions.

Its first instruction is the one this document answers:

> Separate profile memory, today-state, recent conversational context and
> learned behavioural memory.

`npm run memory:audit` is that sorting.

---

## 1. The instinct that was wrong

The obvious worry, coming off T13, is that memory is bloating the prompt.
`getUserMemory` hands over every fact on every turn and the formatter caps at
fifty, so fifty facts a turn looked like the risk.

It is not. **92 facts across 29 users — a mean of 3.2 each, a maximum of 14.**
Eight users have exactly one. Three facts a turn is perhaps 60 tokens against a
21,400-token floor.

Shrinking the memory block is not the T14 that matters. What memory lacks is
not brevity. It is shape.

---

## 2. What is stored, sorted

| layer | facts | share | what it is |
|---|---:|---:|---|
| profile | 45 | 49% | name, age, sex, height, weight, goal |
| behavioural | 23 | 25% | activity level, work schedule, wake time, habits |
| health | 11 | 12% | supplements, symptoms, conditions |
| instruction | 7 | 8% | **how Ted should talk** |
| preference | 6 | 7% | diet, drink, which nudges, when to check in |

T14 names four layers. A fifth had to be added on contact with the table, and
it is the one that should not exist.

### The first cut of this table was wrong, and the mistake is the point

Four facts were filed as `instruction` on the strength of their key names —
`nudge_preferences`, `daily_preference`, `logging_preference`,
`coaching_preference` — and reading the values proved it wrong. They say
"meals, water, supplements, moving", "wants end of day check for missed items",
"needs patience for first 2-3 days while building habit". Those are the
person's own choices, and deleting them as duplicated voice rules would have
thrown away the only record of what they asked for.

**A layer decided from a key the model invented is a layer decided from a
guess.** That is the argument for fixing the key vocabulary before building
retrieval rules on top of a layer, and it is why the ranking in section 6 puts
the vocabulary first.

### `instruction` — SOUL.md, written back into the user's memory

Seven facts are not about the person at all. They are rules about how Ted
speaks, stored per user, injected on every turn, on top of a SOUL.md that
already says all of it at 14,670 tokens:

```
voice_style_preference   233 chars
chat_style_preference    171 chars
tone_preference          117 chars  (x4 users)
meal_reply_rule           83 chars
```

All seven say the same thing in different words: short, lowercase, one
thought, light hinglish, no dashes, no receipt-style replies. SOUL.md's
"How I talk" (1,651 tokens) and "How I actually sound" (1,740 tokens) already
say exactly that, to every user, on every turn.

One of them reads "short 1-2 line whatsapp tone, lowercase, friend-first
bangalore vibe, light hinglish (arre/yaar), no dashes, no headings or receipts,
never type calories/macros in message" — which is a paraphrase of four SOUL.md
sections.

This is the duplication T13 went looking for and did not find inside SOUL.md.
It is not inside SOUL.md. It is between SOUL.md and the memory block, and it
arrives one user at a time because the model writes it there.

Worse than the tokens: **these are the only rules in the system a user's own
conversation can rewrite.** SOUL.md is version-controlled and reviewed. A
`tone_preference` is whatever the model decided to save that turn.

### today-state and recent conversational context are missing

Not from this document — from the table. Today-state lives in `dailyEntries`,
conversational context lives in the session and is reset after 60 idle minutes.
Neither is in `userFacts`, and nothing coordinates the three. That is the
finding, not an omission.

---

## 3. Two homes for one fact

**43 of 92 facts (47%) mirror a typed column in the `users` table.** Name, sex,
height, weight, goal all exist twice: once as a validated column, once as
free text the model wrote.

Compared by value: **35 agree, 0 disagree.** They have not drifted today.

That is not the same as safe, and the repo already knows why — Order 24 was
"the day two stores disagreed in three different ways", and nine repair scripts
exist because of it. The condition that produced them is still here:

- `users.weightKg` is a validated number. `userFacts.weight_kg` is free text.
- Only the second one reaches the prompt.
- Both are writable, by different paths, with nothing reconciling them.

### The eight that cannot be compared at all

`goal` exists in both stores in two different vocabularies. `users.goal` is an
enum — `loseWeight`, `maintainWeight`. The fact beside it says "lose weight",
"losing weight", "holding steady", "holding_steady", and in one case "meal
tracking" next to a `loseWeight` enum.

An earlier version of the audit reported all eight as drift. Seven were the
same goal in two vocabularies, and calling those a conflict is a false alarm
that costs trust in the whole report. They are counted as incomparable now.

But the underlying problem is worse than a reporting nuisance: **nothing in the
system can tell a correction from a rephrasing.** That is precisely the
capability T14's supersession rule has to have.

---

## 4. Supersession is an exact string match

`userFacts` is indexed `by_user_and_key`, so saving a fact replaces the
existing one **only when the key matches character for character.** The key is
free text the model invents each turn.

One user in production holds both:

```
supplement_vitamin_b12       1000mcg
suppplement_vitamin_b12      (three p's)
```

Two rows, one supplement, both injected into every prompt. Nothing detected it
and nothing will, because exact-match supersession cannot see a typo.

The same shape is waiting in `gender` vs `sex` (six users use one, five the
other), `goal` vs `goal_raw`, and `supplements` vs the five individual
`supplement_*` keys. They do not collide today only because no single user has
happened to use both spellings.

---

## 5. Reuse: measured, but not ripe

`userFacts.useCount` and `lastUsedAt` have been written by the gate since
commit d554a88 (16 Sep). One fact of 92 has ever changed a reply.

**That is not a finding yet.** The commit that shipped the counter says so in
as many words: a zero means "not measured yet" rather than "memory is never
used" until the gateway has served with it for a week. That week is up on
**23 September**. The audit prints the date beside the number so nobody reads
1% as a verdict.

Whatever it says on the 23rd, read it knowing the detector is deliberately
strict — it excludes product vocabulary and times of day, so it undercounts.

---

## 6. Proposed, needing a decision

Ranked by what they fix, not by effort:

| # | change | fixes |
|---|---|---|
| 1 | **built** — stop the model writing `instruction` facts | SOUL.md being rewritable by a conversation |
| 2 | **built** — a key vocabulary, aliases and typo collapsing | typo supersession, gender/sex, goal/goal_raw |
| 3 | one home per profile fact — `users` owns it, the block reads it | 47% duplication, the Order 24 condition |
| 4 | a `layer` column, and retrieval by task | T14's actual DoD |
| 5 | `expires_at` for temporary facts | "temporary instructions behave predictably" |

1 and 2 are small and independent. 3 is a migration and touches the nine repair
scripts. 4 and 5 are the real T14 and should follow 2, because a retrieval rule
keyed on a vocabulary the model invents per turn cannot be relied on.

### 1 and 2, built 19 Sep — what they do

Both live in the gate, `hermes/ted_safety_gates/__init__.py`, so no Hermes
patch is involved. **They need a gateway restart to take effect.**

`apply_key_vocabulary` runs on every `ted_memory_save`, before anything is
written:

- **Aliases** land one concept on one key — `goal_raw` becomes `goal`.
- **Typo collapsing** compares an unfamiliar key against the keys this user
  already holds, and if they are identical once repeated characters are
  collapsed, theirs wins. `suppplement_vitamin_b12` supersedes
  `supplement_vitamin_b12` instead of sitting beside it. This catches the
  class — `activityy_level`, `supplementt_coq10`, `wake__time` — not the one
  typo that was found.
- **Voice rules are refused**: any key containing tone, voice, style,
  phrasing, wording or formatting, plus `meal_reply_rule` by name. Logged as
  `ted_fact_refused_voice_rule`, never returned as an error — an internal
  refusal in front of somebody's reply is what patches 6, 7, 8 and 11 exist to
  stop.

**An unrecognised key is still saved.** A gate that drops what it does not
recognise is the onboarding bug again, where Ted's real answers were discarded
for arriving in a shape the gate did not expect. Unknown keys are saved and
logged, so the vocabulary grows from evidence.

The six words are the list rather than "anything ending in `_preference`" for
the reason section 2 gives: `nudge_preferences`, `daily_preference`,
`logging_preference` and `coaching_preference` all sound like instructions and
are the person's own choices. None of them contains any of the six.

**Costs 210 tokens a turn.** The tool description now names the preferred keys
and the refusal, so the model is steered rather than only corrected. That is
+1% on a 21,554-token floor, and it invalidates the WhatsApp prompt cache once
on deploy.

**Still not done, and deliberately:** the 7 existing voice-rule rows are
untouched. Deleting live user data is irreversible and is Vandy's call, not a
side effect of shipping a gate change.

*19 Sep 2026: the tool exists, the deletion has not happened.*
`scripts/ted-purge-voice-rules.py` (`npm run memory:voice-rules`) lists them
and deletes them only with `--apply`. It selects with the gate's own
`is_voice_rule_key`, so the list it would delete and the list the gate refuses
can never disagree, and it prints the rules themselves by default because
reading the values is what caught the four misfiled keys in section 2. The
write goes through a new `forget-facts` action on `/ted-memory` that takes
named keys only and is capped at ten: `delete` is the privacy teardown and
this is a cleanup, and they must not be one call with a flag. Convex has to be
deployed before it can run. Whether it runs at all is still Vandy's call.

---

## 7. How to re-run it

```sh
npm run memory:audit
python3 scripts/ted-memory-audit.py --show-keys   # unrecognised key names
python3 scripts/ted-memory-audit.py --json
```

No fact values are printed, and none are written to disk. Keys are the
schema's words; values are the user's, and some of them are the reason
`ted-log-retention.py` had to exist.
