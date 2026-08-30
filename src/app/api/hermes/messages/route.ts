import { handleHermesMessage } from "@/lib/hermes/handle-message";

export async function POST(request: Request) {
  if (process.env.NODE_ENV === "production") {
    return Response.json(
      { error: "The local Hermes adapter is disabled in production." },
      { status: 503 },
    );
  }

  let payload: unknown;

  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON payload." }, { status: 400 });
  }

  const handledMessage = handleHermesMessage(payload);

  if (!handledMessage) {
    return Response.json(
      { error: "No supported Hermes text message was found." },
      { status: 422 },
    );
  }

  return Response.json({ status: "handled", message: handledMessage });
}
