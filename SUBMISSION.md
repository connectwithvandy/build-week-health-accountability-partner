# Build Week submission — generated 2026-09-05 10:25:11 IST

Read from Convex deployment `hardy-scorpion-901` (TED_CONVEX_SITE_URL in /Users/vandana.agarwal/.hermes/.env (the live gateway's backend)) with read-only `npx convex data` queries. No writes, no migrations.

## Numbers

| Metric | Number | Source table | Exact filter |
| --- | ---: | --- | --- |
| Data coverage (every total below is lifetime, no date filter) | 2026-09-02 20:38:37 IST → 2026-09-05 10:20:29 IST | `dailyEntries + onboarding + reminders + reportedReplies + targets + userFacts + users` | `oldest and newest _creationTime across every table in the deployment — totals cannot reach further back than this` |
| Total user records created | 25 | `users` | `no filter — every row in the table` |
| Users onboarded (finished onboarding) | 4 | `onboarding` | `completedAt !== undefined` |
| Users onboarded (cross-check on the user row) | 4 | `users` | `status === "active"` |
| Users part-way through onboarding | 21 | `users` | `status === "onboarding"` |
| Users active in the last 24 hours | 22 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1788497711287 (2026-09-04 10:25:11 IST)` |
| Users active in the last 7 days | 25 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1787979311287 (2026-08-29 10:25:11 IST)` |
| Total inbound messages | NOT STORED | `dailyEntries` | `distinct externalMessageId where externalMessageId !== '' → 0 rows carry one; the schema has no messages table, so inbound turns are not counted anywhere in Convex` |
| Inbound messages — defensible floor | 31 | `dailyEntries` | `no filter — every row is one thing a user sent that Ted logged; excludes chat that produced no log, so this is a lower bound` |
| Meals logged | 27 | `dailyEntries` | `entryType === "meal"` |
| Individual food items logged | 62 | `dailyEntries` | `sum of meal.items.length where entryType === "meal"` |
| All logged entries (meal + water + steps + workout + commitment) | 31 | `dailyEntries` | `no filter — every row in the table` |
| Voice notes received (that produced a log) | 8 | `dailyEntries` | `source === "voice"` |
| Photos received (that produced a log) | 7 | `dailyEntries` | `source === "photo"` |
| Waitlist entries | NO SUCH TABLE | `—` | `no table matching /waitlist\|wait_list\|waiting/i exists in hardy-scorpion-901` |
| Payment / paid-user records | NO SUCH TABLE | `—` | `no table matching /pay\|subscription\|billing\|invoice\|checkout\|order/i exists in hardy-scorpion-901` |
| Memory facts stored about users | 40 | `userFacts` | `no filter — every row in the table` |
| Replies users reported as wrong | 1 | `reportedReplies` | `no filter — every row in the table` |

### Caveats

- **Inbound messages cannot be counted from Convex.** `convex/schema.ts` has no messages table, and `dailyEntries.externalMessageId` is written empty on every row (0 of 31). Use the line below as the defensible floor, or pull the real number from the WhatsApp gateway logs.

## Inbound messages, from the gateway

Read from the gateway's own store, `~/.hermes/state.db`, read-only, by `scripts/gateway-message-count.py`. Generated 2026-09-05 10:20:33 IST.

| Metric | Number | Source | Exact filter |
| --- | ---: | --- | --- |
| Inbound WhatsApp messages from users | 522 | `messages + sessions` | `messages.role = 'user' and sessions.source = whatsapp` |
| Inbound, excluding the busiest account | 348 | `messages + sessions` | `as above, minus the single highest-volume sender (173 messages), which is the builder's own testing` |
| Replies Ted sent back | 704 | `messages + sessions` | `messages.role = 'assistant' and sessions.source = whatsapp` |
| Distinct people who messaged Ted | 34 | `sessions` | `distinct COALESCE(user_id, chat_id) where source is whatsapp` |
| WhatsApp conversations | 66 | `sessions` | `rows in sessions where source is whatsapp` |
| Covering | 2026-08-30 23:48:09 IST → 2026-09-05 10:20:33 IST | `messages + sessions` | `oldest and newest message timestamp on a whatsapp session` |

Why this sits outside the Convex table: `convex/schema.ts` has no messages table
and `dailyEntries.externalMessageId` is empty on all 31 rows, so Convex can only
give a floor of one row per message that produced a log. The gateway records
every turn, which is why 522 is so much larger than that floor of 31.

Two things to know before quoting these:

- The database holds every Hermes session on this machine, so the raw 1609 rows
  in `messages` is not a product number. Only the WhatsApp rows above are.
- The busiest single sender accounts for 173 of the 521 attributable messages,
  33%, and is almost certainly testing by the builder. Quote 348 from 33 people
  where the number has to exclude that. One further inbound message sits on a
  session carrying no user id, so it is counted in 522 but attributed to nobody.

The gateway consistently sees more people than Convex has user records for. The
gap is people who messaged Ted without ever reaching a stored user row, plus
test numbers. Compare against the Convex table above rather than against a
figure repeated here, which would go stale on the next refresh.

## Fill in manually before submitting

Numbers here come from each post's own insights panel and from analytics.
Screenshot each panel as you go and keep the file names next to the row.

| Post | Link | Impressions | Reactions | Screenshot |
| --- | --- | ---: | ---: | --- |
| LinkedIn |  |  |  |  |
| Instagram |  |  |  |  |
| X |  |  |  |  |

- Unique site visitors this week: 
- Analytics screenshot: 
- Analytics read-only access link: 

## Checklist

- [ ] Live product URL — https://heyted.vercel.app/
- [ ] Public GitHub repo URL — https://github.com/connectwithvandy/build-week-health-accountability-partner
- [ ] Metrics — the table above, plus the manual numbers filled in
