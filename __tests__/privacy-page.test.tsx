import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPage from "@/app/privacy/page";

describe("PrivacyPage", () => {
  it("answers the four required privacy questions", () => {
    render(<PrivacyPage />);

    expect(screen.getByRole("heading", { name: /what is stored/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /who can see it/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /how long it is kept/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /how to delete it/i })).toBeInTheDocument();
    expect(screen.getByText(/delete my data/i)).toBeInTheDocument();
  });
});
