# T07 — one inbound event, one outcome

**Status: the half that can exist today exists. The rest is webhook-shaped and
waits on T06 being executed, not decided.**

T07's definition of done:

> Replaying the same inbound event multiple times produces one user-visible
> outcome and one state mutation; slow model work never blocks webhook
> acknowledgement.

Two halves, and they had very different answers on 18 Sep 2026.

---

## One state mutation — already true, and tested

`convex/model.ts` builds a dedupe key for every logged entry:

```
msg:<externalMessageId>        when the platform gave us a message id
auto:<date:type:items:…:at>    when it did not
```

`convex/ted.ts` looks that key up on the `by_user_and_dedupe_key` index before
inserting, and returns `{duplicate: true}` with the existing entry rather than
writing a second one. Convex mutations are transactional, so the read and the
insert cannot interleave.

The reasoning in the file is the part worth keeping: *"Two genuinely separate
glasses of water an hour apart are NOT duplicates, so without a message id the
key stays unique and the write goes through."* Nine assertions in
`__tests__/convex-model.test.ts` cover it, including the water case and item
normalisation.

**Nothing to do here.** It was done before T07 was looked at, which the roadmap
column does not say.

## One user-visible outcome — was not true, now is

Convex refused to log the meal twice. Nothing refused to *answer* twice. A
redelivered message would have been read, answered and charged for, and the
person would have watched Ted say the same thing twice for no reason.

This could not be fixed in the plugin. The gate has no way to stay quiet on the
WhatsApp path: `[SILENT]` is understood on the cron path only, and returning it
from a chat turn delivers those eight characters to a real person. So it is
**Hermes patch 15**, at the top of `_handle_message_with_agent`, before the
model is called: a bounded map of `(platform, chat_id, message_id)` already
answered, oldest evicted first.

**No duplicate has ever been observed on Baileys.** The three pairs of
identical messages in the delivery ledger were all the onboarding gate
repeating a question, fixed separately the same evening. So today this is
insurance.

**On the official Cloud API it stops being optional.** Meta retries a webhook
whenever it does not receive a 2xx quickly enough, and a slow model turn is
exactly that. This patch is a prerequisite for T06's migration, not an extra.

**Known limit, on purpose:** the map is in memory, so a restart forgets. The
alternative is a durable write on the hot path of every inbound message to
defend against a redelivery spanning a restart, and Convex still holds the line
on state either way.

---

## What is left, and why it cannot be built yet

The remaining bullets are about webhooks, and Baileys has none. It holds a
socket; there is no HTTP request to acknowledge and nothing retries it.

| T07 asks for | today | after T06 |
| --- | --- | --- |
| acknowledge webhooks immediately | nothing to acknowledge | required |
| persist the inbound event first | Hermes stores the message | needs a real inbound queue |
| queue background work, track retries | outbound only, via `delivery_obligations` | inbound too |
| deduplicate by provider message id | **done**, patch 15 + Convex | unchanged |
| idempotent writes | **done**, tested | unchanged |
| dead-letter after bounded retries | outbound has `abandoned` | inbound needs one |

The outbound side already has the shape T07 wants for inbound:
`delivery_obligations` persists the obligation, tracks attempts, and has a
terminal `abandoned` state that `ted-watch.py` watches. When the inbound
pipeline is built it should look like that rather than inventing a second
vocabulary.

## Re-verify

```
npm run hermes:patch:check     # patch 15 still applied
npm test -- convex-model       # the dedupe key still behaves
```

`ted-gate-guard.py` counts the patches and `ted-watch.py` runs it every fifteen
minutes, so a Hermes upgrade that drops patch 15 turns a check red on its own.
