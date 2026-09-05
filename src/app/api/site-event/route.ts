import { ConvexHttpClient } from "convex/browser";

import { api } from "../../../../convex/_generated/api";
import {
  clientIp,
  istDayKey,
  istWeekKey,
  looksLikeABot,
  normalisePlacement,
  visitorHash,
} from "@/lib/site-analytics";

/**
 * Where the website reports its own traffic.
 *
 * The landing page and /privacy send one small beacon here on load, and one
 * more when someone taps "Message Ted". This route is the only place that sees
 * an IP address: it turns it into a weekly one-way hash (see
 * `src/lib/site-analytics.ts`) and hands Convex the hash, never the address.
 *
 * It always answers 204 to a browser, whatever happened, so a visitor never
 * waits on analytics and never sees an error from it. Configuration problems
 * are logged for the runtime logs instead of being returned.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const noContent = () => new Response(null, { status: 204 });

export async function POST(request: Request) {
  const convexUrl = process.env.NEXT_PUBLIC_CONVEX_URL;
  const secret = process.env.TED_SITE_SECRET;

  if (!convexUrl || !secret) {
    console.error(
      "[site-event] not recording: NEXT_PUBLIC_CONVEX_URL or TED_SITE_SECRET is missing from this deployment.",
    );
    return noContent();
  }

  const userAgent = request.headers.get("user-agent") ?? "";
  if (looksLikeABot(userAgent)) return noContent();

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return noContent();
  }

  if (!body || typeof body !== "object") return noContent();

  const input = body as { type?: unknown; path?: unknown; placement?: unknown; referrer?: unknown };

  const type =
    input.type === "page_view" || input.type === "whatsapp_click" ? input.type : undefined;
  if (!type) return noContent();

  const now = Date.now();
  const weekKey = istWeekKey(now);

  // Only the path is kept from whatever the page sent — never a query string,
  // which is where a stray email address or token would hide.
  const path = typeof input.path === "string" ? input.path.split("?")[0].slice(0, 255) : "/";

  // The referrer is kept as a bare hostname: enough to tell Instagram from
  // LinkedIn, not enough to record the post someone came from.
  let referrer: string | undefined;
  if (typeof input.referrer === "string" && input.referrer.length > 0) {
    try {
      referrer = new URL(input.referrer).hostname;
    } catch {
      referrer = undefined;
    }
  }

  try {
    await new ConvexHttpClient(convexUrl).mutation(api.site.record, {
      secret,
      type,
      visitorHash: visitorHash({
        ip: clientIp(request.headers),
        userAgent,
        weekKey,
        salt: process.env.SITE_EVENT_SALT,
      }),
      dayKey: istDayKey(now),
      weekKey,
      path,
      placement: type === "whatsapp_click" ? normalisePlacement(input.placement) : undefined,
      referrer,
    });
  } catch (error) {
    console.error("[site-event] Convex refused the event:", error);
  }

  return noContent();
}
