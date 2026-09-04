# Ted Beta Tester Flow

> **Read the first section.** Onboarding changed on 4 Sep 2026: the
> three-question opener was replaced by the counted five (order 19 in
> `PROGRESS.md`). The old flow is kept at the bottom of this file, marked
> superseded, because it records what testers before 4 Sep actually saw.

## The counted five — current, since 4 Sep 2026

Onboarding is a state machine in `hermes/ted_safety_gates/__init__.py`
(`SETUP_QUESTIONS`), not a prompt instruction, so the model cannot reorder,
skip, or add to it. Each question carries its own count:

| # | Asks for | Wording |
| --- | --- | --- |
| 1/5 | age | how old are you? beta's 18+ |
| 2/5 | height | how tall are you? |
| 3/5 | weight | and your weight? |
| 4/5 | sex | male or female? the formula needs one or the other. |
| 5/5 | activity | how active is a normal day? desk most of it, on your feet, or training regularly? |

Why exactly five: these are exactly the five Mifflin–St Jeor inputs, which is
what makes "five questions" literally true. A sixth would make the count a lie,
so the city and the check-in time wait until a reminder is actually being set.

1/5 is deliberately plain while the rest of Ted is cheeky — the age answer is
the only thing that makes the under-18 refusal reachable, and a joke inviting
someone to lie there is the one joke that costs something.

Three further rules the gate enforces:

- **Be sure, or ask.** An answer it cannot read confidently is asked again
  rather than stored. A question is asked at most three times
  (`_MAX_SETUP_ASKS`) so a counted question cannot loop.
- **The answer is read as a shape, not matched against a phrase list.** A real
  user answered 5/5 with a word that was not one of the three offered labels.
- **A read-back** confirms what was captured before the number is used.

## Superseded: the three-question opener (31 Aug – 4 Sep 2026)

## Hermes `SOUL.md` onboarding

This behavior was added to Ted's Hermes instructions on 31 August 2026.

### Three-question opener

1. First message:

   > Chalo, done. What should I call you?

2. After the user answers:

   > Nice to meet you, [name]. Before we get into it, I’ll remember what you share so I can coach your day. I’m not a doctor, and you can say “delete my data” anytime and it’s gone.
   >
   > So, what’s the one thing you want to change?

3. After the user shares their goal:

   > And what time should I check in each day? Send your city too, so I get the time right.

4. After the user answers:

   > Done. Message me a meal, photo, voice note, or any progress update whenever it happens. I’ll pick up the rest as we go.

### Rules after the opener

- Do not ask for a full profile before coaching starts.
- Ask for age, height, weight, targets, plans, quiet hours, or commitments only when the current conversation needs them.
- Immediately before first calculating or discussing a calorie target, ask: “Quick check before I do this: are you 18 or older?”
- If the answer is no, do not calculate or recommend a calorie target.
- Keep the existing medical boundary and confirmed “delete my data” behavior.

## Tester invitation

> Hey, I’m testing Ted, a health accountability coach that lives on WhatsApp. Could you use it for one normal day and message your meals or health updates as they happen? Try text, a photo, or a voice note. Please tell me the first moment that feels confusing, wrong, or annoying. Start here: [WhatsApp link]

## What Vandy records

For each tester, record only:

- Did they answer all three opening questions?
- What was their first real update?
- Did Ted's check-in change what they did next?
- Where did they first hesitate, stop, or correct Ted?
