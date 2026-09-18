# T13 — the prompt payload, measured 19 September 2026

**Status: measured, and the measurement changed the answer. The largest saving
turned out not to be an edit at all — it is Hermes patch 17, applied to the
checkout and waiting on a gateway restart. The editorial shrink is deliberately
not applied; section 3 says why.**

T13's definition of done:

> Median input tokens fall materially while the TED eval set shows no
> unacceptable quality regression.

Its first instruction is the one this document answers:

> Measure current system prompt, tools, memory and history tokens
> **separately**.

`python3 scripts/ted-prompt-audit.py --days 30` is that measurement.

---

## 0. The estimate was wrong first, by a quarter

The first version of the audit divided characters by four — Hermes' own
pre-flight estimate, `agent/model_metadata.py:2669`. It reported SOUL.md at
**10,696 tokens**. Counted for real against `claude-sonnet-5`, SOUL.md is
**14,670**.

Four characters per token is an English-prose number. Ted is written in
Hinglish with emoji and tokenizes at **2.92 characters per token**. Every
conclusion drawn from the estimate was a quarter too small, in the direction
that makes the prompt look cheaper than it is.

The audit now counts through `messages.count_tokens`, which is free and
unbilled, caches each result by content hash, and says in its own output
whether a given run counted or estimated. When it cannot count, it falls back
to 2.92 — the measured ratio for Ted's text — and never to 4.

A second error in the same direction: summing per-tool counts reported 8,711
tokens for a payload the API counts as **5,525**. The API adds a fixed
overhead the moment any tool is present, and summing added it once per tool.

A third, found by running the audit through `npm`: under the repo's own
`python3` the tool modules fail to import for want of PyYAML, the toolsets
resolved to nothing, and the audit printed **"0 tools"** — silently taking
5,525 tokens off the floor. It now reports an unmeasured payload as unknown,
names the interpreter, and leaves the floor blank rather than smaller. A floor
missing its tools is not a smaller floor.

None of the three was visible without checking the audit against the bill.

---

## 1. What every call carries

| block | tokens | where it comes from |
|---|---:|---|
| system prompt | **15,835** | `sessions.system_prompt`, counted |
| — of which SOUL.md | 14,670 | 93% of the system prompt |
| — Hermes boilerplate | ~1,165 | finishing the job, parallel tool calls, steering, host facts |
| tool schemas (WhatsApp) | **5,525** | 10 tools, `get_tool_definitions()` |
| tool schemas (cron) | 5,249 | 9 tools, no `vision_analyze` |
| **floor, per call** | **~21,400** | paid on every turn of every session |
| history | 293–898 | per session, and it is the small number |

The floor is 53% of a WhatsApp call and 57% of a cron call. History — the
thing "shrink the prompt" usually means — is under 5%.

SOUL.md by section, counted:

```
   3,323 tok   22.7%  Example dialogues
   1,984 tok   13.6%  Logging a meal
   1,740 tok   11.9%  How I actually sound
   1,651 tok   11.3%  How I talk
   1,358 tok    9.3%  What I remember about them
     754 tok    5.1%  Language
     547 tok    3.7%  When something is unsafe or unclear
     ... 12 more sections, none above 550
  14,627 tok          TOTAL
```

Ten tools cost 5,525 tokens. The three largest are `ted_save_onboarding`
(1,701), `ted_log_entry` (1,377) and `ted_set_reminder` (1,264) — all three
carry long prose descriptions that exist to stop specific past failures.

---

## 2. The finding: the same text costs different money

| source | sessions | calls | floor | billed/call | cached | reads per write |
|---|---:|---:|---:|---:|---:|---:|
| whatsapp | 197 | 2,395 | 21,554 | 40,389 | **88%** | **10.2** |
| cron | 633 | 793 | 21,077 | 36,672 | **27%** | **0.40** |

A WhatsApp turn reads 88% of its prompt from cache, at a tenth of list price.
A cron firing reads 27%, and pays the 1-hour cache-write premium — 2x list —
on the rest.

**A cached prefix has to be read about 1.1 times to beat not caching at all.**
Cron reads it 0.40 times. Cron's caching is a net loss, and has been all along.

Priced from the same rows `ted-api-spend.py` uses, and agreeing with it to
within fifty cents:

```
cron, as it runs today (1h TTL, 2.0x writes)      $83.92 / 30 days
if cron did not cache at all                      $58.16 – $38.78
saving                                            $26 – $45   (Rs 2,300 – 4,000)
```

**95% of cron's bill is cache writes, and most of them expire unread.**
Nothing Ted says changes. This is not an editing question.

### The saving is a range, and the reason is worth knowing

The two ends are two ways of reading the same rows, and the gap between them
is an unexplained 1.5x:

- **$26** takes the billed token columns at face value. 793 calls billed
  29.08M prompt tokens, so 29.08M is what plain input would cost.
- **$45** takes the *counted* prompt at face value. The prompt is 24,449
  tokens per call in that window (19,200 system + 5,249 tools), so 793 calls
  should be 19.4M tokens, not 29.08M.

**Billed prompt tokens per call are 36,672 against a counted 24,449 — 1.50x.**
On single-call cron sessions the two agree almost exactly (a 21,084-token
prompt against 22,116 cache-write tokens, 1.05x), so the gap is not in the
counting. It appears on multi-call sessions, where the `system_and_3` layout
puts four cache breakpoints in each request and the prefix is re-written.

