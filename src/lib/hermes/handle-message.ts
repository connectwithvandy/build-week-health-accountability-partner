import { FIRST_REPLY } from "@/lib/coach/ted-personality";

export { FIRST_REPLY } from "@/lib/coach/ted-personality";

export type HandledHermesMessage = {
  messageId: string;
  chatId: string;
  from: string;
  text: string;
  reply: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function handleHermesMessage(
  payload: unknown,
): HandledHermesMessage | null {
  if (!isRecord(payload)) return null;

  if (
    typeof payload.messageId === "string" &&
    typeof payload.chatId === "string" &&
    typeof payload.senderId === "string" &&
    typeof payload.body === "string" &&
    payload.body.trim()
  ) {
    return {
      messageId: payload.messageId,
      chatId: payload.chatId,
      from: payload.senderId,
      text: payload.body.trim(),
      reply: FIRST_REPLY,
    };
  }

  if (payload.event !== "message.received") return null;

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
    chatId: message.from,
    from: message.from,
    text: message.text.trim(),
    reply: FIRST_REPLY,
  };
}
