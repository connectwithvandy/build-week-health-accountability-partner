import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

const openingMessage = "Okay Ted, let's do this 🫡";

describe("Home", () => {
  it("explains Ted's core promise", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /your health day/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /tracking isn’t the hard part/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /whatsapp is the app/i })).toBeInTheDocument();
    expect(screen.getAllByText("7:42").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/not medical advice/i)).toBeInTheDocument();
    expect(screen.getByText(/stores your profile, messages, plans, logs/i)).toBeInTheDocument();
    expect(screen.getByText(/services that run it process this information/i)).toBeInTheDocument();
    expect(screen.getByText(/delete my data/i)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Privacy" }).some((link) => link.getAttribute("href") === "/privacy")).toBe(true);
  });

  it("repeats the WhatsApp action with the agreed opening message", () => {
    render(<Home />);

    const links = screen.getAllByRole("link", { name: /(message ted|whatsapp)/i });
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(openingMessage)).not.toBeInTheDocument();

    for (const link of links) {
      expect(link).toHaveTextContent(/free during beta/i);
      const href = link.getAttribute("href");
      expect(href).toContain("https://wa.me/");
      expect(decodeURIComponent(href ?? "")).toContain(openingMessage);
      expect(decodeURIComponent(href ?? "")).toContain("🫡");
    }
  });
});
