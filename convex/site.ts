import { ConvexError, v } from "convex/values";

import { mutation, query } from "./_generated/server";

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
    const users = await ctx.db.query("users").collect();

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
    let startsThisWeek = 0;
    for (const user of users) {
      const dayKey = istDayKey(user.createdAt);
      startsByDay.set(dayKey, (startsByDay.get(dayKey) ?? 0) + 1);
      if (weekDays.has(dayKey)) startsThisWeek += 1;
    }

    return {
      generatedAt: now,
      today: istDayKey(now),
      windowDays: WINDOW_DAYS,
      totals: {
        uniqueVisitors: visitorsAllTime.size,
        pageViews,
        whatsappClicks: clicks,
        uniqueClickers: clickersAllTime.size,
        conversationsStarted: users.length,
      },
      thisWeek: {
        uniqueVisitors: visitorsThisWeek.size,
        pageViews: pageViewsThisWeek,
        whatsappClicks: clicksThisWeek,
        uniqueClickers: clickersThisWeek.size,
        conversationsStarted: startsThisWeek,
      },
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
      })),
      // Everything the reader needs to judge the numbers above.
      coverage: {
        eventsScanned: events.length,
        truncated: events.length === ROW_LIMIT,
        oldestEventAt: events.length > 0 ? events[events.length - 1].createdAt : null,
        newestEventAt: events.length > 0 ? events[0].createdAt : null,
      },
    };
  },
});
