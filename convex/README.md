# Convex functions for Ted

This is Ted's data layer. Nothing here talks to WhatsApp. The gateway does
that, and reaches these functions over HTTP.

| File | What it holds |
| --- | --- |
| `schema.ts` | The tables: `users`, `onboarding`, `userFacts`, `dailyEntries`, `targets`, `reminders`, `reportedReplies`. |
| `ted.ts` | The queries and mutations. Every handler takes the user from the live turn, so a user id supplied in the model's arguments is dropped. |
| `http.ts` | The authenticated `/ted-memory` endpoint the Hermes gateway calls. It requires the shared secret in an `Authorization: Bearer` header; the queries and mutations behind it are internal, not public. |
| `model.ts` | Pure functions shared by the above, including `decideReminderDelivery` (quiet hours, pause, per-day cap) and `findClashingEntry` (duplicate logs). Pure so they can be tested without a deployment: see `__tests__/convex-model.test.ts`. |

Two rules this directory exists to enforce:

- **Per-user isolation.** `userFacts` is keyed by a one-way hash of the WhatsApp
  sender. A cross-user leak is what caused this table to exist, so the model can
  neither supply nor select an identity.
- **A failed write must say so.** Storage outages are tagged and surfaced as
  "that didn't save", which is a different message from the claim gate's "I
  haven't completed that action", and a tester could not previously tell the two
  apart.

The production deployment is `hardy-scorpion-901` (Europe, Ireland). Before
restarting the gateway after changing anything here, run:

```bash
npm run convex:check
```

It confirms the deployed backend still supports every action the gate calls.

Convex docs: <https://docs.convex.dev/functions>
