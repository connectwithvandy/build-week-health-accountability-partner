import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

const openingMessage = "Okay Ted, let's do this!";

describe("Home", () => {
  it("explains Ted's core promise", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /your day slipped away/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/remembers your meals, movement, water/i)).toBeInTheDocument();
    expect(screen.getByText(/one useful thing you can still do today/i)).toBeInTheDocument();
    expect(screen.getByText(/message ted → tell it what you ate and did/i)).toBeInTheDocument();
    expect(screen.getByText(/7:42 pm/i)).toBeInTheDocument();
    expect(screen.getByText(/not medical advice/i)).toBeInTheDocument();
    expect(screen.getByText(/stores your profile, messages, plans, logs/i)).toBeInTheDocument();
    expect(screen.getByText(/services that run it process this information/i)).toBeInTheDocument();
    expect(screen.getByText(/delete my data/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
  });

  it("repeats the WhatsApp action with the agreed opening message", () => {
    render(<Home />);

    const links = screen.getAllByRole("link", { name: /message ted/i });
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(openingMessage)).not.toBeInTheDocument();

    for (const link of links) {
      expect(link).toHaveTextContent(/free during beta/i);
      const href = link.getAttribute("href");
      expect(href).toContain("https://wa.me/");
      expect(decodeURIComponent(href ?? "")).toContain(openingMessage);
      expect(decodeURIComponent(href ?? "")).not.toContain("🫡");
    }
  });
});
