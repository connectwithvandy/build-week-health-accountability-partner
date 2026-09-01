import { v } from "convex/values";

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
    if (!user) return { success: true, deleted: false };

    const facts = await ctx.db
      .query("userFacts")
      .withIndex("by_user", (query) => query.eq("userId", user._id))
      .collect();
    for (const fact of facts) await ctx.db.delete(fact._id);
    await ctx.db.delete(user._id);
    return { success: true, deleted: true };
  },
});
