import { v } from "convex/values";

import type { Id } from "./_generated/dataModel";

import { internalMutation, internalQuery } from "./_generated/server";

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
      return { facts: [] };
    }

    const facts = await ctx.db
      .query("userFacts")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .collect();

    return {
      facts: facts.map(({ key, value, updatedAt }) => ({ key, value, updatedAt })),
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
      rows: { _id: Id<"userFacts" | "onboarding" | "targets" | "reminders" | "dailyEntries"> }[],
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

    await ctx.db.delete(user._id);
    removed.users = 1;
    return { success: true, deleted: true, removed };
  },
});
