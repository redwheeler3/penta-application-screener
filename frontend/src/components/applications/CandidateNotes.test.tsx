import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { CommitteeNote } from "../../types";
import { CandidateNotes } from "./CandidateNotes";

const committeeNote: CommitteeNote = {
  id: 7,
  authorName: "Committee Member",
  body: "Reference call completed.",
  createdAt: "2026-09-23T04:35:14Z",
  updatedAt: "2026-09-23T04:35:14Z",
  editableByMe: true,
};

function renderNotes(overrides: Partial<ComponentProps<typeof CandidateNotes>> = {}) {
  const callbacks = {
    onSavePrivateNote: vi.fn().mockResolvedValue(true),
    onAddCommitteeNote: vi.fn().mockResolvedValue(true),
    onUpdateCommitteeNote: vi.fn().mockResolvedValue(true),
    onDeleteCommitteeNote: vi.fn().mockResolvedValue(true),
  };
  render(
    <CandidateNotes
      applicationId={42}
      privateNote="Private context"
      committeeNotes={[committeeNote]}
      {...callbacks}
      {...overrides}
    />,
  );
  return callbacks;
}

describe("CandidateNotes", () => {
  it("keeps private autosave and committee publishing visibly separate", async () => {
    const user = userEvent.setup();
    const callbacks = renderNotes();

    expect(screen.getByText("Only you can see this.")).toBeInTheDocument();
    const privateNote = screen.getByRole("textbox", { name: "My private notes" });
    fireEvent.change(privateNote, { target: { value: "Updated private context" } });
    fireEvent.blur(privateNote);
    await waitFor(() => {
      expect(callbacks.onSavePrivateNote).toHaveBeenCalledWith(42, "Updated private context");
    });

    await user.click(screen.getByRole("tab", { name: /Committee notes/ }));
    expect(screen.getByText("Visible to all committee members.")).toBeInTheDocument();
    expect(
      within(screen.getByRole("tabpanel")).getByText("Reference call completed."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add committee note" }));
    await user.type(screen.getByRole("textbox", { name: "New committee note" }), "Share this");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => {
      expect(callbacks.onAddCommitteeNote).toHaveBeenCalledWith(42, "Share this");
    });
  });

  it("offers edit and delete only for an editable committee note", async () => {
    const user = userEvent.setup();
    const callbacks = renderNotes();

    await user.click(screen.getByRole("tab", { name: /Committee notes/ }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const editor = screen.getByRole("textbox", { name: "Edit note by Committee Member" });
    await user.clear(editor);
    await user.type(editor, "Updated shared context");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(callbacks.onUpdateCommitteeNote).toHaveBeenCalledWith(
        42,
        7,
        "Updated shared context",
      );
    });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(callbacks.onDeleteCommitteeNote).toHaveBeenCalledWith(42, 7);
    });
  });
});
