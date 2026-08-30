export type HandledWhatsAppMessage = {
  messageId: string;
  from: string;
  text: string;
  reply: string;
};

export const FIRST_REPLY =
  "Chalo, scene set karte hain 😌 First things first: what are we trying to fix?";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function handleWhatsAppMessage(
  payload: unknown,
): HandledWhatsAppMessage | null {
  if (!isRecord(payload) || !Array.isArray(payload.entry)) return null;

  const entry = payload.entry[0];
  if (!isRecord(entry) || !Array.isArray(entry.changes)) return null;

  const change = entry.changes[0];
  if (!isRecord(change) || !isRecord(change.value)) return null;

  const messages = change.value.messages;
  if (!Array.isArray(messages) || !isRecord(messages[0])) return null;

  const message = messages[0];
  const text = message.text;

  if (
    message.type !== "text" ||
    typeof message.id !== "string" ||
    typeof message.from !== "string" ||
    !isRecord(text) ||
    typeof text.body !== "string" ||
    !text.body.trim()
  ) {
    return null;
  }

  return {
    messageId: message.id,
    from: message.from,
    text: text.body.trim(),
    reply: FIRST_REPLY,
  };
}
