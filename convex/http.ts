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

    // Named keys only, and never the whole memory: "delete" below is the
    // privacy teardown and this is a cleanup. Capped at the same 10 as a save,
    // because a caller asking to forget more than ten keys in one request is
    // reaching for the teardown and should have to say so.
    if (input.action === "forget-facts") {
      const keys = Array.isArray((body as { keys?: unknown }).keys)
        ? ((body as { keys: unknown[] }).keys.filter(
            (key): key is string => typeof key === "string" && key.trim() !== "",
          ))
        : null;
      if (!keys || keys.length === 0 || keys.length > 10) {
        return json({ success: false, error: "Invalid keys" }, 400);
      }
      const result = await ctx.runMutation(internal.ted.deleteUserFacts, {
        whatsappUserId: input.whatsappUserId,
        keys,
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
        // Only the two known kinds are forwarded. Anything else, including a
        // missing value from an older gateway, is treated as an ordinary nudge:
        // the stricter of the two paths, so a garbled field can never be the
        // thing that lets a 3am water ping through.
        const rawKind = String(payload.kind ?? "");
        const kind = rawKind === "dailyReview" ? "dailyReview" : "nudge";
        const result = await ctx.runMutation(internal.ted.gateReminderDelivery, {
          whatsappUserId: input.whatsappUserId,
          nowLocalTime: String(payload.nowLocalTime ?? ""),
          today: String(payload.today ?? ""),
          kind,
        });
        return json(result);
      }

      // Which stored facts shaped the reply that just went out. The gate does
      // the deciding, from the delivered text; this only counts.
      if (input.action === "factsUsed") {
        const keys = Array.isArray(payload.keys)
          ? payload.keys.filter((key): key is string => typeof key === "string")
          : [];
        // A cap, because this is reached on ordinary turns and a caller that
        // sent a thousand keys would be a bug worth refusing rather than
        // absorbing. Nobody has more than a few dozen facts.
        if (keys.length > 50) {
          return json({ success: false, error: "Too many keys" }, 400);
        }
        const result = await ctx.runMutation(internal.ted.noteFactsUsed, {
          whatsappUserId: input.whatsappUserId,
          keys,
        });
        return json(result);
      }

      // Builder read-back, same rule as "reports" and "setupAudit": it crosses
      // users, so it is reached with the shared secret and is never a model
      // tool. Read-only; the release itself is "reminderMissed" below.
      if (input.action === "pendingReminders") {
        const result = await ctx.runQuery(
          internal.ted.listPendingReminderDeliveries,
          {},
        );
        return json({ success: true, ...result });
      }

      // The counterpart to "reminderGate": the send it cleared never reached
      // anybody, so the day's count and the unanswered-nudge count go back.
      // Quoting the gate's own deliveryId is what keeps this exactly-once, so
      // a missing or wrong one is a no-op rather than a blind decrement.
      if (input.action === "reminderMissed") {
        const result = await ctx.runMutation(internal.ted.releaseReminderDelivery, {
          whatsappUserId: input.whatsappUserId,
          deliveryId: String(payload.deliveryId ?? ""),
          today: String(payload.today ?? ""),
          reason: payload.reason === undefined ? undefined : String(payload.reason),
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

      // Builder read-back, same rule as "reports": it crosses users, so it is
      // reached with the shared secret and is never a model tool.
      if (input.action === "setupAudit") {
        const result = await ctx.runQuery(internal.ted.listSetupState, {});
        return json({ success: true, ...result });
      }

      // Recompute one user's status from their own rows. Writes no new data,
      // so it is safe to run over everyone: see refreshSetup in ted.ts.
      if (input.action === "refreshSetup") {
        const result = await ctx.runMutation(internal.ted.refreshSetup, {
          whatsappUserId: input.whatsappUserId,
        });
        return json(result);
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
