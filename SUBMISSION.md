# Build Week submission — generated 2026-09-05 10:34:33 IST

Read from Convex deployment `hardy-scorpion-901` (TED_CONVEX_SITE_URL in /Users/vandana.agarwal/.hermes/.env (the live gateway's backend)) with read-only `npx convex data` queries. No writes, no migrations.

## Numbers

| Metric | Number | Source table | Exact filter |
| --- | ---: | --- | --- |
| Data coverage (every total below is lifetime, no date filter) | 2026-09-02 20:38:37 IST → 2026-09-05 10:20:29 IST | `dailyEntries + onboarding + reminders + reportedReplies + targets + userFacts + users` | `oldest and newest _creationTime across every table in the deployment — totals cannot reach further back than this` |
| Total user records created | 25 | `users` | `no filter — every row in the table` |
| Users onboarded (finished onboarding) | 4 | `onboarding` | `completedAt !== undefined` |
| Users onboarded (cross-check on the user row) | 4 | `users` | `status === "active"` |
| Users part-way through onboarding | 21 | `users` | `status === "onboarding"` |
| Users active in the last 24 hours | 22 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1788498273540 (2026-09-04 10:34:33 IST)` |
| Users active in the last 7 days | 25 | `dailyEntries + userFacts + onboarding + users + reportedReplies` | `distinct userId still present in 'users', with any of: dailyEntries.occurredAt \| dailyEntries.createdAt \| dailyEntries.updatedAt \| userFacts.updatedAt \| onboarding.updatedAt \| users.updatedAt \| reportedReplies.reportedAt >= 1787979873540 (2026-08-29 10:34:33 IST)` |
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

Numbers here come from each post's own insights panel, transcribed from the
social stats doc. Every link below was checked and returns 200.

| Post | Link | Impressions | Reactions | Screenshot |
| --- | --- | ---: | --- | --- |
| LinkedIn | https://lnkd.in/p/dXFgHZTh | 1,441 | not recorded | |
| Instagram | https://www.instagram.com/p/Dc1PCZwRFpl3YRkUfDaTqKYnXRoO2JjF8P_Lqk0/ | not available | 72 likes, 11 comments, 2 shares | `docs/evidence/instagram-insights.png` |
| X, post 1 | https://x.com/vandism_ag/status/2095558754586734706 | 155 views | 9 likes | |
| X, post 2 | https://x.com/vandism_ag/status/2096093283483312332 | 7 views | not recorded | |

**Total impressions across posts with a number: 1,603.** That is LinkedIn 1,441
plus X 155 plus X 7. Instagram is not in that total, so the real reach is higher
than 1,603 by however many people saw the Instagram post.

**Total recorded reactions: 92.** That is 72 Instagram likes, 11 Instagram
comments and 9 X likes. LinkedIn reactions are not recorded in the source doc,
so this is a floor rather than the true count.

Three gaps to close if there is time, each of which only makes the numbers
better:

- Instagram impressions are unavailable because the account is private. The
  likes and comments still count, but the reach cannot be shown.
- LinkedIn reactions and comments were not captured, only the 1,441 impressions.
  That is the best-performing post by reach, so its engagement is worth having.
- No screenshots are filed yet. Judges generally accept the numbers, but a
  screenshot of each insights panel is what makes them checkable.

- Unique site visitors this week: 
- Analytics screenshot: 
- Analytics read-only access link: 

## Checklist

- [x] Live product URL — https://heyted.vercel.app/
      Tested by hand on 2026-09-05: opened the site on a phone, tapped through
      to WhatsApp, sent Ted a message and got a reply. This also settles the
      number on the site being the one Ted answers on, which the three
      automated checks in `scripts/gateway-message-count.py --verify-number`
      could not confirm from the machine.
- [x] Public GitHub repo URL — https://github.com/connectwithvandy/build-week-health-accountability-partner
      Loaded with no login, so it is genuinely public.
- [x] Metrics — the Convex table, the gateway table, and the social numbers
- [ ] Unique site visitors — still the one number missing
