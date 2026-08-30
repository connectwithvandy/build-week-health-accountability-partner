export type HandledHermesMessage = {
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

export function handleHermesMessage(
  payload: unknown,
): HandledHermesMessage | null {
  if (!isRecord(payload) || payload.event !== "message.received") return null;

  const message = payload.message;

  if (
    !isRecord(message) ||
    typeof message.id !== "string" ||
    typeof message.from !== "string" ||
    typeof message.text !== "string" ||
    !message.text.trim()
  ) {
    return null;
  }

  return {
    messageId: message.id,
    from: message.from,
    text: message.text.trim(),
    reply: FIRST_REPLY,
  };
}
