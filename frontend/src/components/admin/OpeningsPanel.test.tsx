import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpeningsPanel } from "./OpeningsPanel";

vi.mock("../../api/openings", () => ({
  fetchOpenings: vi.fn().mockResolvedValue([]),
}));

vi.mock("./DirectSelectionOpeningForm", () => ({
  DirectSelectionOpeningForm: (props: { onCancel: () => void }) => (
    <section>
      <h4>Direct selection</h4>
      <button type="button" onClick={props.onCancel}>Cancel direct selection</button>
    </section>
  ),
}));

const props = {
  onError: vi.fn(),
  onPoolChanged: vi.fn(),
  onOpenApplicant: vi.fn(),
  onOpenRetainedApplicant: vi.fn(),
};

describe("OpeningsPanel modes", () => {
  it("enters and leaves the new-opening form as one exclusive mode", async () => {
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "New opening" }));
    expect(screen.getByRole("heading", { name: "New opening" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fill from previous applicants" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "New opening" })).toBeInTheDocument();
  });

  it("keeps direct selection mutually exclusive with the opening form", async () => {
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Fill from previous applicants" }));
    expect(screen.getByRole("heading", { name: "Direct selection" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "New opening" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel direct selection" }));
    expect(screen.getByRole("button", { name: "New opening" })).toBeInTheDocument();
  });
});
