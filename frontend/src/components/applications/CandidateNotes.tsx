import { LockKeyhole, Plus, UsersRound } from "lucide-react";
import { type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { formatPacificDateTime } from "../../format";
import type { CommitteeNote } from "../../types";

const MAX_PRIVATE_NOTE_HEIGHT_PX = 150;
type NotesTab = "private" | "committee";
let lastOpenTab: NotesTab = "private";

export function CandidateNotes(props: {
  applicationId: number;
  privateNote: string;
  committeeNotes: CommitteeNote[];
  onSavePrivateNote: (id: number, note: string) => Promise<boolean>;
  onAddCommitteeNote: (id: number, body: string) => Promise<boolean>;
  onUpdateCommitteeNote: (id: number, noteId: number, body: string) => Promise<boolean>;
  onDeleteCommitteeNote: (id: number, noteId: number) => Promise<boolean>;
  readOnly?: boolean;
}) {
  const [activeTab, setActiveTab] = useState<NotesTab>(lastOpenTab);
  const [privateNote, setPrivateNote] = useState(props.privateNote);
  const [privateStatus, setPrivateStatus] = useState<"saved" | "saving" | "error">("saved");
  const [newNote, setNewNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingBody, setEditingBody] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [committeeBusy, setCommitteeBusy] = useState(false);
  const [committeeError, setCommitteeError] = useState<string | null>(null);
  const privateNoteRef = useRef<HTMLTextAreaElement>(null);
  const pendingPrivateSave = useRef<ReturnType<typeof setTimeout> | null>(null);
  const privateRevision = useRef(0);
  const savedPrivateNote = useRef(props.privateNote);

  useEffect(
    () => () => {
      if (pendingPrivateSave.current !== null) clearTimeout(pendingPrivateSave.current);
    },
    [],
  );

  useLayoutEffect(() => {
    const textarea = privateNoteRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_PRIVATE_NOTE_HEIGHT_PX)}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_PRIVATE_NOTE_HEIGHT_PX ? "auto" : "hidden";
  }, [privateNote, activeTab]);

  function persistPrivateNote(note: string, revision: number) {
    if (props.readOnly || note === savedPrivateNote.current) {
      if (revision === privateRevision.current) setPrivateStatus("saved");
      return;
    }
    setPrivateStatus("saving");
    props.onSavePrivateNote(props.applicationId, note).then((saved) => {
      if (revision !== privateRevision.current) return;
      if (saved) {
        savedPrivateNote.current = note;
        setPrivateStatus("saved");
      } else {
        setPrivateStatus("error");
      }
    });
  }

  function updatePrivateNote(note: string) {
    setPrivateNote(note);
    const revision = (privateRevision.current += 1);
    if (pendingPrivateSave.current !== null) clearTimeout(pendingPrivateSave.current);
    setPrivateStatus("saving");
    pendingPrivateSave.current = setTimeout(() => persistPrivateNote(note, revision), 600);
  }

  function flushPrivateNote() {
    if (pendingPrivateSave.current !== null) {
      clearTimeout(pendingPrivateSave.current);
      pendingPrivateSave.current = null;
    }
    persistPrivateNote(privateNote, privateRevision.current);
  }

  function selectTab(tab: NotesTab) {
    if (activeTab === "private") flushPrivateNote();
    lastOpenTab = tab;
    setActiveTab(tab);
    setCommitteeError(null);
  }

  async function addCommitteeNote(event: FormEvent) {
    event.preventDefault();
    const body = newNote.trim();
    if (!body) return;
    setCommitteeBusy(true);
    setCommitteeError(null);
    const saved = await props.onAddCommitteeNote(props.applicationId, body);
    setCommitteeBusy(false);
    if (saved) {
      setNewNote("");
      setAdding(false);
    } else {
      setCommitteeError("Could not add the note. Try again.");
    }
  }

  async function updateCommitteeNote(event: FormEvent, noteId: number) {
    event.preventDefault();
    const body = editingBody.trim();
    if (!body) return;
    setCommitteeBusy(true);
    setCommitteeError(null);
    const saved = await props.onUpdateCommitteeNote(props.applicationId, noteId, body);
    setCommitteeBusy(false);
    if (saved) {
      setEditingId(null);
      setEditingBody("");
    } else {
      setCommitteeError("Could not update the note. Try again.");
    }
  }

  async function deleteCommitteeNote(noteId: number) {
    setCommitteeBusy(true);
    setCommitteeError(null);
    const deleted = await props.onDeleteCommitteeNote(props.applicationId, noteId);
    setCommitteeBusy(false);
    if (deleted) {
      setDeletingId(null);
    } else {
      setCommitteeError("Could not delete the note. Try again.");
    }
  }

  return (
    <section className="notes-panel">
      <div className="notes-heading">
        <h4>Notes</h4>
        <div className="notes-tabs no-print" role="tablist" aria-label="Applicant notes">
          <button
            type="button"
            className="notes-tab"
            id={`private-notes-tab-${props.applicationId}`}
            role="tab"
            aria-selected={activeTab === "private"}
            aria-controls={`private-notes-panel-${props.applicationId}`}
            onClick={() => selectTab("private")}
          >
            My notes
          </button>
          <button
            type="button"
            className="notes-tab"
            id={`committee-notes-tab-${props.applicationId}`}
            role="tab"
            aria-selected={activeTab === "committee"}
            aria-controls={`committee-notes-panel-${props.applicationId}`}
            onClick={() => selectTab("committee")}
          >
            Committee notes
            <span className="notes-count">{props.committeeNotes.length}</span>
          </button>
        </div>
        {activeTab === "committee" && !props.readOnly && !adding ? (
          <button type="button" className="add-committee-note no-print" onClick={() => setAdding(true)}>
            <Plus size={14} /> Add committee note
          </button>
        ) : null}
      </div>

      <div className="notes-interactive no-print">
        {activeTab === "private" ? (
          <div
            id={`private-notes-panel-${props.applicationId}`}
            role="tabpanel"
            aria-labelledby={`private-notes-tab-${props.applicationId}`}
            className="notes-tab-panel"
          >
            <p className="notes-visibility"><LockKeyhole size={13} /> Only you can see this.</p>
            {props.readOnly ? (
              <div className="notes-read-only-body">{privateNote || "No private note."}</div>
            ) : (
              <>
                <textarea
                  ref={privateNoteRef}
                  aria-label="My private notes"
                  value={privateNote}
                  onChange={(event) => updatePrivateNote(event.target.value)}
                  onBlur={flushPrivateNote}
                  placeholder="Add a private note about this applicant…"
                  rows={2}
                />
                <p className={`notes-save-status is-${privateStatus}`} aria-live="polite">
                  {privateStatus === "saving"
                    ? "Saving…"
                    : privateStatus === "error"
                      ? "Could not save — try again."
                      : privateNote
                        ? "Saved"
                        : ""}
                </p>
              </>
            )}
          </div>
        ) : (
          <div
            id={`committee-notes-panel-${props.applicationId}`}
            role="tabpanel"
            aria-labelledby={`committee-notes-tab-${props.applicationId}`}
            className="notes-tab-panel committee-notes-panel"
          >
            <p className="notes-visibility"><UsersRound size={14} /> Visible to all committee members.</p>
            <div className="committee-notes-list">
              {props.committeeNotes.length === 0 ? (
                <p className="committee-notes-empty">No committee notes yet.</p>
              ) : props.committeeNotes.map((note) => (
                <article className="committee-note" key={note.id}>
                  <div className="committee-note-meta">
                    <strong>{note.authorName}</strong>
                    <div className="committee-note-meta-trailing">
                      <span>
                        {formatPacificDateTime(note.createdAt)}
                        {note.updatedAt !== note.createdAt ? " · Edited" : ""}
                      </span>
                      {note.editableByMe && editingId !== note.id && !props.readOnly && deletingId !== note.id ? (
                        <div className="committee-note-actions">
                          <button type="button" onClick={() => { setEditingId(note.id); setEditingBody(note.body); }}>Edit</button>
                          <button type="button" onClick={() => setDeletingId(note.id)}>Delete</button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {editingId === note.id ? (
                    <form onSubmit={(event) => void updateCommitteeNote(event, note.id)}>
                      <textarea
                        aria-label={`Edit note by ${note.authorName}`}
                        value={editingBody}
                        onChange={(event) => setEditingBody(event.target.value)}
                        rows={3}
                        autoFocus
                      />
                      <div className="committee-note-form-actions">
                        <button type="button" onClick={() => setEditingId(null)}>Cancel</button>
                        <button type="submit" className="is-primary" disabled={committeeBusy || !editingBody.trim()}>Save</button>
                      </div>
                    </form>
                  ) : (
                    <p className="committee-note-body">{note.body}</p>
                  )}
                  {note.editableByMe && editingId !== note.id && !props.readOnly && deletingId === note.id ? (
                      <div className="committee-note-confirm">
                        <span>Delete this note?</span>
                        <button type="button" onClick={() => setDeletingId(null)}>Keep</button>
                        <button type="button" className="is-danger" disabled={committeeBusy} onClick={() => void deleteCommitteeNote(note.id)}>Delete</button>
                      </div>
                  ) : null}
                </article>
              ))}
            </div>
            {!props.readOnly && adding ? (
                <form className="committee-note-composer" onSubmit={(event) => void addCommitteeNote(event)}>
                  <textarea
                    aria-label="New committee note"
                    value={newNote}
                    onChange={(event) => setNewNote(event.target.value)}
                    placeholder="Add a note for the committee…"
                    rows={3}
                    autoFocus
                  />
                  <div className="committee-note-form-actions">
                    <button type="button" onClick={() => { setAdding(false); setNewNote(""); }}>Cancel</button>
                    <button type="submit" className="is-primary" disabled={committeeBusy || !newNote.trim()}>Add note</button>
                  </div>
                </form>
            ) : null}
            {committeeError ? <p className="committee-note-error" role="alert">{committeeError}</p> : null}
          </div>
        )}
      </div>
      {privateNote || props.committeeNotes.length > 0 ? (
        <div className="notes-print">
          {privateNote ? (
            <section>
              <h5>My notes</h5>
              <p>{privateNote}</p>
            </section>
          ) : null}
          {props.committeeNotes.length > 0 ? (
            <section>
              <h5>Committee notes</h5>
              {props.committeeNotes.map((note) => (
                <article key={note.id}>
                  <strong>{note.authorName}</strong>
                  <span>{formatPacificDateTime(note.createdAt)}</span>
                  <p>{note.body}</p>
                </article>
              ))}
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
