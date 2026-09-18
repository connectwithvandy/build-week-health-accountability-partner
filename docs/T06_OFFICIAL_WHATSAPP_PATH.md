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
month**. Cost is not the obstacle. Filing a reminder as *marketing*
rather than *utility* would make it ₹520 a month and is the mistake to avoid.

**Unconfirmed and worth re-checking:** several vendor blogs say Meta will
charge for service messages from **1 October 2026** at the utility rate. Meta's
own pricing page still says non-template messages inside the window are free
and names no such date. If the blogs are right, the 321 free messages a month
become roughly **₹37 a month**. Still not the
obstacle; recheck near the date.

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

1. **Meta's free test number.** No SIM, no purchase, no cost. Creating a
   developer app issues one immediately, along with a pre-approved
   `hello_world` template. It will message up to **5 recipients** you verify
   first, which Meta treats as a hard allowlist.

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

## 7. What is still open

- Whether Ted's own number migrates cleanly. Needs step 6, and is the only
  step with no rehearsal available: the test number cannot rehearse a
  migration of a different number.
- Whether Meta approves a reminder template in Ted's voice at all.
- Whether service messages start being charged on 1 Oct 2026.
- Business verification, whenever growth passes 250 unique users a day.
