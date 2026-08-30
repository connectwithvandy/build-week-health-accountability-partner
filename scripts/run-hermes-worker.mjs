const DEFAULT_HERMES_URL = "http://127.0.0.1:3000";
const DEFAULT_TED_ADAPTER_URL = "http://127.0.0.1:3001/api/hermes/messages";

export async function processMessagesOnce({
  fetchImpl = fetch,
  hermesUrl = process.env.HERMES_BASE_URL || DEFAULT_HERMES_URL,
  adapterUrl = process.env.TED_HERMES_ADAPTER_URL || DEFAULT_TED_ADAPTER_URL,
  handledIds = new Set(),
} = {}) {
  const incomingResponse = await fetchImpl(`${hermesUrl}/messages`);
  if (!incomingResponse.ok) {
    throw new Error(`Hermes receive failed (${incomingResponse.status}).`);
  }

  const messages = await incomingResponse.json();
  if (!Array.isArray(messages)) {
    throw new Error("Hermes returned an invalid messages response.");
  }

  for (const payload of messages) {
    const messageId = payload?.messageId;
    if (typeof messageId !== "string" || handledIds.has(messageId)) continue;

    const handledResponse = await fetchImpl(adapterUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (handledResponse.status === 422) continue;
    if (!handledResponse.ok) {
      throw new Error(`Ted handler failed (${handledResponse.status}).`);
    }

    const handledResult = await handledResponse.json();
    const handledMessage = handledResult?.message;
    if (!handledMessage?.chatId || !handledMessage?.reply) {
      throw new Error("Ted handler returned an invalid reply.");
    }

    const sendResponse = await fetchImpl(`${hermesUrl}/send`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chatId: handledMessage.chatId,
        message: handledMessage.reply,
        replyTo: handledMessage.messageId,
      }),
    });

    if (!sendResponse.ok) {
      throw new Error(`Hermes send failed (${sendResponse.status}).`);
    }

    handledIds.add(messageId);
    console.log(`Ted replied to Hermes message ${messageId}.`);
  }

  return handledIds;
}

async function run() {
  const handledIds = new Set();
  console.log("Ted's Hermes worker is listening for WhatsApp messages.");

  while (true) {
    try {
      await processMessagesOnce({ handledIds });
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    } catch (error) {
      console.error(`Ted worker error: ${error.message}`);
      await new Promise((resolve) => setTimeout(resolve, 3_000));
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run();
}
