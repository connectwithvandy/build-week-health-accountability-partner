import { describe, expect, it } from "vitest";

import { POST } from "@/app/api/hermes/messages/route";
import { FIRST_REPLY } from "@/lib/hermes/handle-message";

const textPayload = {
  event: "message.received",
  message: {
    id: "hermes.local-test",
    from: "919999999999",
    timestamp: "2026-08-30T17:30:00.000Z",
    text: "Okay, let’s do this 🫡",
  },
};

describe("local Hermes adapter", () => {
  it("sends a simulated Hermes text event through the message handler", async () => {
    const request = new Request("http://localhost/api/hermes/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(textPayload),
    });

    const response = await POST(request);
    const result = await response.json();

    expect(response.status).toBe(200);
    expect(result).toEqual({
      status: "handled",
      message: {
        messageId: "hermes.local-test",
        from: "919999999999",
        text: "Okay, let’s do this 🫡",
        reply: FIRST_REPLY,
      },
    });
  });

  it("does not handle payloads without a supported text message", async () => {
    const request = new Request("http://localhost/api/hermes/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ event: "connection.ready" }),
    });

    const response = await POST(request);

    expect(response.status).toBe(422);
  });
});
