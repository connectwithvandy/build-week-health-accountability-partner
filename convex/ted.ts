import { v } from "convex/values";

import type { Doc, Id } from "./_generated/dataModel";

import { internalMutation, internalQuery } from "./_generated/server";
import type { MutationCtx, QueryCtx } from "./_generated/server";
import {
  addLocalDays,
  buildDedupeKey,
  calorieFloorFor,
  countsTowardDay,
  dailyEntryStateValidator,
  dailyEntryTypeValidator,
  decideReminderDelivery,
  findClashingEntry,
  goalValidator,
  inputSourceValidator,
  isLocalDateKey,
  isLocalTimeKey,
  needsDateConfirmation,
  onboardingFieldValidator,
  firstHealthValueProblem,
  pauseProblem,
  nextCompletedAt,
  setupSnapshotFrom,
  type SetupSnapshot,
  type SetupState,
  setupStateFor,
  summariseDay,
  summariseWeek,
  WEEK_LENGTH_DAYS,
  weekdayValidator,
  weekStartFor,
} from "./model";

const factValidator = v.object({
  key: v.string(),
  value: v.string(),
  sourceMessageId: v.optional(v.string()),
});

export const getUserMemory = internalQuery({
  args: { whatsappUserId: v.string() },
  handler: async (ctx, { whatsappUserId }) => {
    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();

    if (!user) {
      return {
        facts: [],
        unansweredNudges: 0,
        awaitingBreakReply: false,
        timeZone: null,
      };
    }

    const facts = await ctx.db
      .query("userFacts")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .collect();

    const policy = await ctx.db
      .query("reminders")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    return {
      facts: facts.map(({ key, value, updatedAt }) => ({ key, value, updatedAt })),
      // Read on every turn anyway, so the gate can tell whether a reply reset
      // is owed without paying for a second round trip on messages where it
      // is not — which is almost all of them.
      unansweredNudges: policy?.unansweredNudges ?? 0,
      awaitingBreakReply: policy?.awaitingBreakReply === true,
      // The gate does the conversion, in Python's zoneinfo. This is only the
      // store. Every date and time Ted writes or reads depends on it, so it
      // rides along on the read that every turn already makes.
      timeZone: user.timeZone ?? null,
    };
  },
});

export const saveUserFacts = internalMutation({
  args: {
    whatsappUserId: v.string(),
    facts: v.array(factValidator),
  },
  handler: async (ctx, { whatsappUserId, facts }) => {
    const now = Date.now();
    let user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();

    if (!user) {
      const userId = await ctx.db.insert("users", {
        whatsappUserId,
        status: "onboarding",
        createdAt: now,
        updatedAt: now,
      });
      user = await ctx.db.get(userId);
    }

    if (!user) {
      throw new Error("Could not create Ted user");
    }

    let saved = 0;
    for (const fact of facts) {
      const key = fact.key.trim().toLowerCase();
      const value = fact.value.trim();
      if (!key || !value || key.length > 80 || value.length > 500) {
        throw new Error("Fact keys must be 1–80 characters and values 1–500 characters");
      }

      const existing = await ctx.db
        .query("userFacts")
        .withIndex("by_user_and_key", (query) =>
          query.eq("userId", user._id).eq("key", key),
        )
        .unique();

      if (existing) {
        await ctx.db.patch(existing._id, {
          value,
          sourceMessageId: fact.sourceMessageId,
          updatedAt: now,
        });
      } else {
        await ctx.db.insert("userFacts", {
          userId: user._id,
          key,
          value,
          sourceMessageId: fact.sourceMessageId,
          createdAt: now,
          updatedAt: now,
        });
      }
      saved += 1;
    }

    await ctx.db.patch(user._id, { updatedAt: now });
    return { success: true, saved };
  },
});

export const deleteUserMemory = internalMutation({
  args: { whatsappUserId: v.string() },
  handler: async (ctx, { whatsappUserId }) => {
    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();
    if (!user) {
      return { success: true, deleted: false, removed: {} };
    }

    // The privacy page promises "profile, plans, logs, uploads, reminders,
    // reviews". Every table below hangs off userId, so a partial teardown is
    // never a partial promise — it is a broken one.
    const removed: Record<string, number> = {};
    const clear = async (
      rows: {
        _id: Id<
          | "userFacts"
          | "onboarding"
          | "targets"
          | "reminders"
          | "dailyEntries"
          | "reportedReplies"
        >;
      }[],
      table: string,
    ) => {
      for (const row of rows) {
        await ctx.db.delete(row._id);
      }
      removed[table] = rows.length;
    };

    await clear(
      await ctx.db
        .query("userFacts")
        .withIndex("by_user", (query) => query.eq("userId", user._id))
        .collect(),
      "userFacts",
    );
    await clear(
      await ctx.db
        .query("onboarding")
        .withIndex("by_user", (query) => query.eq("userId", user._id))
        .collect(),
      "onboarding",
    );
    await clear(
      await ctx.db
        .query("targets")
        .withIndex("by_user", (query) => query.eq("userId", user._id))
        .collect(),
      "targets",
    );
    await clear(
      await ctx.db
        .query("reminders")
        .withIndex("by_user", (query) => query.eq("userId", user._id))
        .collect(),
      "reminders",
    );
    await clear(
      await ctx.db
        .query("dailyEntries")
        .withIndex("by_user_and_date", (query) => query.eq("userId", user._id))
        .collect(),
      "dailyEntries",
    );

    // A reported reply holds the user's own message, verbatim, and Ted's
    // answer to it. It is the user's data by any reading, and /privacy says
    // deletion removes everything Ted has stored about them. Leaving these
    // behind also orphaned them to a user id that no longer resolves, so the
    // builder read-back showed an empty sender for rows nobody could act on.
    // The bug report is worth less than the promise.
    await clear(
      await ctx.db
        .query("reportedReplies")
        .withIndex("by_user", (query) => query.eq("userId", user._id))
        .collect(),
      "reportedReplies",
    );

    await ctx.db.delete(user._id);
    removed.users = 1;
    return { success: true, deleted: true, removed };
  },
});

