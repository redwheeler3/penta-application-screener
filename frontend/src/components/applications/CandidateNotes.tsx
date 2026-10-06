import { LockKeyhole, Plus, UsersRound } from "lucide-react";
import { type FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { formatPacificDateTime } from "../../format";
import type { CommitteeNote } from "../../types";
import type { PrivateNoteEditor } from "../../hooks/usePrivateNotes";

const MAX_PRIVATE_NOTE_HEIGHT_PX = 150;
type NotesTab = "private" | "committee";
let lastOpenTab: NotesTab = "private";
const noSubscription = () => () => {};

export function CandidateNotes(props: {
  applicationId: number;
  privateNote: string;
  committeeNotes: CommitteeNote[];
  privateNoteEditor: PrivateNoteEditor | null;
  onAddCommitteeNote: (id: number, body: string, creationKey: string) => Promise<boolean>;
  onUpdateCommitteeNote: (id: number, noteId: number, body: string) => Promise<boolean>;
  onDeleteCommitteeNote: (id: number, noteId: number) => Promise<boolean>;
  readOnly?: boolean;
}) {
  const [activeTab, setActiveTab] = useState<NotesTab>(lastOpenTab);
  const readOnlyNote = useMemo(() => ({ body: props.privateNote, status: "saved" as const }), [props.privateNote]);
  const privateDraft = useSyncExternalStore(
    props.privateNoteEditor?.subscribe ?? noSubscription,
    props.privateNoteEditor?.getSnapshot ?? (() => readOnlyNote),
  );
  const privateNote = privateDraft.body;
  const privateStatus = privateDraft.status;
  const blockPrivateDraft = props.privateNoteEditor?.block;
  useEffect(() => { if (props.readOnly) blockPrivateDraft?.(); }, [props.readOnly, blockPrivateDraft]);
  const [newNote, setNewNote] = useState("");
  const creationAttempt = useRef<{ key: string; body: string; draft: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingBody, setEditingBody] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [committeeBusy, setCommitteeBusy] = useState(false);
  const [committeeError, setCommitteeError] = useState<string | null>(null);
  const privateNoteRef = useRef<HTMLTextAreaElement>(null);
  const editorRef = useRef({ adding, newNote, editingId, editingBody });
  editorRef.current = { adding, newNote, editingId, editingBody };

  useLayoutEffect(() => {
    const textarea = privateNoteRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_PRIVATE_NOTE_HEIGHT_PX)}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_PRIVATE_NOTE_HEIGHT_PX ? "auto" : "hidden";
  }, [privateNote, activeTab]);

  function flushPrivateNote() {
    if (!props.readOnly) props.privateNoteEditor?.flush();
  }

  function selectTab(tab: NotesTab) {
    if (activeTab === "private") flushPrivateNote();
    lastOpenTab = tab;
    setActiveTab(tab);
    setCommitteeError(null);
  }

  async function addCommitteeNote(event: FormEvent) {
    event.preventDefault();
    if (committeeBusy || props.readOnly) return;
    const attempt = creationAttempt.current ?? { key: crypto.randomUUID(), body: newNote.trim(), draft: newNote };
    if (!attempt.body) return;
    creationAttempt.current = attempt;
    const submitted = attempt.draft;
    setCommitteeBusy(true);
    setCommitteeError(null);
    const saved = await props.onAddCommitteeNote(props.applicationId, attempt.body, attempt.key);
    setCommitteeBusy(false);
    if (saved) creationAttempt.current = null;
    if (saved && editorRef.current.adding && editorRef.current.newNote === submitted) {
      setNewNote("");
      setAdding(false);
    } else if (!saved) {
      setCommitteeError("The note is unconfirmed. Retry to confirm it before adding another.");
    }
  }

  async function updateCommitteeNote(event: FormEvent, noteId: number) {
    event.preventDefault();
    const body = editingBody.trim();
    if (!body) return;
    const submitted = editingBody;
    setCommitteeBusy(true);
    setCommitteeError(null);
    const saved = await props.onUpdateCommitteeNote(props.applicationId, noteId, body);
    setCommitteeBusy(false);
    if (saved && editorRef.current.editingId === noteId && editorRef.current.editingBody === submitted) {
      setEditingId(null);
      setEditingBody("");
    } else if (!saved) {
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
            {(props.readOnly && privateStatus === "saved") || !props.privateNoteEditor ? (
              <div className="notes-read-only-body">{privateNote || "No private note."}</div>
            ) : (
              <>
                <textarea
                  ref={privateNoteRef}
                  aria-label="My private notes"
                  value={privateNote}
                  readOnly={props.readOnly || privateStatus === "blocked"}
                  onChange={(event) => props.privateNoteEditor?.change(event.target.value)}
                  onBlur={flushPrivateNote}
                  placeholder="Add a private note about this applicant…"
                  rows={2}
                />
                <p className={`notes-save-status is-${privateStatus}`} aria-live="polite">
                  {privateStatus === "blocked"
                    ? "Notes can no longer be saved for this application. Your draft is available below; select and copy it before discarding."
                    : privateStatus === "saving"
                    ? "Saving…"
                    : privateStatus === "error"
                      ? "Could not save — try again."
                      : privateNote
                        ? "Saved"
                        : ""}
                </p>
                {privateStatus === "error" ? (
                  <button type="button" onClick={flushPrivateNote}>Retry save</button>
                ) : null}
                {privateStatus === "blocked" ? (
                  <button type="button" onClick={() => props.privateNoteEditor?.discard()}>Discard unsaved draft</button>
                ) : null}
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
                        readOnly={props.readOnly}
                        onChange={(event) => setEditingBody(event.target.value)}
                        rows={3}
                        autoFocus
                      />
                      <div className="committee-note-form-actions">
                        <button type="button" onClick={() => setEditingId(null)}>Cancel</button>
                        {!props.readOnly ? <button type="submit" className="is-primary" disabled={committeeBusy || !editingBody.trim()}>Save</button> : null}
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
            {adding ? (
                <form className="committee-note-composer" onSubmit={(event) => void addCommitteeNote(event)}>
                  <textarea
                    aria-label="New committee note"
                    value={newNote}
                    readOnly={props.readOnly}
                    onChange={(event) => setNewNote(event.target.value)}
                    placeholder="Add a note for the committee…"
                    rows={3}
                    autoFocus
                  />
                  <div className="committee-note-form-actions">
                    <button type="button" disabled={creationAttempt.current !== null} onClick={() => { setAdding(false); setNewNote(""); }}>Cancel</button>
                    {!props.readOnly ? <button type="submit" className="is-primary" disabled={committeeBusy || (!creationAttempt.current && !newNote.trim())}>{creationAttempt.current ? "Retry note" : "Add note"}</button> : null}
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
