import { v } from "convex/values";

import type { Doc, Id } from "./_generated/dataModel";

import { internalMutation, internalQuery } from "./_generated/server";
import type { MutationCtx } from "./_generated/server";
import {
  addLocalDays,
  buildDedupeKey,
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
    return { success: true, duplicate: false, entryId, dedupeKey };
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

    return {
      summary: summariseDay(localDate, entries),
      entries: entries.map((entry) => ({
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
    const user = await ensureUser(ctx, whatsappUserId);
    const now = Date.now();
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
      return { success: true, created: false, targetId: existing._id };
    }

    const targetId = await ctx.db.insert("targets", {
      userId: user._id,
      customCommitments: customCommitments ?? [],
      ...fields,
      createdAt: now,
      updatedAt: now,
    });
    await ctx.db.patch(user._id, { updatedAt: now });
    return { success: true, created: true, targetId };
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
      patch.pausedUntil = pausedUntil === null ? undefined : pausedUntil;
    }

    if (existing) {
      await ctx.db.patch(existing._id, patch);
      await ctx.db.patch(user._id, { updatedAt: now });
      return { success: true, created: false, reminderId: existing._id };
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
    return { success: true, created: true, reminderId };
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
        timeZone: v.optional(v.string()),
        goal: v.optional(goalValidator),
      }),
    ),
  },
  handler: async (ctx, { whatsappUserId, currentField, completedField, profile }) => {
    const user = await ensureUser(ctx, whatsappUserId);
    const now = Date.now();

    if (profile) {
      const patch: Record<string, unknown> = { updatedAt: now };
      for (const [key, value] of Object.entries(profile)) {
        if (value !== undefined) patch[key] = value;
      }
      if (currentField === "complete") patch.status = "active";
      await ctx.db.patch(user._id, patch);
    } else if (currentField === "complete") {
      await ctx.db.patch(user._id, { status: "active", updatedAt: now });
    }

    const existing = await ctx.db
      .query("onboarding")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .unique();

    if (!existing) {
      const onboardingId = await ctx.db.insert("onboarding", {
        userId: user._id,
        currentField,
        completedFields: completedField ? [completedField] : [],
        startedAt: now,
        completedAt: currentField === "complete" ? now : undefined,
        updatedAt: now,
      });
      return { success: true, created: true, onboardingId };
    }

    const completedFields = [...existing.completedFields];
    if (completedField && !completedFields.includes(completedField)) {
      completedFields.push(completedField);
    }
    await ctx.db.patch(existing._id, {
      currentField,
      completedFields,
      completedAt:
        currentField === "complete" ? (existing.completedAt ?? now) : existing.completedAt,
      updatedAt: now,
    });
    return { success: true, created: false, onboardingId: existing._id };
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
    } else {
      // Counted at the moment a nudge is actually cleared to send, for the
      // same reason the daily cap is: asking and not sending would burn the
      // budget silently, and here it would also march a present user towards
      // a break they never needed.
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