Whether Anthropic is billing creation on overlapping breakpoints, or Hermes
is retrying without incrementing `api_call_count`, is not settled here. Both
would show exactly this. **Use $26 as the number to plan against** — it is
the one that holds whichever explanation is true.

### Why it happens, and why it is not a bug

`config.yaml` sets `cache_ttl: 1h` deliberately, and the reason written beside
it is correct:

> Ted's traffic is bursty — a dozen daily reviews fire in one second at 21:00,
> then nothing for half an hour — so a five-minute cache was written, expired
> unread, and written again.

That is true of the bunched firings, and those are the 27% that do hit. It is
not true of the spread-out ones, and there are more of them. The TTL is a
single global setting serving two workloads with opposite shapes: chat, where
a session makes twelve calls in minutes and caching wins ten to one, and cron,
where a firing makes one or two calls and then the session ends forever.

---

## 3. What is not worth doing yet, and why

T13 also asks to remove duplicated instructions and obsolete incident stories
from the personality prompt. Measured:

- **There is no literal duplication.** 451 sentences in SOUL.md, zero exact
  repeats. It is a rulebook — 73 sentences containing "never", 31 containing
  "do not" — but each rule is stated once.
- **The incident stories are load-bearing on purpose.** "On 3 Sep a user told
  me a scoop of whey was not 120 kcal and I simply agreed, because I had
  nothing but a recollection to stand on." Those lines are the evidence that
  makes each rule stick, and they were added one real failure at a time.

Cutting them would be a voice change dressed as a cost change, and T13's own
definition of done requires "no unacceptable quality regression" measured
against **the TED eval set — which is T16, and does not exist yet**.

So the editorial shrink waits for T16. Saying that is not deferring the task:
the measurement is done, and the largest saving available today needs no
editing at all.

---

## 4. Ranked, with what each one costs to be wrong

| # | lever | saving | risk if wrong |
|---|---|---:|---|
| 1 | **taken — Hermes patch 17** | $26–45/mo | none to the user; `cache_control` is metadata |
| 2 | a short cron identity instead of full SOUL | ~10k tok/firing | cron messages drift out of Ted's voice |
| 3 | trim example dialogues (3,323 tok) | ~15% of the floor | the voice they hold is the product |
| 4 | shorten the three largest tool descriptions | ~1,500 tok | re-opens the failures they were written to stop |

Levers 2–4 all change what the model reads and all need an eval set.

---

## 5. Lever 1, taken: Hermes patch 17

It was **not a config flip**. `anthropic_prompt_cache_policy` in
`agent/agent_runtime_helpers.py` decides caching from the provider and model
alone — there is no per-source knob, and `cache_ttl` is global, serving chat
and cron at once though their shapes are opposite.

`scripts/hermes-patches/17-no-dead-cache-breakpoints-on-cron.patch` adds
`system_only=` to `apply_anthropic_cache_control` and passes it when
`agent.platform == "cron"` — the value `cron/scheduler.py` already sets where
it builds the agent.

**The system breakpoint stays.** That is the difference between this and
turning caching off for cron outright: cron system prompts are byte-identical
between firings, so the bunched jobs still read one another's prefix and the
27% that does hit is kept. What goes is the three message-level breakpoints,
which a session that ends can never read.

Verified against the patched code on the machine:

```
chat  (all breakpoints): 4
cron  (system only):     1
text the model reads, all three identical: yes
```

That last line is the whole safety argument. `cache_control` is metadata, so
this is the one lever T13 found that cannot change what Ted says, and the only
one that does not need T16.

**Applied, registered in `patches.json` so a Hermes upgrade cannot drop it
quietly, and live since the gateway restarted at 23:38 on 18 Sep.**

### The first firing under it, and what it settled

`cron_6e77ad1b48ab`, 00:00:38 on 19 Sep, two calls:

```
                 write per call    against a counted prompt of 21,084
  before              36,637       1.74x
  after               21,037       1.00x
```

**The cache write is now the prompt, once.** 21,037 against an independently
counted 21,084 is a 0.2% difference, which is not a coincidence — it is the
same number arrived at two different ways.

That settles the 1.5x this document could not explain. The two candidates were
overlapping cache breakpoints and a retry that never incremented
`api_call_count`. Removing three breakpoints removed the excess, so it was the
breakpoints. A retry would have been untouched by this patch.

At that rate the saving is **$50 a month, not the $26 planned against** — the
conservative end was conservative because it assumed the billed tokens were
real prompt. They were not; a third of them were the same prefix billed again.

**Three caveats, because this is one session.** It fired at midnight with
nothing near it, so its `cache_read` of 0 is what an isolated firing looks like
with or without the patch — this does not yet show whether the patch cost any
of the reads the bunched 21:00 jobs were getting. The $50 applies one session's
write rate to a 30-day call count, which is a projection. And the number to
trust is `npm run prompt:audit --days 7` after a few days of mixed traffic,
where `r/w` has had bunched firings to work with.

---

## 6. How to re-run it

```sh
python3 scripts/ted-prompt-audit.py --days 30     # the whole audit
python3 scripts/ted-prompt-audit.py --soul-only   # section table, no database
python3 scripts/ted-prompt-audit.py --no-api      # never call out
python3 scripts/ted-prompt-audit.py --json
```

No message content is read or printed. The system prompt and the tool schemas
are Ted's own text and are counted in full; nothing a user typed ever is.

The "before" for T13's definition of done is the floor in section 1:
**21,400 tokens per call, of which 15,835 is the system prompt and 5,525 is
tools.** Any claimed shrink is measured against that number, by this script.
