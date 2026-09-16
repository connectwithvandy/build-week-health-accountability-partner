import { ConvexError, v } from "convex/values";

import { mutation, query } from "./_generated/server";
import { setupRequirements, setupSnapshotFrom, setupStateFor } from "./model";

/**
 * The website's own numbers: who arrived, who tapped "Message Ted", and how
 * many of those turned into a first WhatsApp conversation.
 *
 * Both functions in this file are public, because the Next.js server calls them
 * over HTTPS and Convex only exposes public functions that way. Neither does
 * anything without `TED_SITE_SECRET`, a Convex environment variable that only
 * the server knows, so a stranger who finds the deployment URL can neither
 * write a fake visit nor read the dashboard:
 *
 *     npx convex env set TED_SITE_SECRET "$(openssl rand -hex 24)"
 *
 * and the same value in the Vercel project. Until it is set both functions
 * refuse, loudly, rather than collecting numbers nobody can trust.
 */
function assertSecret(supplied: string) {
  const expected = process.env.TED_SITE_SECRET;

  // ConvexError, not Error: a plain throw reaches the browser as the word
  // "Server Error" and nothing else, which would make the setup panel's promise
  // to name the missing variable a lie. ConvexError carries its message through.
  if (!expected) {
    throw new ConvexError(
      "TED_SITE_SECRET is not set on this Convex deployment. Add it in the Convex dashboard under Settings → Environment Variables, on the same deployment this site reads.",
    );
  }
  if (supplied !== expected) {
    throw new ConvexError(
      "TED_SITE_SECRET is set on Convex but does not match the value in the Vercel project. The two must be identical.",
    );
  }
}

/** Longest string accepted in any single field, so one bad caller cannot write
 *  a megabyte into the table. */
const MAX_FIELD = 255;

function trim(value: string | undefined) {
  if (value === undefined) return undefined;
  const cleaned = value.slice(0, MAX_FIELD);
  return cleaned.length > 0 ? cleaned : undefined;
}

export const record = mutation({
  args: {
    secret: v.string(),
    type: v.union(v.literal("page_view"), v.literal("whatsapp_click")),
    visitorHash: v.string(),
    dayKey: v.string(),
    weekKey: v.string(),
    path: v.string(),
    placement: v.optional(v.string()),
    referrer: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    assertSecret(args.secret);

    await ctx.db.insert("siteEvents", {
      type: args.type,
      visitorHash: args.visitorHash.slice(0, MAX_FIELD),
      dayKey: args.dayKey.slice(0, MAX_FIELD),
      weekKey: args.weekKey.slice(0, MAX_FIELD),
      path: args.path.slice(0, MAX_FIELD),
      placement: trim(args.placement),
      referrer: trim(args.referrer),
      createdAt: Date.now(),
    });

    return { recorded: true };
  },
});

/**
 * Convex refuses to scan more than 16384 documents in one query. This sits just
 * under it, and the summary reports whether it hit the ceiling rather than
 * quietly under-counting — the same rule `scripts/submission-report.ts` follows.
 */
const ROW_LIMIT = 16000;

/** Days of history the dashboard charts. */
const WINDOW_DAYS = 14;

const DAY_MS = 24 * 60 * 60 * 1000;
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/** The IST calendar day a timestamp falls in, as YYYY-MM-DD. */
function istDayKey(timestamp: number) {
  return new Date(timestamp + IST_OFFSET_MS).toISOString().slice(0, 10);
}

/** The list of IST day keys ending today, oldest first. */
function recentDayKeys(now: number, days: number) {
  const keys: string[] = [];
  for (let back = days - 1; back >= 0; back -= 1) {
    keys.push(istDayKey(now - back * DAY_MS));
  }
  return keys;
}