// ---------------------------------------------------------------------------
// Structured writes.
//
// Until now the only rows Ted ever created were a stub `users` record and
// loose key/value strings in `userFacts`. dailyEntries, targets, reminders and
// onboarding were modelled correctly and never written to, so today's meals
// and corrections lived in the conversation window and nowhere else.

async function ensureUser(
  ctx: { db: MutationCtx["db"] },
  whatsappUserId: string,
): Promise<Doc<"users">> {
  const now = Date.now();
  const existing = await ctx.db
    .query("users")
    .withIndex("by_whatsapp_user_id", (query) =>
      query.eq("whatsappUserId", whatsappUserId),
    )
    .unique();
  if (existing) return existing;

  const userId = await ctx.db.insert("users", {
    whatsappUserId,
    status: "onboarding",
    createdAt: now,
    updatedAt: now,
  });
  const created = await ctx.db.get(userId);
  if (!created) throw new Error("Could not create Ted user");
  return created;
}

/**
 * Read everything `setupStateFor` needs for one user, across the three tables
 * that hold it.
 *
 * `userId` is passed rather than re-resolved so a caller that has just written
 * a row reads back the same user it wrote to.
 */
async function buildSetupSnapshot(
  // Reader, not writer: this only ever reads, so the read-only audit query can
  // share the exact code the status refresh judges by. Two implementations of
  // "what is missing" is the bug this whole change exists to remove.
  ctx: { db: QueryCtx["db"] },
  user: Doc<"users">,
): Promise<SetupSnapshot> {
  const [target, reminder] = await Promise.all([
    ctx.db
      .query("targets")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique(),
    ctx.db
      .query("reminders")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique(),
  ]);
  return setupSnapshotFrom(user, target, reminder);
}

/**
 * Recompute `users.status` from what is actually stored, and return the gaps.
 *
 * Called after every write that could close or reopen one, so the status is a
 * fact about the row rather than a claim somebody made about it. This is the
 * only place outside `deleteUserMemory` that may move a user between
 * "onboarding" and "active": nothing else, and specifically not the model, gets
 * to decide.
 *
 * "deleting" is left alone. A user part-way through erasure whose rows happen
 * to still satisfy the requirements must not be quietly reactivated by a late
 * write landing after they asked to be forgotten.
 */
async function refreshSetupStatus(
  ctx: { db: MutationCtx["db"] },
  userId: Id<"users">,
): Promise<SetupState> {
  // Re-read rather than trust the caller's copy: every caller has just written
  // to one of these rows, and the whole point is to judge the state after the
  // write rather than the state that prompted it.
  const user = await ctx.db.get(userId);
  if (!user) throw new Error("Could not read Ted user");

  const state = setupStateFor(await buildSetupSnapshot(ctx, user));
  if (user.status === "deleting") return state;

  const now = Date.now();
  const derived = state.ready ? "active" : "onboarding";
  if (user.status !== derived) {
    await ctx.db.patch(user._id, { status: derived, updatedAt: now });
  }

  // `onboarding.completedAt` is stamped here, beside the status it has to
  // agree with, rather than only in `saveOnboarding`. Setup can be finished by
  // a write that never touches onboarding — a calorie target agreed in open
  // conversation reaches `setTarget` — and when that happened the user went
  // active while the column stayed empty forever. GT and Shreya were both in
  // that state on 16 Sept.
  //
  // Only an existing row is stamped. A user with no onboarding row at all has
  // not started one, and inventing it here would make `startedAt` a fiction;
  // `saveOnboarding` still owns creating the row.
  const onboarding = await ctx.db
    .query("onboarding")
    .withIndex("by_user", (query) => query.eq("userId", user._id))
    .unique();
  if (onboarding) {
    const completedAt = nextCompletedAt(onboarding.completedAt, state.ready, now);
    if (completedAt !== onboarding.completedAt) {
      await ctx.db.patch(onboarding._id, { completedAt, updatedAt: now });
    }
  }

  return state;
}

