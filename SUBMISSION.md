# Build Week submission — generated 2026-09-05 10:18:32 IST

Read from Convex deployment `hardy-scorpion-901` (TED_CONVEX_SITE_URL in /Users/vandana.agarwal/.hermes/.env (the live gateway's backend)) with read-only `npx convex data` queries. No writes, no migrations.

## Numbers

| Metric | Number | Source table | Exact filter |
| --- | ---: | --- | --- |
| Data coverage (every total below is lifetime, no date filter) | 2026-09-02 20:38:37 IST → 2026-09-05 09:47:23 IST | `dailyEntries + onboarding + reminders + reportedReplies + targets + userFacts + users` | `oldest and newest _creationTime across every table in the deployment — totals cannot reach further back than this` |
| Total user records created | 24 | `users` | `no filter — every row in the table` |
| Users onboarded (finished onboarding) | 4 | `onboarding` | `completedAt !== undefined` |
| Users onboarded (cross-check on the user row) | 4 | `users` | `status === "active"` |
| Users part-way through onboarding | 20 | `users` | `status === "onboarding"` |
| Users active in the last 24 hours | 21 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1788497312572 (2026-09-04 10:18:32 IST)` |
| Users active in the last 7 days | 24 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1787978912572 (2026-08-29 10:18:32 IST)` |
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
