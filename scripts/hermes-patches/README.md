# Hermes patches

Six fixes now live *below* Ted's plugin, in the Hermes gateway
itself (`~/.hermes/hermes-agent`). A plugin cannot reach them: the strings are
emitted by Hermes' own retry machinery, and `VALID_HOOKS` has no hook for
outbound gateway status messages.

They are applied to the working Hermes checkout. **A Hermes upgrade can drop
them.** `hermes update` stashes local changes, pulls, and re-applies the stash;
when that re-apply conflicts it runs `git reset --hard` and leaves the work in a
stash only (`hermes_cli/main.py`, `_stash_local_changes_if_needed`). Nothing is
destroyed, but the gateway silently goes back to leaking model names into
WhatsApp and charging laptop sleep to the provider — which is why this is
checked rather than remembered.

`npm run gates:guard` reports whether all six patches are still applied, alongside
its existing gate checks. It treats a missing patch as a warning, not a stop:
an unpatched Ted is noisy, but he still refuses under-18s, still never returns a
deficit, and still keeps users' memories apart.

    npm run hermes:patch:check    # are they applied?
    npm run hermes:patch          # re-apply whatever is missing
    hermes gateway restart && npm run gates:guard

Re-applying is safe to run twice — already-present hunks are skipped, and the
verdict comes from re-checking the files, not from `patch`'s exit code. If a
patch can no longer apply because the upstream file moved, the script says so
and stops; redo the change by hand and re-export with `git diff`.

## 01 — sleep-aware stall detection

Every provider-stall watchdog measured silence with `time.time()`, which keeps
running while the host is suspended. A closed laptop lid was therefore charged
to the provider: on 2 Sep the log records `Stream stale for 1019s (threshold
180s)` five times in one call, across a `Clamshell Sleep` window that `pmset -g
log` confirms. The one detection that happened while the machine was awake
fired at 192s — correct.

The patch adds a monotonic companion timer (`time.monotonic()` pauses with the
machine on macOS and Linux) for the streaming, non-streaming, Codex and Bedrock
watchdogs. Wall-clock timestamps are left alone where `stream_diag` compares
them against `started_at` to compute TTFB.

Paired with `HERMES_STREAM_STALE_GIVEUP=2` in
`~/Library/LaunchAgents/ai.hermes.gateway.plist`, so a genuinely wedged call
reaches the configured `fallback_model` in minutes instead of never.

Note: `providers.<id>.stale_timeout_seconds` cannot fix this. The reasoning
floor in `agent/reasoning_timeouts.py` raises any configured value back up to
180s for `claude-sonnet-5`, so a lower setting is silently ignored.

## 02 — plain-language provider errors

Hermes' user-facing provider-failure strings are now read from
`display.provider_messages.*` in `config.yaml`, defaulting to the previous
wording so upstream tests still pass. Mid-call stall notices — which name the
model, the provider and the context size, and repeat once per reconnect — are
matched and suppressed on chat surfaces (raw text still goes to
`~/.hermes/logs/agent.log`, and CLI/API/webhook surfaces are untouched).

Ted's wording lives in `~/.hermes/config.yaml` under `display.provider_messages`,
which is why the copy is config rather than code: SOUL.md forbids exposing model
and provider names, and SCOPING.md #27 wants a plain "that didn't go through".

## 03 — the voice-note "Listening…" acknowledgement

Not part of an order. It was already sitting uncommitted in the Hermes checkout
when order 09 started, and `SOUL.md` documents the behaviour it provides — "the
gateway sends one short `Listening…` acknowledgement while it transcribes" —
so it is real, wanted, and was surviving only in a working tree that
`hermes update` would have stashed away.

Exported here so it is saved and re-appliable like the other two, and added to
the guard so its disappearance is noticed rather than discovered later by a
voice note going quiet.

## 04 — the photo "taking a look" acknowledgement

The landing page shows Ted answering a meal photo in two beats: "ooh a pic 👀
taking a look, one sec…" and then the numbers. Only the second beat existed. A
photo is the slowest thing a user can send, because the routing decision does
blocking network I/O and then a vision model runs, and until it finished the
thread just sat there. On WhatsApp that reads as broken.

Patch 03 already does this for voice notes, and PRODUCT_BUILD_GUARDRAILS asks
for it directly: "acknowledge slow media quickly, then process asynchronously
where appropriate". This is the same shape for images.

The part worth keeping is the throttle. WhatsApp delivers a burst of photos as
separate messages, each its own gateway event, so a per-event acknowledgement
would send five of them for one plate — exactly the noise the guardrail "one
user action should feel like one interaction" exists to prevent. The
acknowledgement is therefore throttled per session over a 90-second window, and
skipped entirely when `display.media_ack.image` is set to an empty string.

Copy lives in `~/.hermes/config.yaml` under `display.media_ack`, for the same
reason `display.provider_messages` does: it is Ted's voice, and Ted's voice
should not require patching Hermes to change.

## 05 — busy acknowledgements in Ted's voice

Sending two messages in a row is how people talk, and Hermes answered it with
"⚡ Interrupting current task (…). I'll respond to your message shortly." A
tester on 3 Sep read that as the product breaking. The three busy replies are
now one line each in Ted's voice, with the status detail, `/stop` and the
subagent-versus-compression distinction dropped — none of which is the user's
to care about.

## 06 — no gateway notices to users

"⚠️ Gateway shutting down — Your current task will be interrupted." reached one
person eight times in ninety minutes on 3 Sep, one per deploy. A restart here
is a deploy, and the people on the other end are using a health app. Nothing
they sent was lost, so it announced an outage that never touched them. The
notice stays in the log.

## Where the checks live

`patches.json`, in this directory, holds the load-bearing strings for every
patch. Both `scripts/hermes-patch-guard.py` and the gateway plugin read it —
two definitions would eventually disagree about whether Ted is patched, and the
quiet one would be the one that mattered.

The plugin re-runs the check at **every gateway boot** and logs
`ted_hermes_patches_ok`, or `ted_hermes_patches_missing` naming what went and
how to put it back. `gates:guard` always caught a dropped patch; it always
relied on someone remembering to run it after an upgrade, which is the kind of
thing that gets remembered until the once it matters.
