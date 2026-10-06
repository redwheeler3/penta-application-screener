import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommitteeNote } from "../../types";
import { usePrivateNotes } from "../../hooks/usePrivateNotes";
import { CandidateNotes } from "./CandidateNotes";

const api = vi.hoisted(() => ({
  savePrivateNote: vi.fn<ReturnType<typeof import("../../api/applications").createApi>["savePrivateNote"]>(),
}));

vi.mock("../../api/applications", () => ({
  createApi: () => api,
}));
afterEach(() => vi.useRealTimers());

const committeeNote: CommitteeNote = {
  id: 7,
  authorName: "Committee Member",
  body: "Reference call completed.",
  createdAt: "2026-09-23T04:35:14Z",
  updatedAt: "2026-09-23T04:35:14Z",
  editableByMe: true,
};

function renderNotes(overrides: Partial<ComponentProps<typeof CandidateNotes>> & {
  onSavePrivateNote?: (id: number, note: string) => Promise<boolean>;
} = {}) {
  const callbacks = {
    onSavePrivateNote: vi.fn().mockResolvedValue(true),
    onAddCommitteeNote: vi.fn().mockResolvedValue("saved"),
    onUpdateCommitteeNote: vi.fn().mockResolvedValue(true),
    onDeleteCommitteeNote: vi.fn().mockResolvedValue(true),
  };
  const { onSavePrivateNote = callbacks.onSavePrivateNote, ...noteProps } = overrides;
  vi.mocked(api.savePrivateNote).mockImplementation(async (id, _opening, body) =>
    new Response(null, { status: await onSavePrivateNote(id, body) ? 200 : 409 }));
  function Workspace() {
    const notes = usePrivateNotes({ onSaved: vi.fn(), onError: vi.fn() });
    return (
    <CandidateNotes
      applicationId={42}
      privateNote="Private context"
      committeeNotes={[committeeNote]}
      {...callbacks}
      {...noteProps}
      privateNoteEditor={overrides.readOnly ? null : notes.editor(42, 1, "Private context")}
    />
    );
  }
  render(<Workspace />);
  return callbacks;
}

