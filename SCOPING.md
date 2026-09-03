# Ted — WhatsApp Health Accountability V1 Scoping Doc

## 1. USER — specific person

Vandy is 33 and works in sales. She spends 9–10 hours a day at a desk and already cares about eating well, exercising, walking enough, drinking water, and following a healthy routine.

She does not need another complicated tracker. She needs one coach inside WhatsApp that remembers her day and helps her act before it is too late.

V1 is limited to adults aged 18 and over.

## 2. PROBLEM — what's broken in their day

Vandy’s health information is split across apps, alarms, notes, and memory.

She may log a meal in one place, track water somewhere else, and forget a walk or workout during a busy workday. By dinner, she often discovers that an important commitment slipped and there is little time left to recover.

Existing tools also require her to remember to open them. They record isolated numbers but do not understand what she has already done, what she intended to do, or what would be most useful next.

## 3. WHAT V1 DOES — full user flow, step by step

1. The user visits a polished, mobile-first or web landing page

2. The page explains the product through benefits, WhatsApp chat examples, how it works, privacy information, and repeated “Start on WhatsApp” buttons. There is no product dashboard.

3. Pressing the button opens WhatsApp with the pre-filled message: “Okay Ted, let's do this 💪” There is no payment, waitlist, email, password, or separate account. The WhatsApp number identifies the user.

4. Ted opens conversationally: “Chalo, done. What should I call you?” After the name, Ted gives the short disclosure and asks the goal question in the same message. Answering the goal question records consent for the beta.

5. Beta setup has only two more questions after the name: the one thing the user wants to change, then “What time should I check in each day? Send your city too, so I get the time right.”

6. Ted then starts coaching. It asks for height, weight, age, calorie target, diet plan, steps, water, workouts, quiet hours, and custom commitments only when that information becomes relevant in a real conversation.

7. The 18+ check appears immediately before Ted first calculates or discusses a calorie target. The invited beta testers must already be known adults.

8. The user can provide an existing health plan through text, photos, voice notes, or PDFs. PDFs are accepted only for existing health plans, not for daily updates.

9. If no calorie target exists, V1 can calculate estimated maintenance calories using the Mifflin–St Jeor equation. It does not automatically prescribe a calorie deficit. The user must provide or choose any weight-loss target.

10. During the day, the user sends meals or progress updates through WhatsApp. Text and voice notes work for meals and all progress updates; photos work for meal updates; PDFs work only for existing health plans. Ted replies in text.

11. For a clear meal photo, the coach identifies the food and portions, logs it immediately, and returns estimated:

   - Calories
   - Protein
   - Carbohydrates
   - Fat
   - Fiber

   It then softly invites correction if anything looks wrong. It does not force the user to confirm every successful entry.

12. For a blurry or uncertain meal photo, the coach asks what is on the plate before saving it.

13. The user can immediately correct an entry in plain language, such as “That was paneer, not chicken.” The coach replaces the incorrect details and recalculates the estimates.

14. For confusing or unrelated input, the coach first repeats its best interpretation and asks whether it understood correctly. It then offers relevant examples or choices.

15. If an update appears to be a duplicate, the coach asks before logging it again.

16. If an update refers to another date, the coach confirms the exact date before saving it—for example, “You mean yesterday, August 29. Shall I save it there?”

17. The coach compares each confirmed update with the user’s saved targets, commitments, previous messages, and everything already logged that day.

18. It responds with current progress and one practical next action. Its language is supportive and never uses shame, punishment, or exercise as compensation for eating.

19. Users can ask “How am I doing today?” to see current totals, completed commitments, and what remains.

20. Reminders arrive at times chosen by the user. The coach sends only the user-selected commitment in the morning so the day does not begin with an overwhelming list.

21. The number of reminders depends on the user’s preferences. Reminders respect quiet hours and can be changed through WhatsApp.

22. If a reminder is ignored, the coach follows up once and then stops pursuing that commitment.

23. Users can pause reminders until a stated time or date and resume them later.

    If four consecutive nudges go unanswered, the coach stops nudging and asks
    once whether the user wants reminders paused for a few days, then stays
    silent until the user sends any message at all. It never sends a fifth
    unanswered nudge. The question obeys quiet hours and the daily cap like any
    other message.

24. At the user’s chosen evening time, the coach sends a daily review covering meals, nutrition estimates, water, steps, exercise, wins, missed commitments, and one realistic action that can still be completed.

    The coach also offers a weekly recap once, at the end of setup, and sends
    one only if the user says yes. It runs Monday to Sunday, is no more than
    four short lines, and is built only from what the user actually logged.
    Every average names the number of days it was computed from, and a week
    with nothing logged is reported as nothing logged rather than as zero.
    Declining is a stored answer, so the offer is never repeated.

25. V1 saves the full conversation and raw media, user profile, uploaded plans, goals, targets, reminders, quiet hours, confirmed logs, corrections, and daily reviews. Raw photos, voice notes, and PDFs remain stored until the user requests deletion. This history is used to make later responses more relevant.

26. Saved data remains until the user requests deletion. “Delete my data” permanently removes the user’s profile, plans, logs, media, and conversation history.

27. If the AI or logging system is unavailable, the coach clearly says the update was not saved and asks the user to try again.

28. If the coach gives a wrong or unsafe response, the user can report it. The coach provides a safe fallback without promising that a human coach will reply.

29. If the user mentions medical concerns or requests unsafe guidance, the coach stops that guidance and directs them to a qualified professional.

## 4. WHAT V1 DOES NOT DO — everything parked

V1 does not include:

- A user dashboard or separate tracking app
- Wearable, Apple Health, Oura, or other health-data integrations
- Sleep tracking; revisit it with a future Apple Health connection
- Personalized meal-plan creation
- Personalized workout-plan creation
- Automatic calorie-deficit prescriptions
- Medical advice, diagnosis, or treatment
- Bloodwork interpretation
- Supplement prescriptions
- Support for crash diets or extreme calorie targets
- Coaching for users under 18
- Voice-call coaching
- Replies sent as voice notes, GIFs, or stickers
- Social or community features
- Payments or subscriptions
- Human-coach escalation
- Viewing, correcting, or deleting older individual entries
- Automatic decisions based on unclear media
- A long setup questionnaire before the user receives coaching
- Punishment, guilt, shame, or advice to compensate for food through exercise

Future versions may explore calls and replies using voice notes, GIFs, and stickers.

## 5. RISKIEST ASSUMPTION — what could make this pointless

The riskiest assumption is that an AI coach that remembers and proactively follows up will actually improve users’ follow-through.

If users ignore the nudges or the coach does not change what they do next, the product becomes just another tracker.

The first success signal is behavioral: after receiving a timely follow-up, users complete or meaningfully reschedule a commitment they otherwise would have missed.