/**
 * Refuse a health number that cannot describe a person, before it is stored.
 *
 * Throwing rather than clamping, for the reason `setTarget`'s calorie floor
 * already gives: a clamp leaves Ted having said one number out loud while the
 * row holds another, and two stores disagreeing is the failure this codebase
 * keeps paying for. A refusal keeps them in step.
 *
 * The gateway turns this into one plain sentence for the user and writes the
 * detail below to its log. It is safe for this message to name the field and
 * the number because it never reaches a chat.
 */
function assertStorableHealthValues(fields: Record<string, unknown>): void {
  const problem = firstHealthValueProblem(fields);
  if (problem) throw new Error(problem);
}

const mealValidator = v.object({
  items: v.array(v.string()),
  calories: v.number(),
  proteinGrams: v.number(),
  carbohydrateGrams: v.number(),
  fatGrams: v.number(),
  fiberGrams: v.number(),
});

export const logDailyEntry = internalMutation({
  args: {
    whatsappUserId: v.string(),
    localDate: v.string(),
    entryType: dailyEntryTypeValidator,
    source: inputSourceValidator,
    state: v.optional(dailyEntryStateValidator),
    occurredAt: v.optional(v.number()),
    externalMessageId: v.optional(v.string()),
    note: v.optional(v.string()),
    meal: v.optional(mealValidator),
    waterMl: v.optional(v.number()),
    steps: v.optional(v.number()),
    workoutMinutes: v.optional(v.number()),
    commitmentId: v.optional(v.string()),
    correctsDedupeKey: v.optional(v.string()),
    // Milestone 10. Both default to false: a write that needs a question
    // asked first must fail closed, not slip through on an omitted flag.
    today: v.optional(v.string()),
    dateConfirmed: v.optional(v.boolean()),
    secondOneConfirmed: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    if (!isLocalDateKey(args.localDate)) {
      throw new Error("localDate must be YYYY-MM-DD in the user's own timezone");
    }
    // Everything a logged entry can carry a number in, including the macros
    // inside a meal, which the model estimates from a photo and which nothing
    // has ever checked.
    assertStorableHealthValues({
      waterMl: args.waterMl,
      steps: args.steps,
      workoutMinutes: args.workoutMinutes,
      calories: args.meal?.calories,
      proteinGrams: args.meal?.proteinGrams,
      carbohydrateGrams: args.meal?.carbohydrateGrams,
      fatGrams: args.meal?.fatGrams,
      fiberGrams: args.meal?.fiberGrams,
    });
    const user = await ensureUser(ctx, args.whatsappUserId);
    const now = Date.now();
    const occurredAt = args.occurredAt ?? now;
    const dedupeKey = buildDedupeKey({
      localDate: args.localDate,
      entryType: args.entryType,
      externalMessageId: args.externalMessageId,
      occurredAt,
      meal: args.meal,
      waterMl: args.waterMl,
      steps: args.steps,
      workoutMinutes: args.workoutMinutes,
      commitmentId: args.commitmentId,
    });

    // A message Ted has already logged is a re-delivery, not a second meal.
    const existing = await ctx.db
      .query("dailyEntries")
      .withIndex("by_user_and_dedupe_key", (query) =>
        query.eq("userId", user._id).eq("dedupeKey", dedupeKey),
      )
      .unique();
    if (existing) {
      return {
        success: true,
        duplicate: true,
        entryId: existing._id,
        dedupeKey,
      };
    }

    // A day the user named out loud is confirmed once before anything is
    // written. A meal on the wrong date quietly corrupts two daily reviews,
    // and "yesterday" is easy to mishear.
    if (
      args.today !== undefined &&
      needsDateConfirmation(args.localDate, args.today, args.dateConfirmed === true)
    ) {
      return {
        success: false,
        needsConfirmation: "date" as const,
        localDate: args.localDate,
        today: args.today,
        dedupeKey,
      };
    }

    // Not a re-delivery (that is the dedupeKey above) but plausibly the same
    // event described twice. Ask rather than guess in either direction.
    // A correction is exempt: it is explicitly replacing the row it clashes
    // with, which is the whole point of correctsDedupeKey.
    if (!args.correctsDedupeKey && args.secondOneConfirmed !== true) {
      const sameDay = await ctx.db
        .query("dailyEntries")
        .withIndex("by_user_and_date", (query) =>
          query.eq("userId", user._id).eq("localDate", args.localDate),
        )
        .collect();
      const clash = findClashingEntry(sameDay, {
        entryType: args.entryType,
        occurredAt,
        commitmentId: args.commitmentId,
        meal: args.meal,
      });
      if (clash) {
        return {
          success: false,
          needsConfirmation: "duplicate" as const,
          clashesWith: {
            entryType: clash.entryType,
            occurredAt: clash.occurredAt,
            dedupeKey: clash.dedupeKey,
            meal: clash.meal ?? undefined,
            commitmentId: clash.commitmentId ?? undefined,
          },
          dedupeKey,
        };
      }
    }

    // A correction supersedes the entry it replaces rather than deleting it,
    // so the day's totals stay honest and the original is still auditable.
    let correctedEntryId: Id<"dailyEntries"> | undefined;
    if (args.correctsDedupeKey) {
      const superseded = await ctx.db
        .query("dailyEntries")
        .withIndex("by_user_and_dedupe_key", (query) =>
          query.eq("userId", user._id).eq("dedupeKey", args.correctsDedupeKey!),
        )
        .unique();
      if (superseded) {
        await ctx.db.patch(superseded._id, { state: "corrected", updatedAt: now });
        correctedEntryId = superseded._id;
      }
    }

    const entryId = await ctx.db.insert("dailyEntries", {
      userId: user._id,
      localDate: args.localDate,
      entryType: args.entryType,
      source: args.source,
      state: args.state ?? "confirmed",
      occurredAt,
      externalMessageId: args.externalMessageId ?? "",
      dedupeKey,
      note: args.note,
      meal: args.meal,
      waterMl: args.waterMl,
      steps: args.steps,
      workoutMinutes: args.workoutMinutes,
      commitmentId: args.commitmentId,
      correctedEntryId,
      createdAt: now,
      updatedAt: now,
    });

    await ctx.db.patch(user._id, { updatedAt: now });

    // The day's running totals, computed here rather than asked for in a
    // second round trip, and never reconstructed by the model. This is what
    // lets the gate print "this meal" and "the day so far" from real numbers
    // in the same breath: guardrail 5, "use deterministic code for facts".
    const dayEntries = await ctx.db
      .query("dailyEntries")
      .withIndex("by_user_and_date", (query) =>
        query.eq("userId", user._id).eq("localDate", args.localDate),
      )
      .collect();

    return {
      success: true,
      duplicate: false,
      entryId,
      dedupeKey,
      daySummary: summariseDay(args.localDate, dayEntries),
    };
  },
});

