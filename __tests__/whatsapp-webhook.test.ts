import { describe, expect, it } from "vitest";

import { POST } from "@/app/api/whatsapp/webhook/route";
import { FIRST_REPLY } from "@/lib/whatsapp/handle-message";

const textPayload = {
  object: "whatsapp_business_account",
  entry: [
    {
      changes: [
        {
          value: {
            messages: [
              {
                from: "919999999999",
                id: "wamid.local-test",
                timestamp: "1788111000",
                type: "text",
                text: { body: "Okay, let’s do this 🫡" },
              },
            ],
          },
        },
      ],
    },
  ],
};

describe("local WhatsApp webhook", () => {
  it("sends a simulated Meta text event through the message handler", async () => {
    const request = new Request("http://localhost/api/whatsapp/webhook", {
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
        messageId: "wamid.local-test",
        from: "919999999999",
        text: "Okay, let’s do this 🫡",
        reply: FIRST_REPLY,
      },
    });
  });

  it("does not handle payloads without a supported text message", async () => {
    const request = new Request("http://localhost/api/whatsapp/webhook", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ object: "whatsapp_business_account" }),
    });

    const response = await POST(request);

    expect(response.status).toBe(422);
  });
});
