import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

import {
  dailyEntryStateValidator,
  dailyEntryTypeValidator,
  goalValidator,
  inputSourceValidator,
  onboardingFieldValidator,
} from "./model";

const timestamp = v.number();

export default defineSchema({
  users: defineTable({
    whatsappUserId: v.string(),
    status: v.union(v.literal("onboarding"), v.literal("active"), v.literal("deleting")),
    name: v.optional(v.string()),
    age: v.optional(v.number()),
    heightCm: v.optional(v.number()),
    weightKg: v.optional(v.number()),
    timeZone: v.optional(v.string()),
    goal: v.optional(goalValidator),
    consentAcceptedAt: v.optional(timestamp),
    medicalDisclaimerAcceptedAt: v.optional(timestamp),
    createdAt: timestamp,
    updatedAt: timestamp,
  }).index("by_whatsapp_user_id", ["whatsappUserId"]),

  onboarding: defineTable({
    userId: v.id("users"),
    currentField: onboardingFieldValidator,
    completedFields: v.array(onboardingFieldValidator),
    startedAt: timestamp,
    completedAt: v.optional(timestamp),
    updatedAt: timestamp,
  }).index("by_user", ["userId"]),

  targets: defineTable({
    userId: v.id("users"),
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
    customCommitments: v.array(
      v.object({
        commitmentId: v.string(),
        label: v.string(),
        active: v.boolean(),
      }),
    ),
    createdAt: timestamp,
    updatedAt: timestamp,
  }).index("by_user", ["userId"]),

  reminders: defineTable({
    userId: v.id("users"),
    maxPerDay: v.number(),
    morningCommitmentId: v.string(),
    dailyReviewTime: v.string(),
    quietHoursStart: v.string(),
    quietHoursEnd: v.string(),
    pausedUntil: v.optional(timestamp),
    items: v.array(
      v.object({
        reminderId: v.string(),
        commitmentId: v.string(),
        localTime: v.string(),
        enabled: v.boolean(),
        followUpAfterMinutes: v.optional(v.number()),
      }),
    ),
    createdAt: timestamp,
    updatedAt: timestamp,
  }).index("by_user", ["userId"]),

  dailyEntries: defineTable({
    userId: v.id("users"),
    localDate: v.string(),
    entryType: dailyEntryTypeValidator,
    source: inputSourceValidator,
    state: dailyEntryStateValidator,
    occurredAt: timestamp,
    externalMessageId: v.string(),
    dedupeKey: v.string(),
    note: v.optional(v.string()),
    meal: v.optional(
      v.object({
        items: v.array(v.string()),
        calories: v.number(),
        proteinGrams: v.number(),
        carbohydrateGrams: v.number(),
        fatGrams: v.number(),
        fiberGrams: v.number(),
      }),
    ),
    waterMl: v.optional(v.number()),
    steps: v.optional(v.number()),
    workoutMinutes: v.optional(v.number()),
    commitmentId: v.optional(v.string()),
    correctedEntryId: v.optional(v.id("dailyEntries")),
    createdAt: timestamp,
    updatedAt: timestamp,
  })
    .index("by_user_and_date", ["userId", "localDate"])
    .index("by_user_and_dedupe_key", ["userId", "dedupeKey"]),
});