export const getDaySummary = internalQuery({
  args: { whatsappUserId: v.string(), localDate: v.string() },
  handler: async (ctx, { whatsappUserId, localDate }) => {
    if (!isLocalDateKey(localDate)) {
      throw new Error("localDate must be YYYY-MM-DD in the user's own timezone");
    }
    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();
    if (!user) {
      return { summary: summariseDay(localDate, []), entries: [], target: null };
    }

    const entries = await ctx.db
      .query("dailyEntries")
      .withIndex("by_user_and_date", (query) =>
        query.eq("userId", user._id).eq("localDate", localDate),
      )
      .collect();

    const target = await ctx.db
      .query("targets")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    // Only what actually counts. A corrected row stays in the table for the
    // audit trail, but handing it to the model is how a correction gets undone
    // in the next sentence: it names the meal it can see. The count of what was
    // filtered is returned so nothing is hidden, just not nameable.
    const counted = entries.filter(countsTowardDay);
    return {
      summary: summariseDay(localDate, entries),
      superseded: entries.length - counted.length,
      entries: counted.map((entry) => ({
        entryType: entry.entryType,
        state: entry.state,
        occurredAt: entry.occurredAt,
        dedupeKey: entry.dedupeKey,
        note: entry.note,
        meal: entry.meal,
        waterMl: entry.waterMl,
        steps: entry.steps,
        workoutMinutes: entry.workoutMinutes,
        commitmentId: entry.commitmentId,
      })),
      target: target
        ? {
            calories: target.calories,
            proteinGrams: target.proteinGrams,
            steps: target.steps,
            waterMl: target.waterMl,
            workoutsPerWeek: target.workoutsPerWeek,
            nutritionSource: target.nutritionSource,
          }
        : null,
    };
  },
});

/**
 * The user's week, Monday to Sunday, read from what they actually logged.
 *
 * Takes any date inside the week and resolves it to that week's Monday, so the
 * caller cannot land on the wrong seven days by being a day out. Ted reads the
 * review from this and never from the conversation — the same rule the daily
 * review already follows, and the reason a weekly recap can be trusted at all.
 */
export const getWeekSummary = internalQuery({
  args: { whatsappUserId: v.string(), localDate: v.string() },
  handler: async (ctx, { whatsappUserId, localDate }) => {
    if (!isLocalDateKey(localDate)) {
      throw new Error("localDate must be YYYY-MM-DD in the user's own timezone");
    }
    const weekStart = weekStartFor(localDate);
    const weekEnd = addLocalDays(weekStart, WEEK_LENGTH_DAYS - 1);

    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();
    if (!user) {
      return { summary: summariseWeek(weekStart, []), target: null };
    }

    const entries = await ctx.db
      .query("dailyEntries")
      .withIndex("by_user_and_date", (query) =>
        query
          .eq("userId", user._id)
          .gte("localDate", weekStart)
          .lte("localDate", weekEnd),
      )
      .collect();

    const target = await ctx.db
      .query("targets")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    return {
      summary: summariseWeek(weekStart, entries),
      target: target
        ? {
            calories: target.calories,
            proteinGrams: target.proteinGrams,
            steps: target.steps,
            waterMl: target.waterMl,
            workoutsPerWeek: target.workoutsPerWeek,
          }
        : null,
    };
  },
});

