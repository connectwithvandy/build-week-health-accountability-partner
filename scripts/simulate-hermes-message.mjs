const adapterUrl =
  process.env.TED_HERMES_ADAPTER_URL ??
  "http://localhost:3000/api/hermes/messages";

const text = process.argv.slice(2).join(" ") || "Okay Ted, let's do this 🫡";

const payload = {
  event: "message.received",
  message: {
    id: `local-${Date.now()}`,
    from: "919999999999",
    timestamp: new Date().toISOString(),
    text,
  },
};

try {
  const response = await fetch(adapterUrl, {
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
  console.error(
    `Simulator failed. Is npm run dev running?\n${error.message}`,
  );
  process.exitCode = 1;
}
