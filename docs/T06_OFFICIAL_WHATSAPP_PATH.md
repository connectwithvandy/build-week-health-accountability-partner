# T06 — the official WhatsApp path

**Status: decided, not executed.** Every claim here was checked on 18 Sep 2026
against the source named beside it, or measured from this system's own data.
Where something could not be verified it says so rather than guessing.

Ted runs today on **Baileys** (`@whiskeysockets/baileys` 7.0.0-rc13), an
unofficial WhatsApp client. It works, and it is the single largest structural
risk left in the project: it is a reverse-engineered client on somebody else's
network, and the number it uses is Vandy's.

---

## 1. Is Ted allowed on the official platform at all?

**Yes.** This was the part most likely to end the discussion, and it does not.

Meta changed the [Business Solution Terms](https://www.whatsapp.com/legal/business-solution-terms)
effective **15 January 2026** (immediately for numbers registered after
15 October 2025). The clause:

> Providers and developers of artificial intelligence or machine learning
> technologies... are strictly prohibited from accessing or using the WhatsApp
> Business Solution... for the purposes of providing... such technologies
> **when such technologies are the primary (rather than incidental or
> ancillary) functionality** being made available for use, as determined by
> Meta in its sole discretion.

It binds **AI Providers** shipping a general assistant. The reported bans hit
ChatGPT and Perplexity, which were exactly that. Ted is a health
accountability service whose product is meal logging, a calorie target and
reminders; the model is how it is built, not what is sold. That is the
permitted side of the line.

**The residual risk is real but small:** "as determined by Meta in its sole
discretion", and Ted *is* conversational. The mitigation is to describe the
service as what it does, never as an AI assistant, in the display name, the
business description and the app review.

**Health messaging.** The [Business Messaging Policy](https://whatsappbusiness.com/policy/)
says: *"Don't use WhatsApp for telemedicine or to send or request any health
related information, if applicable regulations prohibit"*. Conditional on local
regulation. Ted gives calorie estimates, not diagnosis or treatment, and
already refuses under-18s and never returns a deficit. No change needed, but
the gates are now load-bearing for platform compliance and not only for safety.

---

## 2. Cloud API direct, or a BSP?

**Direct Meta Cloud API.**

| | Cloud API direct | BSP |
| --- | --- | --- |
| Per-message cost | Meta's rate | Meta's rate **plus** a platform fee |
| Hosting | Meta hosts it | Meta hosts it |
| Integration work | a Hermes adapter | a Hermes adapter, against their API |
| Verification help | none | usually assists |
| Lock-in | none | their abstraction |

The integration cost is the same either way, because Hermes needs a new
platform adapter for either. A BSP's real value is hand-holding through
business verification, and that is not the blocker here (§3). A BSP's cost is
permanent. Direct.

---

## 3. What actually gates it

**Business verification is not required to start.** An unverified business is
capped at **250 unique customers per 24 hours**. Ted has **56 users**. The cap
bites at roughly four times the current size, so the stuck sole proprietorship
delays *scale*, not *migration*.

**Number identity.** Moving a number onto the Business Platform takes it off
the normal WhatsApp app. The thread history users can see stays on their
handsets; Ted's own record is in `state.db` either way. The display name needs
Meta approval and should describe the service, per §1.

**Not verified here:** whether Vandy's current number can be migrated without
losing the Baileys session in a way that strands anyone mid-conversation. This
needs a test number, and is the first thing to try.

---

## 4. The 24-hour window, which is the real question

Inside 24 hours of a user's message, Ted may say anything, in his own words,
free. Outside it, only a **pre-approved template**: fixed text with variable
slots, submitted in advance, charged per delivered message.

So the cost of migrating is a property of how Ted talks. Measured with
`scripts/ted-window-check.py` against `delivery_obligations`, which is the only
record of what people actually received:

```
406 message(s) delivered in the last 30 days

  replies to a person      178   0 outside the window
  scheduled reminders      228   85 outside the window

  inside the 24h window, free        321   79.1%
  outside it, needs a template        85   20.9%
```

**About a fifth of what Ted sends would have to become a template**, and all of
it is reminders. Replies are never a problem: by definition somebody has just
written.

*An earlier version of this section said 0% and "nothing Ted sends would need a
template". That was wrong. It read `delivery_obligations` alone, and a
scheduled reminder never touches that ledger — the cron scheduler hands it to
the adapter and writes a line to `agent.log`. The check reads both now, and
prints the reminder count separately so a zero there is visibly a reading
error rather than good news.*

**So the question T06 has to answer is a product question:** when the nudges
come back, can they be templates? A utility template can carry variables
("you logged {{1}} yesterday") but cannot improvise. "arre, you skipped
yesterday yaar, what's the plan?" cannot be generated per person outside the
window. Either the nudge becomes a fixed opener whose job is to reopen the
window, and the real conversation happens once they reply, or the product
changes.

**Rates** (India, read 18 Sep 2026, [Meta pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)):

- non-template messages inside an open window: **free**
- utility template: **~₹0.115**
- marketing template: **~₹0.8631**, about 7.5x

At 85 out-of-window reminders a month, utility templates cost about **₹10 a
month**. Cost is not the obstacle. Filing a reminder as *marketing* rather than
*utility* would make it about **₹73 a month** (85 × ₹0.8631). An earlier
version of this line said ₹520, which follows from no figure on this page; the
7.5x multiple is the real point. The reason to avoid marketing is not the bill:
it is a different approval bar, and a health reminder filed as a promotion can
be switched off by a user's own marketing settings.

**Largely settled, 19 Sep 2026.** The blogs said Meta would charge for service
messages from 1 October. Meta's own Step 2 page in the app says, in its own
words: *"For service messages where you reply to customer messages, you get
1,000 free user-initiated conversations each month."* So replies are not free
without limit any more, and they are free well past where Ted sits: **321 a
month against a cap of 1,000**. The cap, not the date, is the thing to watch,
and the trigger is roughly tripling the conversation volume.

**What is not optional is a payment method.** The same page: a payment method
is required to send business-initiated messages, which is *marketing, utility
and authentication* — every template. Read in Billing Hub on 19 Sep: the
WhatsApp Business account shows **No payment method**, balance $0.00. The two
templates in review therefore cannot send when approved. This is the blocker
for the reminder work, not the approval.

---

## 4b. What the move gains, not only what it costs

Everything above is about risk and constraint. There is a gain, and it is
larger than it looks.

**Interactive messages.** The official platform sends reply buttons (up to 3),
list messages (up to 10 options), link buttons and Flows, which is a small form
inside WhatsApp. Ted cannot send any of these today: the bridge sends text,
images, audio and documents, and nothing else.

**And we should not try on the current path.** The official Baileys library
removed button and list support in January 2026. WhatsApp requires a `<biz>`
node to authorise them, workarounds were reverse-engineered, and Meta patched
them out. Community forks still offer it and carry a reported ban risk, on the
one number 56 users talk to. Not worth it.

**Why this matters more than the polish.** Every failure found in real
onboarding threads on 18 Sep is a free-text answer that should have been a tap:

- Venky was asked "male or female?" and typed `male`, then typed `desk` to the
  next one. Both parsed, but nothing guaranteed they would.
- Ram answered `27`, `160`, `80` to three counted questions and the broad age
  read took his weight as his age: adult to adult, no refusal, and 265 kcal off
  the figure he was about to be handed.
- arpit asked a question instead of answering and stalled entirely.

`SETUP_QUESTIONS` is six questions, and at least four of them are closed
choices: sex, goal, activity level, and the tracking target. As buttons or a
list they stop being parsing problems. A whole class of bug in
`extract_calorie_profile` and `_resolve_measurements` simply has nothing to do.

**So the case for migrating is not only defensive.** It is: remove the risk of
being cut off, accept a template constraint on reminders, and gain the
interface this product should have had from the start.

*Not verified:* whether an interactive message can be sent inside the 24-hour
window without being a template. It is a non-template message type, so it
should be free and unrestricted inside the window, and onboarding always is.
Worth confirming on the free test number before designing around it.

## 5. Migration sequence

Each step is reversible until step 6.

1. ~~**Meta's free test number.**~~ — **done, 19 Sep 2026.** App "Ted",
   App ID `1092607106462705`, business portfolio "Ted Health". Test number
   `+1 (555) 162-3902`, Phone Number ID `1324962557368120`, WABA
   `1756517772307257`. Vandy's own number is the one verified recipient of a
   possible five, and Meta's demo template was sent to it and arrived, so
   outbound on the official platform is proved rather than assumed.

   **The token on that page is not the token.** Step 1's "Generate token"
   button issues a 24-hour user token. The adapter needs a System User
   permanent token from Business Settings, and that is still to do.

   No SIM, no purchase, no cost. It will message up to **5 recipients** you
   verify first, which Meta treats as a hard allowlist.

   *An earlier draft of this said "buy a spare SIM". That was wrong and was
   corrected the same evening when Vandy asked why it was needed. It is worth
   recording why the mistake was easy: the test number is a property of the
   developer app rather than of a phone, so it does not look like a phone
   number problem until you go and read how one is issued.*
2. ~~**A Hermes platform adapter** for the Cloud API~~ — **it already exists,
   found 19 Sep by looking rather than assuming.**
   `gateway/platforms/whatsapp_cloud.py` is 2,217 lines, sits beside the
   Baileys adapter exactly as this step describes, and is enabled by env vars.
   It covers outbound text over the Graph API, the webhook server and its
   verify-token handshake, X-Hub-Signature-256 HMAC checking, wamid replay
   protection, media both ways, and interactive buttons and lists. Hermes also
   ships `hermes_cli/setup_whatsapp_cloud.py` and its own tests for it.

   Its docstring lists **"Phase 5 — 24-hour conversation window + template
   fallback"** as scope, and phase 5 is the part that is *not* built: no
   template payload appears anywhere in the file and nothing tracks the
   window. That half is Ted-specific anyway — which template a reminder
   becomes, and what goes in its variable, is a fact about our cron jobs — so
   it is written in this repo as `hermes/ted_whatsapp_templates/`, pure and
   tested, sending nothing. Wiring it needs a patch: `pre_cron_agent` from
   patch 13 is the right hook and the right moment, but it understands `skip`
   and `allow` only, so a third action has to be added to carry a template
   back.
3. **Templates drafted and submitted** for the reminders, in the *utility*
   category, and approved. This has a lead time and nothing else can start it.

   **Submitted 19 Sep 2026:** `ted_daily_review` and `ted_scheduled_reminder`,
   both UTILITY, both *In review*. `ted_quiet_check` held pending Vandy's
   decision. `ted_daily_review` was stopped by Meta's pre-submit category
   classifier until its body said the person set the check-in themselves; see
   `T06_TEMPLATES.md`, which now records that as a rule rather than a theory.

   *Drafted on 19 Sep: `T06_TEMPLATES.md` has three submission-ready templates
   covering all 20 enabled reminder jobs, the categorisation reasoning against
   Meta's own wording, and the answer this document left open — the nudge
   becomes a knock on the door, and Ted's real sentence is sent once the tap
   reopens the window. Not submitted: that needs step 1.*
4. **Full flow on the test number**: onboarding, a meal photo, a correction,
   a reminder outside the window through a template, and a deletion.
5. **Run both in parallel.** The test number serves up to five consenting
   users for a week while Baileys serves everybody else. Five is the platform
   limit and it is also enough: four to ten people talk to Ted on a normal day,
   so five real threads is not a sample, it is most of the traffic.
6. **Cutover.** Verified backup first (`ted-backup.py`, drilled), then migrate
   the live number, then start the Cloud adapter. Only one client may hold a
   WhatsApp identity at a time.

   **Ted has his own number.** `creds.json` registers him as "Ted" on a line
   that is neither Vandy's personal WhatsApp nor any user's, so the cutover
   moves Ted's own identity and takes nothing else down with it. That is a
   materially smaller risk than migrating a number a person also uses, and it
   was worth checking rather than assuming.

## 6. Rollback

- **Before step 6:** stop using the test number. There is nothing to undo and
  nothing was bought.
- **After step 6:** the honest answer is that rollback is slow. The number has
  left the Baileys session and returning it means re-registering on the normal
  app and re-pairing. **Users are not lost** — identity is the phone number and
  their threads persist — but Ted is down while it happens.
- **Therefore:** do not cut over without a drilled backup taken that day, and
  do not cut over on a day nobody is watching. `ted-watch.py` stays on the
  laptop watching from outside, as it does for any host move.

## 7. Three things block the channel, and none of them is code

Read in Meta's dashboard on 19 Sep 2026, after the token and templates were
done:

- **The app is unpublished.** Meta's banner on the webhook panel: production
  data "will be delivered unless the app has been published". Until then only
  test webhooks fired from the dashboard arrive. No real person can reach Ted
  on this channel, whatever else is configured.
- **No payment method** (§4). Templates cannot send.
- **The callback URL is an ngrok free tunnel**,
  `scarily-babbling-cupping.ngrok-free.dev`. A public URL exists, but it is one
  more process held up by hand on the laptop, the same shape as the caffeinate
  that keeps the machine awake. Treat it as equally unreliable.

Subscribed webhook fields: `messages`, and `message_template_status_update`
added 19 Sep so a template approval arrives rather than being checked by hand.

**A near miss found on the way.** `whatsapp_cloud` was live and absent from
`platform_toolsets`, so Hermes fell back to `hermes-whatsapp` — terminal,
files, patch and the browser — on a channel whose DM policy defaults to open,
and `ted-gate-guard.py` read only the `whatsapp` key and reported gates on.
Nothing reached it only because the app is unpublished. Both scripts now walk
every live WhatsApp platform. **Publishing the app was the step that would have
opened it**, and it is the step above.

## 7b. The words on the real number, decided in advance

§1 says the mitigation for the AI-provider clause is to describe the service as
what it does, never as an AI assistant, in the display name, the business
description and the app review. That is a rule with no text attached, and it
would be written at the worst possible moment — during a cutover, in a hurry.
So it is written here instead, 19 Sep 2026.

**None of it can be set today.** WhatsApp Manager refuses: *"Profile for the
test phone number cannot be edited."* The test number is fixed as "Test Number"
with category Other. These fields exist only on the real number, at step 6.

| field | text |
| --- | --- |
| Display name | `Ted Health` |
| About | `meal logging, a daily calorie target, and the reminders you ask for.` |
| Business description | `Ted helps you log meals, keeps a daily calorie target, and sends the reminders you set. Not medical advice, not for emergencies, diagnosis or treatment.` |
| Category | **Professional Services** |

Every clause names something the product does. No "assistant", no "chat", no
"AI", and no verb that only a model performs.

**Why Professional Services and not Medical & Health.** Medical & Health is the
more literal label and the argument for it is honesty. It is also the category
that invites the [Business Messaging Policy](https://whatsappbusiness.com/policy/)
health clause — *"Don't use WhatsApp for telemedicine or to send or request any
health related information, if applicable regulations prohibit"* — to be read
against Ted first rather than last. Ted gives calorie estimates, refuses
under-18s and never returns a deficit, so it would survive that reading; the
point is not to invite it for no gain. Professional Services is accurate for a
coaching service rather than evasive.

**What is deliberately not being softened:** `heyted.in/privacy` names the AI
model provider among the processors, and it stays. The clause in §1 binds what
is *sold*, not what a privacy policy discloses, and hiding a data processor to
look better to a reviewer is the kind of thing that fails much worse than it
succeeds. The same page carries "Ted is a habit coach, not a doctor", which is
the sentence the health policy actually wants to see.

App-level settings, checked and already correct on 19 Sep: app display name
`Ted`, business portfolio `Ted Health`, privacy policy, data deletion and terms
URLs all pointing at `https://heyted.in/privacy` (the last two were pointing at
`https://www.facebook.com/`, which is what a placeholder looks like to a
reviewer).

## 8. What is still open

- Whether Ted's own number migrates cleanly. Needs step 6, and is the only
  step with no rehearsal available: the test number cannot rehearse a
  migration of a different number.
- Whether Meta approves a reminder template in Ted's voice at all. Two are in
  review since 19 Sep; the pre-submit classifier passing them is not approval.
- Whether service messages start being charged on 1 Oct 2026.
- Business verification, whenever growth passes 250 unique users a day.