export const setTarget = internalMutation({
  args: {
    whatsappUserId: v.string(),
    nutritionSource: v.optional(
      v.union(
        v.literal("healthPlan"),
        v.literal("userProvided"),
        v.literal("maintenanceEstimate"),
      ),
    ),
    calories: v.optional(v.number()),
    proteinGrams: v.optional(v.number()),
    carbohydrateGrams: v.optional(v.number()),
    fatGrams: v.optional(v.number()),
    fiberGrams: v.optional(v.number()),
    steps: v.optional(v.number()),
    waterMl: v.optional(v.number()),
    workoutsPerWeek: v.optional(v.number()),
    customCommitments: v.optional(
      v.array(
        v.object({
          commitmentId: v.string(),
          label: v.string(),
          active: v.boolean(),
        }),
      ),
    ),
  },
  handler: async (ctx, { whatsappUserId, customCommitments, ...fields }) => {
    // Before the calorie floor below, because that rule asks whether a target
    // is safe for this person and this one asks whether the number is a number
    // at all. A negative calorie target should never reach a comparison
    // against a resting-energy figure.
    assertStorableHealthValues(fields);

    const user = await ensureUser(ctx, whatsappUserId);
    const now = Date.now();

    // The floor, enforced here because this is where every calorie target
    // lands however it was arrived at. The gate's own `_loss_target` has always
    // refused to go below the body's resting burn, but that only ever guarded
    // the number the gate computed; a number agreed in open conversation
    // reached this mutation unchecked. Gourav got 1,550 against a 1,667 floor
    // on 5 Sep, UD got 1,850 against 1,956 on 7 Sep, and nothing objected.
    //
    // Rejected rather than quietly raised. Clamping would leave Ted having
    // said one number out loud while the row held another, which is the exact
    // disagreement between stores that caused UD's whole mess. Refusing keeps
    // the two in step and hands the caller the number it should have used.
    if (typeof fields.calories === "number") {
      const floor = calorieFloorFor(user);
      if (floor.known && fields.calories < floor.floor) {
        throw new Error(
          `A calorie target of ${fields.calories} is below this user's resting ` +
            `energy of ${floor.floor} kcal, which is what their body burns at ` +
            `rest. Use ${floor.floor} or higher. To lose faster than that ` +
            `allows, raise their activity rather than lowering the target.`,
        );
      }
    }

    const existing = await ctx.db
      .query("targets")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    // Only the fields actually supplied are written, so setting a step goal
    // never silently clears a calorie target the user already agreed.
    const patch: Record<string, unknown> = { updatedAt: now };
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined) patch[key] = value;
    }
    if (customCommitments !== undefined) patch.customCommitments = customCommitments;

    if (existing) {
      await ctx.db.patch(existing._id, patch);
      await ctx.db.patch(user._id, { updatedAt: now });
      // A calorie target is one of the eight requirements, so agreeing one can
      // be the write that finishes setup. Checked here rather than only in
      // saveOnboarding because this is reached from open conversation too.
      const state = await refreshSetupStatus(ctx, user._id);
      return { success: true, created: false, targetId: existing._id, ...state };
    }

    const targetId = await ctx.db.insert("targets", {
      userId: user._id,
      customCommitments: customCommitments ?? [],
      ...fields,
      createdAt: now,
      updatedAt: now,
    });
    await ctx.db.patch(user._id, { updatedAt: now });
    const state = await refreshSetupStatus(ctx, user._id);
    return { success: true, created: true, targetId, ...state };
  },
});

