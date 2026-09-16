import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `layout.tsx` wraps every App Router page in this provider, so whatever it
 * does on a partial configuration, it does to `/privacy` and `/metrics` too.
 * It used to throw at module scope, which took both pages down over a variable
 * neither of them needs.
 *
 * The env var is read when the module is first imported, so each test resets
 * the module registry and imports fresh rather than trying to change it after
 * the fact.
 */

const ORIGINAL = process.env.NEXT_PUBLIC_CONVEX_URL;

async function providerWith(url: string | undefined) {
  vi.resetModules();
  if (url === undefined) delete process.env.NEXT_PUBLIC_CONVEX_URL;
  else process.env.NEXT_PUBLIC_CONVEX_URL = url;
  return (await import("@/app/ConvexClientProvider")).ConvexClientProvider;
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.NEXT_PUBLIC_CONVEX_URL;
  else process.env.NEXT_PUBLIC_CONVEX_URL = ORIGINAL;
});

describe("the Convex provider that wraps every page", () => {
  it("still renders the page when the Convex URL is missing", async () => {
    const ConvexClientProvider = await providerWith(undefined);

    // The behaviour that matters: /privacy has no Convex in it, and a missing
    // variable must not be the reason nobody can read the privacy policy.
    render(
      <ConvexClientProvider>
        <p>the privacy page</p>
      </ConvexClientProvider>,
    );

    expect(screen.getByText("the privacy page")).toBeInTheDocument();
  });

  it("does not throw while being imported without configuration", async () => {
    // Importing is the moment it used to fail, before any component rendered,
    // which is why the whole tree went down rather than one subtree.
    await expect(providerWith(undefined)).resolves.toBeTypeOf("function");
  });

  it("renders the page when the Convex URL is present", async () => {
    const ConvexClientProvider = await providerWith("https://example.convex.cloud");

    render(
      <ConvexClientProvider>
        <p>the privacy page</p>
      </ConvexClientProvider>,
    );

    expect(screen.getByText("the privacy page")).toBeInTheDocument();
  });
});
