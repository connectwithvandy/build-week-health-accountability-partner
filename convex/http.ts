import { httpRouter } from "convex/server";

import { internal } from "./_generated/api";
import { httpAction } from "./_generated/server";
import { TED_HTTP_ACTIONS } from "./model";

const http = httpRouter();

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

http.route({
  path: "/ted-memory",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const expectedSecret = process.env.TED_HERMES_SHARED_SECRET;
    const suppliedSecret = request.headers.get("authorization");
    if (!expectedSecret || suppliedSecret !== `Bearer ${expectedSecret}`) {
      return json({ success: false, error: "Unauthorized" }, 401);
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ success: false, error: "Invalid JSON" }, 400);
    }

    if (!body || typeof body !== "object") {
      return json({ success: false, error: "Invalid request" }, 400);
    }

    const input = body as {
      action?: unknown;
      whatsappUserId?: unknown;
      facts?: unknown;
    };
    if (typeof input.whatsappUserId !== "string" || !input.whatsappUserId) {
      return json({ success: false, error: "Missing user identifier" }, 400);
    }

    if (input.action === "get") {
      const result = await ctx.runQuery(internal.ted.getUserMemory, {
        whatsappUserId: input.whatsappUserId,
      });
      return json({ success: true, ...result });
    }

    if (input.action === "save" && Array.isArray(input.facts)) {
      const facts = input.facts.filter(
        (fact): fact is { key: string; value: string; sourceMessageId?: string } =>
          Boolean(
            fact &&
              typeof fact === "object" &&
              typeof (fact as { key?: unknown }).key === "string" &&
              typeof (fact as { value?: unknown }).value === "string" &&
              (typeof (fact as { sourceMessageId?: unknown }).sourceMessageId ===
                "undefined" ||
                typeof (fact as { sourceMessageId?: unknown }).sourceMessageId ===
                  "string"),
          ),
      );
      if (facts.length !== input.facts.length || facts.length > 10) {
        return json({ success: false, error: "Invalid facts" }, 400);
      }
      const result = await ctx.runMutation(internal.ted.saveUserFacts, {
        whatsappUserId: input.whatsappUserId,
        facts,
      });
      return json(result);
    }

    if (input.action === "delete") {
      const result = await ctx.runMutation(internal.ted.deleteUserMemory, {
        whatsappUserId: input.whatsappUserId,
      });
      return json(result);
    }

    // The structured writes. Every one of these takes its user from
    // whatsappUserId above, which the gate binds from the live turn - the
    // model never gets to name whose row it is writing to.
    const payload = body as Record<string, unknown>;
    const rest = { ...payload };
    delete rest.action;
    delete rest.whatsappUserId;

    try {
      if (input.action === "log") {
        const result = await ctx.runMutation(internal.ted.logDailyEntry, {
          whatsappUserId: input.whatsappUserId,
          ...rest,
        } as Parameters<typeof ctx.runMutation>[1]);
        return json(result);
      }

      if (input.action === "day") {
        const result = await ctx.runQuery(internal.ted.getDaySummary, {
          whatsappUserId: input.whatsappUserId,
          localDate: String(payload.localDate ?? ""),
        });
        return json({ success: true, ...result });
      }

      // Any date inside the week; getWeekSummary resolves it to that week's
      // Monday itself, so a caller a day out still gets the right seven days.
      if (input.action === "week") {
        const result = await ctx.runQuery(internal.ted.getWeekSummary, {
          whatsappUserId: input.whatsappUserId,
          localDate: String(payload.localDate ?? ""),
        });
        return json({ success: true, ...result });
      }

      if (input.action === "target") {
        const result = await ctx.runMutation(internal.ted.setTarget, {
          whatsappUserId: input.whatsappUserId,
          ...rest,
        } as Parameters<typeof ctx.runMutation>[1]);
        return json(result);
      }

      if (input.action === "reminder") {
        const result = await ctx.runMutation(internal.ted.setReminder, {
          whatsappUserId: input.whatsappUserId,
          ...rest,
        } as Parameters<typeof ctx.runMutation>[1]);
        return json(result);
      }

      // What this deployment supports, so a checker can compare it against the
      // code that is about to talk to it. Read-only and side-effect free.
      if (input.action === "capabilities") {
        return json({ success: true, actions: [...TED_HTTP_ACTIONS] });
      }

      if (input.action === "reminderGate") {
        const result = await ctx.runMutation(internal.ted.gateReminderDelivery, {
          whatsappUserId: input.whatsappUserId,
          nowLocalTime: String(payload.nowLocalTime ?? ""),
          today: String(payload.today ?? ""),
        });
        return json(result);
      }

      // Any inbound message clears the unanswered-nudge count. Sent only when
      // there is something to clear, so this is a rare call, not a per-turn one.
      if (input.action === "replied") {
        const result = await ctx.runMutation(internal.ted.noteUserReplied, {
          whatsappUserId: input.whatsappUserId,
        });
        return json(result);
      }

      if (input.action === "report") {
        const result = await ctx.runMutation(internal.ted.reportBadReply, {
          whatsappUserId: input.whatsappUserId,
          ...rest,
        } as Parameters<typeof ctx.runMutation>[1]);
        return json(result);
      }

      // Builder read-back. Reached with the shared secret, never by the model,
      // so it is not a route one user's turn can use to read another's.
      if (input.action === "reports") {
        const result = await ctx.runQuery(internal.ted.listReportedReplies, {
          limit: typeof payload.limit === "number" ? payload.limit : undefined,
        });
        return json({ success: true, ...result });
      }

      if (input.action === "onboarding") {
        const result = await ctx.runMutation(internal.ted.saveOnboarding, {
          whatsappUserId: input.whatsappUserId,
          ...rest,
        } as Parameters<typeof ctx.runMutation>[1]);
        return json(result);
      }
    } catch (error) {
      // Convex argument validation and the explicit throws in ted.ts both land
      // here. The gate turns this into one plain sentence for the user; the
      // detail stays in the response for the log.
      return json(
        { success: false, error: error instanceof Error ? error.message : "Write rejected" },
        400,
      );
    }

    return json({ success: false, error: "Unsupported action" }, 400);
  }),
});

export default http;