export const setReminder = internalMutation({
  args: {
    whatsappUserId: v.string(),
    maxPerDay: v.optional(v.number()),
    morningCommitmentId: v.optional(v.string()),
    dailyReviewTime: v.optional(v.string()),
    quietHoursStart: v.optional(v.string()),
    quietHoursEnd: v.optional(v.string()),
    // The weekly review. `weeklyReviewEnabled: false` is a real answer — the
    // user was asked and said no — and is why the offer is not repeated.
    weeklyReviewEnabled: v.optional(v.boolean()),
    weeklyReviewDay: v.optional(weekdayValidator),
    weeklyReviewTime: v.optional(v.string()),
    pausedUntil: v.optional(v.union(v.number(), v.null())),
    items: v.optional(
      v.array(
        v.object({
          reminderId: v.string(),
          commitmentId: v.string(),
          localTime: v.string(),
          enabled: v.boolean(),
          followUpAfterMinutes: v.optional(v.number()),
          // Absent means every day; see convex/schema.ts.
          days: v.optional(v.array(weekdayValidator)),
        }),
      ),
    ),
  },
  handler: async (ctx, { whatsappUserId, pausedUntil, items, ...fields }) => {
    for (const [key, value] of Object.entries(fields)) {
      if (typeof value === "string" && key.endsWith("Time") && !isLocalTimeKey(value)) {
        throw new Error(`${key} must be a 24-hour HH:MM local time`);
      }
      if (
        typeof value === "string" &&
        key.startsWith("quietHours") &&
        !isLocalTimeKey(value)
      ) {
        throw new Error(`${key} must be a 24-hour HH:MM local time`);
      }
    }
    for (const item of items ?? []) {
      if (!isLocalTimeKey(item.localTime)) {
        throw new Error("Each reminder needs a 24-hour HH:MM local time");
      }
    }

    const user = await ensureUser(ctx, whatsappUserId);
    const now = Date.now();
    const existing = await ctx.db
      .query("reminders")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    const patch: Record<string, unknown> = { updatedAt: now };
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined) patch[key] = value;
    }
    if (items !== undefined) patch.items = items;
    // null is how "un-pause" arrives over HTTP; undefined means "leave it".
    if (pausedUntil !== undefined) {
      // The backstop under the gate, which now computes this from a number of
      // days rather than handing the model a date to turn into a timestamp.
      // Sarah's pause arrived here as 26 Sep 2025 while Ted was telling her
      // "back on 23rd", and a pause already in the past silences nothing.
      const problem = pauseProblem(pausedUntil, now);
      if (problem) throw new Error(problem);
      patch.pausedUntil = pausedUntil === null ? undefined : pausedUntil;
    }

    if (existing) {
      await ctx.db.patch(existing._id, patch);
      await ctx.db.patch(user._id, { updatedAt: now });
      // Naming a check-in time is the last of the eight for most people, so
      // this is usually the write that flips them active.
      const state = await refreshSetupStatus(ctx, user._id);
      return { success: true, created: false, reminderId: existing._id, ...state };
    }

    const reminderId = await ctx.db.insert("reminders", {
      userId: user._id,
      maxPerDay: fields.maxPerDay ?? 3,
      morningCommitmentId: fields.morningCommitmentId ?? "",
      dailyReviewTime: fields.dailyReviewTime ?? "21:00",
      quietHoursStart: fields.quietHoursStart ?? "22:00",
      quietHoursEnd: fields.quietHoursEnd ?? "07:00",
      pausedUntil: pausedUntil ?? undefined,
      items: items ?? [],
      createdAt: now,
      updatedAt: now,
    });
    await ctx.db.patch(user._id, { updatedAt: now });
    const state = await refreshSetupStatus(ctx, user._id);
    return { success: true, created: true, reminderId, ...state };
  },
});

export const saveOnboarding = internalMutation({
  args: {
    whatsappUserId: v.string(),
    currentField: onboardingFieldValidator,
    completedField: v.optional(onboardingFieldValidator),
    profile: v.optional(
      v.object({
        name: v.optional(v.string()),
        age: v.optional(v.number()),
        heightCm: v.optional(v.number()),
        weightKg: v.optional(v.number()),
        sex: v.optional(v.union(v.literal("male"), v.literal("female"))),
        timeZone: v.optional(v.string()),
        goal: v.optional(goalValidator),
        // The privacy notice the gate already sends every new user. It was
        // going out and being recorded only in the gateway's local file, so
        // Convex held nothing for anybody: on 6 Sep the gate's own record
        // covered 31 of 32 users and Convex covered 0. A thing that happens
        // and is never written down did not happen as far as any other part
        // of the system can tell.
        privacyNoticeSentAt: v.optional(v.number()),
      }),
    ),
  },
  handler: async (ctx, { whatsappUserId, currentField, completedField, profile }) => {
    // The path a 4cm height reached a profile on. The gate bounds these too,
    // but only where a stored fact is promoted to a column, and this mutation
    // is reachable without going through that.
    if (profile) {
      assertStorableHealthValues({
        age: profile.age,
        heightCm: profile.heightCm,
        weightKg: profile.weightKg,
      });
    }

    const user = await ensureUser(ctx, whatsappUserId);
    const now = Date.now();

    if (profile) {
      const patch: Record<string, unknown> = { updatedAt: now };
      for (const [key, value] of Object.entries(profile)) {
        if (value !== undefined) patch[key] = value;
      }
      // No status here. `currentField: "complete"` used to set it directly,
      // which is what let the model mark Pradosh active with no age, height,
      // weight or target on file. What onboarding step the model believes it
      // is on is now a note about the conversation, not a claim about the row.
      await ctx.db.patch(user._id, patch);
    }

    const existing = await ctx.db
      .query("onboarding")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    // Derived from the rows, not from `currentField`. A model that says
    // "complete" over an empty profile no longer closes onboarding, and a
    // gate flow that filled everything in and never sent a closing write no
    // longer leaves the user open forever. Seven of the 32 users on 6 Sep were
    // in exactly that second state.
    const state = await refreshSetupStatus(ctx, user._id);

    if (!existing) {
      const onboardingId = await ctx.db.insert("onboarding", {
        userId: user._id,
        currentField,
        completedFields: completedField ? [completedField] : [],
        startedAt: now,
        // refreshSetupStatus found no row to stamp, so the insert carries the
        // same decision, taken by the same function.
        completedAt: nextCompletedAt(undefined, state.ready, now),
        updatedAt: now,
      });
      return { success: true, created: true, onboardingId, ...state };
    }

    const completedFields = [...existing.completedFields];
    if (completedField && !completedFields.includes(completedField)) {
      completedFields.push(completedField);
    }
    // No `completedAt` here. `refreshSetupStatus` above is the one writer, and
    // `existing` was read before it ran, so passing it back would overwrite a
    // fresh stamp with the stale value it replaced. The "kept once earned"
    // rule now lives in `nextCompletedAt`.
    await ctx.db.patch(existing._id, {
      currentField,
      completedFields,
      updatedAt: now,
    });
    return { success: true, created: false, onboardingId: existing._id, ...state };
  },
});

