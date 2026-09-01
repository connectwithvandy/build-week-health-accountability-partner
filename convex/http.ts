import { httpRouter } from "convex/server";

import { internal } from "./_generated/api";
import { httpAction } from "./_generated/server";

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

    return json({ success: false, error: "Unsupported action" }, 400);
  }),
});

export default http;
