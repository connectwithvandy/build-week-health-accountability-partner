const webhookUrl =
  process.env.TED_WEBHOOK_URL ?? "http://localhost:3000/api/whatsapp/webhook";

const text = process.argv.slice(2).join(" ") || "Okay, let’s do this 🫡";

const payload = {
  object: "whatsapp_business_account",
  entry: [
    {
      id: "local-business-account",
      changes: [
        {
          field: "messages",
          value: {
            messaging_product: "whatsapp",
            metadata: {
              display_phone_number: "15550000000",
              phone_number_id: "local-phone-number",
            },
            contacts: [{ profile: { name: "Local Tester" }, wa_id: "919999999999" }],
            messages: [
              {
                from: "919999999999",
                id: `local-${Date.now()}`,
                timestamp: String(Math.floor(Date.now() / 1000)),
                type: "text",
                text: { body: text },
              },
            ],
          },
        },
      ],
    },
  ],
};

try {
  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();

  if (!response.ok) {
    throw new Error(`${response.status}: ${JSON.stringify(result)}`);
  }

  console.log(`Sent: ${result.message.text}`);
  console.log(`Ted: ${result.message.reply}`);
} catch (error) {
  console.error(`Simulator failed. Is npm run dev running?\n${error.message}`);
  process.exitCode = 1;
}
