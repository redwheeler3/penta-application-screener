import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { CommitteeNote } from "../../types";
import { deferred } from "../../testSupport";
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
  it("queues a revert behind an in-flight save before showing Saved", async () => {
    const first = deferred<boolean>();
    const reverted = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(reverted.promise);
    renderNotes({ onSavePrivateNote: save });
    const input = screen.getByRole("textbox", { name: "My private notes" });
    fireEvent.change(input, { target: { value: "Changed" } });
    fireEvent.blur(input);
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    fireEvent.change(input, { target: { value: "Private context" } });
    fireEvent.blur(input);
    expect(save).toHaveBeenCalledOnce();
    await act(async () => { first.resolve(true); });
    expect(save).toHaveBeenLastCalledWith(42, "Private context");
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    await act(async () => { reverted.resolve(true); });
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(input).toHaveValue("Private context");
  });

  it("serializes different note edits and deduplicates repeated blur saves", async () => {
    const first = deferred<boolean>();
    const last = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(last.promise);
    renderNotes({ onSavePrivateNote: save });
    const input = screen.getByRole("textbox", { name: "My private notes" });
    fireEvent.change(input, { target: { value: "First edit" } });
    fireEvent.blur(input);
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    fireEvent.change(input, { target: { value: "Last edit" } });
    fireEvent.blur(input);
    fireEvent.blur(input);
    expect(save).toHaveBeenCalledOnce();
    await act(async () => { first.resolve(true); });
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith(42, "Last edit");
    await act(async () => { last.resolve(true); });
    expect(save).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

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
