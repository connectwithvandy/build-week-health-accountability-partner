# T16 — the eval suite

**Status: the case set is built, versioned and checked in. A scored
comparison needs a paid run, which has not happened.**

T16's definition of done:

> A versioned eval suite produces comparable pass/fail/quality results for
> old vs proposed behavior.

---

## 1. What already existed

Most of T16 was here, in two pieces nobody had joined up.

- `ted-model-bakeoff.py` replays real turns through several models, prices
  the run before it spends, and scores the replies against SOUL.md's
  countable rules via `ted-voice-check.py`. What it replayed was **only cron
  turns** — `s.id LIKE 'cron_%'`. The 209 chat sessions carrying a stored
  system prompt had never been used, and that is where meals, Hinglish,
  corrections, pauses and frustration live.
- **48 docstrings** in `hermes/test_ted_safety_gates.py` cite a dated
  production incident. That is T16's "include past production incidents as
  tests rather than prompt stories", already done, for free, on every run of
  the suite.

So this task was not a new harness. It was the case set the runner was
missing.

## 2. The case set

`evals/ted-cases-v1.json`, 50 cases. Build or refresh it with:

```bash
npm run eval:build       # rebuild, 6 per category
npm run eval:cases       # coverage, and whether every case still resolves
npm run eval:run         # replay them; prices itself first, ~$3.16 for 5 models
```

| category | cases |
| --- | --- |
| meal_text | 6 |
| meal_photo | 6 |
| hinglish | 6 |
| correction | 6 |
| pause_reschedule | 6 |
| goal_change | 6 |
| safety_boundary | 6 |
| ambiguous | 6 |
| frustration | 4 |

### Why the file holds hashes and not text

This is a public repository and every case is somebody's health message.
"Anonymised" cannot mean "with the name removed" — the sentence identifies.
A case is a truncated sha256 of the message plus its categories. The text
stays in `state.db` on the machine, the same rule as the media in
`ted-forget-user.py` and the chat id in `docs/T09_DELETION_AUDIT.md`.

The session id is not stored either. It is per-person, and pinning a case to
a person is the thing a deletion undoes.

### Why nine categories and not ten

**Voice cannot be built from this data.** A voice note reaches `messages`
already transcribed, as ordinary text with no marker — four turns in the
whole store mention audio at all, and none of them is a marker. A "voice"
case would be a typed case with a label on it. The gap is recorded in the
artefact itself, under `unavailable`, not only here.

### A case can stop resolving, and that is reported

If a person is forgotten their messages go, and their cases stop resolving.
Both `npm run eval:cases` and a `--suite` run name the count and say the run
is not comparable with an earlier one. A silent skip would change what "the
same cases" means between two runs being compared, which is the one thing
this artefact exists to hold still.

## 3. What is not done

- **No scored run has happened.** Replaying 50 cases across 5 models costs
  about $3.16 and spends real money, so the dry run is as far as this goes
  without a decision. Until then there is a versioned case set and a runner,
  not a baseline to compare against.
- **Scoring is voice rules, emptiness, character breaks and transcription.**
  T16 asks for correctness, state change, memory use, tone, brevity,
  actionability, safety, latency and cost. Latency and cost the runner has;
  tone and brevity the voice rules approximate; correctness, state change and
  memory use are not scored at all and would need a judge or a fixture with
  known-good answers.
- **The classifiers are coarse** and select candidates rather than judge
  meaning. The file is meant to be read and curated by a person, which is
  why it is versioned and checked in rather than rebuilt on every run.

## Re-verify

```bash
npm run eval:cases
.venv/bin/python -m pytest scripts/test_ted_eval_cases.py -q
```