export const summary = query({
  args: { secret: v.string() },
  handler: async (ctx, { secret }) => {
    assertSecret(secret);

    const now = Date.now();
    const days = recentDayKeys(now, WINDOW_DAYS);
    const weekDays = new Set(recentDayKeys(now, 7));

    const events = await ctx.db
      .query("siteEvents")
      .withIndex("by_created_at")
      .order("desc")
      .take(ROW_LIMIT);

    // A user row is written the first time Ted records anything at all for a
    // WhatsApp number, so its creation is that person's first conversation.
    const users = await ctx.db.query("users").take(ROW_LIMIT);

    /**
     * Activation, as distinct from starting a conversation.
     *
     * Saying hello creates a user row and proves almost nothing. Finishing
     * setup and then logging a real meal, walk, glass of water or workout is
     * the smallest act that shows Ted did its job, and the two are reported
     * separately because collapsing them lets a wave of curious hellos read as
     * a wave of use.
     *
     * Readiness is recomputed here from the rows rather than read from
     * `onboarding.completedAt`, because that column is only ever written inside
     * `saveOnboarding`: a user whose last missing field was closed by a
     * `setTarget` call goes active without it. Trusting it would undercount.
     */
    // `.take(ROW_LIMIT)` rather than `.collect()`, for the same reason the site
    // events above use it: Convex refuses to scan past its ceiling, and a
    // `.collect()` that reaches it throws rather than returning a short list.
    // `dailyEntries` is the table that will get there first, and a short read
    // would quietly deflate the activation count, so the ceiling is reported
    // alongside the numbers rather than hidden behind them.
    const [onboarding, entries, targets, reminders] = await Promise.all([
      ctx.db.query("onboarding").take(ROW_LIMIT),
      ctx.db.query("dailyEntries").take(ROW_LIMIT),
      ctx.db.query("targets").take(ROW_LIMIT),
      ctx.db.query("reminders").take(ROW_LIMIT),
    ]);

    const targetByUser = new Map(targets.map((row) => [String(row.userId), row]));
    const reminderByUser = new Map(reminders.map((row) => [String(row.userId), row]));
    const onboardingStartedAt = new Map(
      onboarding.map((row) => [String(row.userId), row.startedAt]),
    );

    /**
     * The moment someone first logged anything. `occurredAt` is when it
     * happened in their day and `createdAt` is when Ted wrote it down; the
     * earlier of the two is the one that cannot post-date the act itself.
     */
    const firstEntryAt = new Map<string, number>();
    const entryDays = new Map<string, Set<string>>();
    for (const entry of entries) {
      const userId = String(entry.userId);
      const at = Math.min(entry.occurredAt, entry.createdAt);
      const known = firstEntryAt.get(userId);
      if (known === undefined || at < known) firstEntryAt.set(userId, at);

      const days = entryDays.get(userId) ?? new Set<string>();
      days.add(entry.localDate);
      entryDays.set(userId, days);
    }

    const visitorsAllTime = new Set<string>();
    const visitorsThisWeek = new Set<string>();
    const clickersAllTime = new Set<string>();
    const clickersThisWeek = new Set<string>();
    const visitorsByDay = new Map<string, Set<string>>();
    const clicksByDay = new Map<string, number>();
    const clicksByPlacement = new Map<string, { clicks: number; visitors: Set<string> }>();

    let pageViews = 0;
    let pageViewsThisWeek = 0;
    let clicks = 0;
    let clicksThisWeek = 0;

    for (const event of events) {
      const inThisWeek = weekDays.has(event.dayKey);

      if (event.type === "page_view") {
        pageViews += 1;
        if (inThisWeek) pageViewsThisWeek += 1;
        visitorsAllTime.add(event.visitorHash);
        if (inThisWeek) visitorsThisWeek.add(event.visitorHash);
      } else {
        clicks += 1;
        if (inThisWeek) clicksThisWeek += 1;
        clickersAllTime.add(event.visitorHash);
        if (inThisWeek) clickersThisWeek.add(event.visitorHash);
        clicksByDay.set(event.dayKey, (clicksByDay.get(event.dayKey) ?? 0) + 1);

        const placement = event.placement ?? "unlabelled";
        const bucket = clicksByPlacement.get(placement) ?? { clicks: 0, visitors: new Set<string>() };
        bucket.clicks += 1;
        bucket.visitors.add(event.visitorHash);
        clicksByPlacement.set(placement, bucket);
      }

      // A tap counts its person as a visitor of that day even if the page view
      // beacon was blocked, so the funnel can never show more clicks than
      // visitors on a day.
      const seen = visitorsByDay.get(event.dayKey) ?? new Set<string>();
      seen.add(event.visitorHash);
      visitorsByDay.set(event.dayKey, seen);
    }

    const startsByDay = new Map<string, number>();
    const activationsByDay = new Map<string, number>();
    let startsThisWeek = 0;
    let activationsThisWeek = 0;
    let activatedAllTime = 0;
    let loggedWithoutFinishing = 0;
    let returnedASecondDay = 0;

    /** How often each requirement is the thing still standing in someone's way.
     *  Counted only for people who have not finished, so it reads as a queue of
     *  open questions rather than a history of answered ones. */
    const blockedBy = new Map<string, number>(setupRequirements.map((name) => [name, 0]));

    for (const user of users) {
      const dayKey = istDayKey(user.createdAt);
      startsByDay.set(dayKey, (startsByDay.get(dayKey) ?? 0) + 1);
      if (weekDays.has(dayKey)) startsThisWeek += 1;

      const userId = String(user._id);
      const state = setupStateFor(
        setupSnapshotFrom(user, targetByUser.get(userId), reminderByUser.get(userId)),
      );
      const firstLog = firstEntryAt.get(userId);

      if ((entryDays.get(userId)?.size ?? 0) >= 2) returnedASecondDay += 1;

      if (!state.ready) {
        for (const requirement of state.missing) {
          blockedBy.set(requirement, (blockedBy.get(requirement) ?? 0) + 1);
        }
        // Someone logging real meals while Ted still considers them unfinished
        // is the most useful number on this page: it is the gap between what
        // the product thinks is happening and what is actually happening.
        if (firstLog !== undefined) loggedWithoutFinishing += 1;
        continue;
      }

      if (firstLog === undefined) continue;

      activatedAllTime += 1;
      // Dated by whichever half landed last, because that is when both were
      // first true. Someone who logged a meal mid-setup and finished the next
      // day activated on the second day, not the first. `startedAt` is the
      // closest stored stand-in for when setup closed, since `completedAt` is
      // exactly the column that cannot be trusted here.
      const activatedAt = Math.max(onboardingStartedAt.get(userId) ?? user.createdAt, firstLog);
      const activatedDay = istDayKey(activatedAt);
      activationsByDay.set(activatedDay, (activationsByDay.get(activatedDay) ?? 0) + 1);
      if (weekDays.has(activatedDay)) activationsThisWeek += 1;
    }

    return {
      generatedAt: now,
      today: istDayKey(now),
      windowDays: WINDOW_DAYS,
      /**
       * Lifetime rollups. The two visitor counts are deliberately NOT called
       * "unique visitors", because they cannot be: the visitor hash has the
       * week baked into it (see `visitorHash` in src/lib/site-analytics.ts), so
       * somebody who comes back in a second week arrives as a second hash and
       * is counted twice. Summed, they are visitor-weeks, an upper bound on
       * people, and naming them that way is the only version of this number
       * that survives being checked.
       *
       * The weekly figures below have no such problem. Within one week the hash
       * is stable, so `thisWeek.uniqueVisitors` really is a headcount.
       */
      totals: {
        visitorWeeks: visitorsAllTime.size,
        pageViews,
        whatsappClicks: clicks,
        clickerWeeks: clickersAllTime.size,
        conversationsStarted: users.length,
        activated: activatedAllTime,
        returnedASecondDay,
        loggedWithoutFinishingSetup: loggedWithoutFinishing,
      },
      thisWeek: {
        uniqueVisitors: visitorsThisWeek.size,
        pageViews: pageViewsThisWeek,
        whatsappClicks: clicksThisWeek,
        uniqueClickers: clickersThisWeek.size,
        conversationsStarted: startsThisWeek,
        activated: activationsThisWeek,
      },
      /** Ordered by how many people each one is holding up, worst first. */
      setupBlockers: [...blockedBy.entries()]
        .map(([requirement, people]) => ({ requirement, people }))
        .filter((row) => row.people > 0)
        .sort((a, b) => b.people - a.people),
      byPlacement: [...clicksByPlacement.entries()]
        .map(([placement, bucket]) => ({
          placement,
          clicks: bucket.clicks,
          uniqueClickers: bucket.visitors.size,
        }))
        .sort((a, b) => b.clicks - a.clicks),
      daily: days.map((dayKey) => ({
        dayKey,
        visitors: visitorsByDay.get(dayKey)?.size ?? 0,
        clicks: clicksByDay.get(dayKey) ?? 0,
        starts: startsByDay.get(dayKey) ?? 0,
        activations: activationsByDay.get(dayKey) ?? 0,
      })),
      // Everything the reader needs to judge the numbers above.
      coverage: {
        eventsScanned: events.length,
        usersScanned: users.length,
        entriesScanned: entries.length,
        // Any of these reaching the ceiling makes the activation numbers a
        // floor rather than a count, and the page says so in those words.
        entriesTruncated:
          entries.length === ROW_LIMIT ||
          users.length === ROW_LIMIT ||
          onboarding.length === ROW_LIMIT,
        truncated: events.length === ROW_LIMIT,
        oldestEventAt: events.length > 0 ? events[events.length - 1].createdAt : null,
        newestEventAt: events.length > 0 ? events[0].createdAt : null,
      },
    };
  },
});
