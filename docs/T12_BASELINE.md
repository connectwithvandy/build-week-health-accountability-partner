# T12 — the baseline, 12 to 18 September 2026

**Status: measurable, measured, and written down. This is the "before" the
roadmap asks for.**

T12's definition of done:

> At least one week/day baseline can answer why a request was slow/expensive/
> failed **without reading the user's chat content**.

Nothing new is recorded to achieve this. Hermes has written all of it down
since the first day — `session_model_usage` has a row per session and model,
`messages` has a timestamp on every turn, `delivery_obligations` has a row per
outbound message since patch 16 covered reminders too. The gap was never the
instrumentation. It was that no one read it back in one place, so "is Ted
slow?" and "why did yesterday cost that?" were answered by opening a provider
console by hand.

`npm run baseline` is that read-back.

---

## 1. The week

```
day         ppl  repl  med s  p90 s  calls  in/call out/call    cost  $/ppl  fallbk    err  deliv
2026-09-12    5    41   10.7   14.3    142    20864      198   $1.48   0.30    100%    97%   100%
2026-09-13    4     4    9.6      -     74    35390       69   $5.21   1.30     27%    28%   100%
2026-09-14    2    36    9.2   11.5    137    31461      121   $5.29   2.64     34%    25%    97%
2026-09-15    3    22   10.7   24.3    125    26756      173   $3.63   1.21     67%    48%    95%
2026-09-16    6    33    9.4   12.1    150    35906       77   $9.45   1.57      5%     5%   100%
2026-09-17    5    39    9.4   11.6    135    33101       85   $5.12   1.02      3%     1%    97%
2026-09-18    4    14   10.9   13.5     49    17079      173   $0.90   0.22     78%    41%   100%

189 replies, $31.08 over 7 days.
```

## 2. What it already answers

**Ted is not slow, and he is not fast.** The median reply is 9 to 11 seconds,
every single day, and the spread barely moves. That stability is the most
useful number here: it means a day that reads 20s later is a real regression
and not noise. p90 is 11 to 14s except 15 Sep, where it is 24s.

**Two replies in the week took over a minute**: 99.4s on 18 Sep and 65.7s on
13 Sep. Both are named by session, and neither needed a transcript to find.

**The fallback road carries far more traffic than anyone would guess.** On
12 September **every single call** went to `openai/gpt-5.3-codex` — 100%,
against an error rate of 97% on the primary. 15 Sep was 67%, 18 Sep 78%. On
16 and 17 September it was 3 to 5%.

This is invisible from a chat. A user gets an answer either way. But it changes
the bill, and it changes the voice, because the fallback is a different model
writing as Ted.

`check_model` in `ted-watch.py` does watch this, and watches the right half of
it: it counts **dead ends** — the credit and auth failures that mean the
primary cannot answer — rather than the fallback rate, because a timeout the
fallback absorbs is the fallback doing its job. It was added on 15 Sep, after
1,070 failed calls over ten days had gone unseen, so the 12 Sep column here
predates it. Tonight it reads "primary model answering (recovered 22:31; 38
failed calls earlier in the window)".

What is not watched is the **share**. A day that is 78% fallback with no dead
ends looks healthy to every check there is, and still costs and sounds
different.

**Cost per person swings 12x**, $0.22 to $2.64, with no relationship to how
many people wrote. 16 Sep cost $9.45 for 6 people and 33 replies; 12 Sep cost
$1.48 for 5 people and 41 replies. The driver is not conversation volume — it
is cron. `npm run spend` splits the bill by what asked for it, and measured
that 71% of cron firings delivered nothing to anybody.

**Delivery is 95 to 100%.** The gaps are the abandoned rows already understood:
a disconnect, not a queue fault.

## 3. What it cannot answer, stated rather than implied

- ~~**The error rate has no durable source.**~~ **Closed 19 Sep 2026.** A
  failed API call is retried and the retry succeeds, so nothing in the
  database records that it happened, and the only evidence is a line in
  `agent.log`. That was "the log might have rotated" until `ai.ted.logs`
  began pruning at 30 days the same day, which made it a scheduled deletion.
  `ted-log-retention.py` now rolls the per-day totals into
  `~/.hermes/state/ted-error-ledger.json` **before** it prunes — the thing
  that destroys the evidence keeps the summary, so the two cannot drift and
  there is no fourth timer to install. A date and a count, never the line: a
  failure line can carry a prompt fragment. The count never revises
  downward, because re-reading a rotated log finds fewer. First run kept 17
  days, back to 30 Aug. The report still says so when neither source reaches
  the start of the window.
- **The first day of any window has no error rate**, and prints `-`. The
  cutoff is a timestamp and lands mid-morning, so `calls` holds part of that
  day while a failure count is per calendar day. The skew is not new; it hid
  inside a plausible number until the ledger pushed 12 Sep to "179%", which
  is the same error saying so out loud.
- **Latency is wall-clock from the person's message to Ted's reply.** It
  includes queueing, tool calls, vision, and retries. It is what the person
  experienced, which is the right thing to baseline, but it is not a model
  latency and should not be read as one.
- **Tokens are per call, not per message.** A scheduled reminder is a call with
  no reply. Dividing tokens by replies is what produced "654,716 tokens per
  message" in the first draft of this file, which was a mix-up rather than a
  finding.
- **Cost is Hermes' estimate**, with the cache-write repricing that
  `ted-api-spend.py` documents. It is not an invoice.

## 4. Why this is the "before"

The roadmap asks for a baseline **captured before changing model or context
architecture**. Two such changes are already queued and both would move these
numbers:

- **T06**, the official WhatsApp path, changes the delivery column's meaning
  entirely: `delivered` becomes a real receipt from Meta rather than the
  adapter accepting a message.
- Any change to SOUL.md's size moves `in/call` directly. It is ~11k tokens on
  every one of roughly 438 calls a day, which is most of what the input column
  measures.

Re-run `npm run baseline --days 7` after either, and compare against the table
in section 1 rather than against a memory of how it felt.

## Re-verify

```bash
npm run baseline              # 7 days
npm run baseline -- --days 14
npm run baseline -- --json    # for piping
npm run spend                 # the cost half, split by what asked for it
```
