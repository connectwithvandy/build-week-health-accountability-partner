import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

/**
 * Exactly one variable is lifted out of `.env.local`, not the whole file.
 * `__tests__/landing-page.test.ts` compares Ted's number in the static landing
 * page against the number the rest of the product is configured with, and that
 * check is only real if the test can see the configured value.
 *
 * The rest of `.env.local` is secrets, and the test process has no business
 * holding them — the same reason the root `conftest.py` drops inherited Convex
 * credentials before the Python tests import anything. CI has no `.env.local`,
 * so there the variable is simply absent and the test says so.
 */
const configured = loadEnv("test", process.cwd(), "");
const testEnv: Record<string, string> = {};

if (configured.NEXT_PUBLIC_TED_WHATSAPP_NUMBER) {
  testEnv.NEXT_PUBLIC_TED_WHATSAPP_NUMBER =
    configured.NEXT_PUBLIC_TED_WHATSAPP_NUMBER;
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    env: testEnv,
  },
});