/**
 * Milestone 11 — record a reply the user says was wrong.
 *
 * Written by the safety gate straight from the conversation, not by the model.
 * A model that has just produced a bad reply is the last thing that should be
 * deciding whether the complaint gets stored, or what it says.
 */
export const reportBadReply = internalMutation({
  args: {
    whatsappUserId: v.string(),
    localDate: v.string(),
    userMessage: v.string(),
    assistantMessage: v.string(),
    note: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    if (!isLocalDateKey(args.localDate)) {
      throw new Error("localDate must be YYYY-MM-DD in the user's own timezone");
    }
    const user = await ensureUser(ctx, args.whatsappUserId);
    const now = Date.now();
    const reportId = await ctx.db.insert("reportedReplies", {
      userId: user._id,
      localDate: args.localDate,
      reportedAt: now,
      userMessage: args.userMessage.slice(0, 4000),
      assistantMessage: args.assistantMessage.slice(0, 4000),
      note: args.note?.slice(0, 1000) || undefined,
    });
    await ctx.db.patch(user._id, { updatedAt: now });
    return { success: true, reportId };
  },
});

/**
 * Every reported reply, newest first — the builder's read-back.
 *
 * Reached only through the shared secret on the HTTP route, never as a model
 * tool, so it cannot become a way for one user's turn to read another's.
 */
/**
 * Every user and what setup they are still missing, derived on read.
 *
 * Builder read-back, reached with the shared secret and never exposed as a
 * model tool, for the same reason `listReportedReplies` is not: it crosses
 * users, so it must never be somewhere one person's turn can reach.
 *
 * Read-only on purpose. Seeing the gaps and closing them are separate calls,
 * so an audit can be run against production without changing it.
 */
export const listSetupState = internalQuery({
  args: {},
  handler: async (ctx) => {
    const users = await ctx.db.query("users").collect();
    const rows = await Promise.all(
      users.map(async (user) => {
        const snapshot = await buildSetupSnapshot(ctx, user);
        const state = setupStateFor(snapshot);
        const onboarding = await ctx.db
          .query("onboarding")
          .withIndex("by_user", (query) => query.eq("userId", user._id))
          .unique();
        return {
          whatsappUserId: user.whatsappUserId,
          name: user.name ?? "",
          // Echoed so a reconcile can write a profile back without moving
          // anyone's place in the conversation. Backfilling a weight is not a
          // reason to restart someone's onboarding at step one.
          currentField: onboarding?.currentField ?? null,
          storedStatus: user.status,
          derivedStatus: state.ready ? "active" : "onboarding",
          // The whole reason this exists: where the two disagree, the stored
          // one is the lie and the derived one is the row.
          disagrees: user.status !== (state.ready ? "active" : "onboarding"),
          missing: state.missing,
          blocked: state.blocked,
          // The two values the gate keeps its own copy of. Returned here, on a
          // builder read-back, rather than added to getUserMemory, which runs
          // on every single turn and does not need them. Without these a
          // drift check has to guess which store is stale.
          goal: snapshot.goal ?? null,
          calorieTarget: snapshot.calories ?? null,
          createdAt: user.createdAt,
        };
      }),
    );
    rows.sort((a, b) => a.missing.length - b.missing.length || a.createdAt - b.createdAt);
    return { users: rows, total: rows.length };
  },
});

/**
 * Recompute one user's status from the rows, changing no data.
 *
 * The whole of step 3 for anyone whose record was already complete and only
 * looked unfinished. Idempotent by construction: it writes `status` only when
 * the derived value differs from the stored one, so running it twice is the
 * same as running it once, and running it on a correct row writes nothing.
 */
export const refreshSetup = internalMutation({
  args: { whatsappUserId: v.string() },
  handler: async (ctx, { whatsappUserId }) => {
    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();
    // Deliberately does not call ensureUser: an audit or a typo must not be
    // able to create a user row as a side effect of asking about one.
    if (!user) return { success: false, error: "No such user" };

    const before = user.status;
    const state = await refreshSetupStatus(ctx, user._id);
    return { success: true, before, after: state.ready ? "active" : "onboarding", ...state };
  },
});