describe("CandidateNotes", () => {
  it("updates private text immediately without rerendering the account workspace on each keystroke", () => {
    const ownerRendered = vi.fn();
    function Workspace() {
      ownerRendered();
      const notes = usePrivateNotes({ onSaved: vi.fn(), onError: vi.fn() });
      return <CandidateNotes
        applicationId={42} privateNote="Private context" committeeNotes={[]}
        privateNoteEditor={notes.editor(42, 1, "Private context")}
        onAddCommitteeNote={vi.fn()} onUpdateCommitteeNote={vi.fn()} onDeleteCommitteeNote={vi.fn()}
      />;
    }
    render(<Workspace />);
    fireEvent.click(screen.getByRole("tab", { name: "My notes" }));
    const rendersBeforeTyping = ownerRendered.mock.calls.length;
    const input = screen.getByRole("textbox", { name: "My private notes" });
    fireEvent.change(input, { target: { value: "One" } });
    fireEvent.change(input, { target: { value: "One two" } });
    expect(input).toHaveValue("One two");
    expect(ownerRendered).toHaveBeenCalledTimes(rendersBeforeTyping);
  });

  it("preserves unsaved text when programmatic navigation disposes the editor without blur", async () => {
    vi.useFakeTimers();
    vi.mocked(api.savePrivateNote).mockResolvedValueOnce(new Response(null, { status: 409 }))
      .mockResolvedValueOnce(new Response(null));
    function Workspace({ visible, openingId }: { visible: boolean; openingId: number }) {
      const notes = usePrivateNotes({ onSaved: vi.fn(), onError: vi.fn() });
      return visible ? <CandidateNotes
        applicationId={42} privateNote="Private context" committeeNotes={[]}
        privateNoteEditor={notes.editor(42, openingId, "Private context")}
        onAddCommitteeNote={vi.fn()} onUpdateCommitteeNote={vi.fn()} onDeleteCommitteeNote={vi.fn()}
      /> : <p>Another view</p>;
    }
    const view = render(<Workspace visible openingId={1} />);
    fireEvent.click(screen.getByRole("tab", { name: "My notes" }));
    fireEvent.change(screen.getByRole("textbox", { name: "My private notes" }), { target: { value: "Keep this draft" } });
    view.rerender(<Workspace visible={false} openingId={2} />);
    expect(screen.getByText("Another view")).toBeInTheDocument();
    expect(api.savePrivateNote).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(api.savePrivateNote).toHaveBeenCalledExactlyOnceWith(42, 1, "Keep this draft");
    view.rerender(<Workspace visible openingId={2} />);
    expect(screen.getByRole("textbox", { name: "My private notes" })).toHaveValue("Keep this draft");
    expect(screen.getByText("Could not save — try again.")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Retry save" })));
    expect(api.savePrivateNote).toHaveBeenLastCalledWith(42, 2, "Keep this draft");
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

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

  it("skips intermediate private drafts queued behind a pending save", async () => {
    const first = deferred<boolean>();
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true);
    renderNotes({ onSavePrivateNote: save });
    const input = screen.getByRole("textbox", { name: "My private notes" });
    fireEvent.change(input, { target: { value: "First" } });
    fireEvent.blur(input);
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    for (const value of ["Intermediate", "Newest"]) {
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);
    }
    await act(async () => { first.resolve(true); });
    expect(save.mock.calls).toEqual([[42, "First"], [42, "Newest"]]);
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it.each(["add", "edit"])("retains a newer committee draft after a pending %s", async (mode) => {
    const pending = deferred<boolean>();
    renderNotes({ onAddCommitteeNote: async () => await pending.promise ? "saved" : "unconfirmed", onUpdateCommitteeNote: () => pending.promise });
    fireEvent.click(screen.getByRole("tab", { name: /Committee notes/ }));
    fireEvent.click(screen.getByRole("button", { name: mode === "add" ? "Add committee note" : "Edit" }));
    const editor = screen.getByRole("textbox", { name: mode === "add" ? "New committee note" : "Edit note by Committee Member" });
    fireEvent.change(editor, { target: { value: "Submitted" } });
    fireEvent.click(screen.getByRole("button", { name: mode === "add" ? "Add note" : "Save" }));
    fireEvent.change(editor, { target: { value: "Typed while saving" } });
    await act(async () => { pending.resolve(true); });
    expect(editor).toHaveValue("Typed while saving");
    expect(screen.getByRole("button", { name: mode === "add" ? "Add note" : "Save" })).toBeEnabled();
  });

  it("keeps private autosave and committee publishing visibly separate", async () => {
    const user = userEvent.setup();
    const callbacks = renderNotes();

    await user.click(screen.getByRole("tab", { name: "My notes" }));
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
      expect(callbacks.onAddCommitteeNote).toHaveBeenCalledWith(42, "Share this", expect.any(String));
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


it("retries the exact unconfirmed creation before publishing a newer draft", async () => {
  const add = vi.fn().mockResolvedValueOnce("unconfirmed").mockResolvedValue("saved");
  renderNotes({ onAddCommitteeNote: add });
  fireEvent.click(screen.getByRole("tab", { name: /Committee notes/ }));
  fireEvent.click(screen.getByRole("button", { name: "Add committee note" }));
  const editor = screen.getByRole("textbox", { name: "New committee note" });
  fireEvent.change(editor, { target: { value: "First" } });
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await screen.findByText(/note is unconfirmed/);
  fireEvent.change(editor, { target: { value: "Next" } });
  fireEvent.click(screen.getByRole("button", { name: "Retry note" }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(2));
  expect(add.mock.calls[1]).toEqual(add.mock.calls[0]);
  expect(editor).toHaveValue("Next");
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(3));
  expect(add.mock.calls[2][1]).toBe("Next");
  expect(add.mock.calls[2][2]).not.toBe(add.mock.calls[0][2]);
});


it("lets a definite refusal be corrected without replaying the rejected body", async () => {
  const add = vi.fn().mockResolvedValueOnce("rejected").mockResolvedValue("saved");
  renderNotes({ onAddCommitteeNote: add });
  fireEvent.click(screen.getByRole("tab", { name: /Committee notes/ }));
  fireEvent.click(screen.getByRole("button", { name: "Add committee note" }));
  const editor = screen.getByRole("textbox", { name: "New committee note" });
  fireEvent.change(editor, { target: { value: "Rejected draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await screen.findByText(/Review the draft/);
  fireEvent.change(editor, { target: { value: "Corrected draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(2));
  expect(add.mock.calls[1][1]).toBe("Corrected draft");
  expect(add.mock.calls[1][2]).not.toBe(add.mock.calls[0][2]);
});
