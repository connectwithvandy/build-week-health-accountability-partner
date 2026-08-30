import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const FIRST_REPLY =
  "Chalo, scene set karte hain 😌 First things first: what are we trying to fix?";

let cachedPersonality: string | undefined;

export async function loadTedPersonality(): Promise<string> {
  if (cachedPersonality) return cachedPersonality;

  const personality = await readFile(
    join(process.cwd(), "TED_PERSONALITY.md"),
    "utf8",
  );

  if (!personality.trim()) {
    throw new Error("TED_PERSONALITY.md is empty.");
  }

  cachedPersonality = personality;
  return personality;
}