export const listReportedReplies = internalQuery({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, { limit }) => {
    const capped = Math.min(Math.max(limit ?? 50, 1), 200);
    const reports = await ctx.db
      .query("reportedReplies")
      .withIndex("by_reported_at")
      .order("desc")
      .take(capped);

    return {
      reports: await Promise.all(
        reports.map(async (report) => {
          const user = await ctx.db.get(report.userId);
          return {
            reportedAt: report.reportedAt,
            localDate: report.localDate,
            // The hashed key, which is the only identity this system holds.
            whatsappUserId: user?.whatsappUserId ?? "",
            userMessage: report.userMessage,
            assistantMessage: report.assistantMessage,
            note: report.note,
            reviewedAt: report.reviewedAt,
          };
        }),
      ),
    };
  },
});

/**
 * The user said something, so they are not gone.
 *
 * Any inbound message resets this, not a particular answer to the break
 * question. Someone who ignores "want a break?" and sends a photo of their
 * lunch has answered it more clearly than "no" would have, and holding their
 * reminders hostage to the literal question would be the pedantic reading.
 *
 * Returns `changed` so the caller can skip the write when there is nothing to
 * clear, which is almost every message.
 */
export const noteUserReplied = internalMutation({
  args: { whatsappUserId: v.string() },
  handler: async (ctx, { whatsappUserId }) => {
    const user = await ctx.db
      .query("users")
      .withIndex("by_whatsapp_user_id", (query) =>
        query.eq("whatsappUserId", whatsappUserId),
      )
      .unique();
    if (!user) return { success: true, changed: false };

    const policy = await ctx.db
      .query("reminders")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();
    if (!policy) return { success: true, changed: false };

    const wasCounting = (policy.unansweredNudges ?? 0) > 0;
    const wasWaiting = policy.awaitingBreakReply === true;
    if (!wasCounting && !wasWaiting) {
      return { success: true, changed: false };
    }

    await ctx.db.patch(policy._id, {
      unansweredNudges: 0,
      awaitingBreakReply: false,
      updatedAt: Date.now(),
    });
    return { success: true, changed: true };
  },
});

/**
 * Milestone 12 — may a reminder go out to this user right now?
 *
 * A mutation rather than a query because a "yes" consumes one of the day's
 * allowance. Counting only what was actually cleared to send is what makes the
 * cap real; asking and not sending would otherwise burn the budget silently.
 */
export const gateReminderDelivery = internalMutation({
  args: {
    whatsappUserId: v.string(),
    nowLocalTime: v.string(),
    today: v.string(),
    // Optional so an older gateway, which does not send it, still gets the
    // previous behaviour rather than an argument-validation error mid-nudge.
    kind: v.optional(v.union(v.literal("dailyReview"), v.literal("nudge"))),
  },
  handler: async (ctx, args) => {
    if (!isLocalTimeKey(args.nowLocalTime)) {
      throw new Error("nowLocalTime must be a 24-hour HH:MM local time");
    }
    if (!isLocalDateKey(args.today)) {
      throw new Error("today must be YYYY-MM-DD in the user's own timezone");
    }
    const user = await ensureUser(ctx, args.whatsappUserId);
    const now = Date.now();
    const policy = await ctx.db
      .query("reminders")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    const decision = decideReminderDelivery(
      policy,
      args.nowLocalTime,
      args.today,
      now,
      args.kind ?? "nudge",
    );
    if (!decision.allowed) {
      return { success: true, ...decision, sentToday: 0 };
    }

    // No row to count into: the user has no stored preferences, so there is no
    // cap to enforce and nothing to increment. Cleared on quiet hours alone.
    if (!policy) {
      return { success: true, ...decision, sentToday: 0 };
    }

    const sentToday =
      (policy.sentLocalDate === args.today ? (policy.sentCount ?? 0) : 0) + 1;
    const patch: Record<string, unknown> = {
      sentLocalDate: args.today,
      sentCount: sentToday,
      updatedAt: now,
    };

    if (decision.offerBreak) {
      // The break offer is going out in place of the nudge. Nothing further
      // goes out until they say something, so the counter stops here rather
      // than climbing while Ted is deliberately silent.
      patch.awaitingBreakReply = true;
    } else if (!policy.awaitingBreakReply) {
      // Counted at the moment a nudge is actually cleared to send, for the
      // same reason the daily cap is: asking and not sending would burn the
      // budget silently, and here it would also march a present user towards
      // a break they never needed.
      //
      // Not counted once the break has already been offered. The evening
      // review still goes out in that state — see `decideReminderDelivery` —
      // and the counter exists only to decide when to offer a break, which has
      // happened. Letting it climb would leave a returning user's row reading
      // like weeks of ignored nudges that were never sent.
      patch.unansweredNudges = (policy.unansweredNudges ?? 0) + 1;
    }

    await ctx.db.patch(policy._id, patch);
    return {
      success: true,
      ...decision,
      sentToday,
      maxPerDay: policy.maxPerDay,
      unansweredNudges: patch.unansweredNudges ?? policy.unansweredNudges ?? 0,
    };
  },
});
