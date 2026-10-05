import { useCallback, useEffect, useReducer, useRef } from "react";

import { savePrivateNote } from "../api/applications";
import { useRequestScope } from "./useRequestScope";

export type PrivateNoteEditor = {
  body: string;
  status: "saved" | "saving" | "error";
  change: (body: string) => void;
  flush: () => void;
};

type Draft = {
  body: string;
  savedBody: string;
  openingId: number;
  revision: number;
  status: PrivateNoteEditor["status"];
  timer: ReturnType<typeof setTimeout> | null;
  queue: Promise<void>;
};

/** Account-owned drafts survive editor/tab/opening changes, in memory only. Each
 * applicant has one ordered writer because private notes belong to the applicant. */
export function usePrivateNotes(options: {
  onSaved: (applicationId: number, body: string) => void;
  onError: (message: string) => void;
}) {
  const drafts = useRef(new Map<number, Draft>());
  const current = useRef(options);
  current.current = options;
  const requests = useRequestScope();
  const suspended = useRef(false);
  const [, notify] = useReducer((revision: number) => revision + 1, 0);

  const flush = useCallback((applicationId: number) => {
    const draft = drafts.current.get(applicationId);
    if (!draft || draft.status === "saved" || suspended.current) return;
    if (draft.timer !== null) clearTimeout(draft.timer);
    draft.timer = null;
    const { body, revision, openingId } = draft;
    const inAccount = requests.capture();
    draft.status = "saving";
    notify();
    draft.queue = draft.queue.then(async () => {
      if (!inAccount() || revision !== draft.revision) return;
      // Compare after preceding writes: reverting during a save still needs a write.
      const needsWrite = body !== draft.savedBody;
      let saved = !needsWrite;
      if (needsWrite) {
        try {
          saved = (await savePrivateNote(applicationId, openingId, body)).ok;
        } catch {
          saved = false;
        }
      }
      if (!inAccount()) return;
      if (saved) {
        draft.savedBody = body;
        if (needsWrite) current.current.onSaved(applicationId, body);
      }
      if (revision === draft.revision) {
        draft.status = saved ? "saved" : "error";
        if (!saved) current.current.onError("Could not save your private note. Your draft is still available in this session.");
        notify();
      }
    });
  }, [requests]);

  useEffect(() => {
    const accountDrafts = drafts.current;
    const warnBeforeExit = (event: BeforeUnloadEvent) => {
      if (![...accountDrafts.values()].some((draft) => draft.status !== "saved")) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeExit);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeExit);
      for (const draft of accountDrafts.values()) {
        if (draft.timer !== null) clearTimeout(draft.timer);
      }
    };
  }, []);

  function editor(applicationId: number, openingId: number, savedBody: string): PrivateNoteEditor {
    const draft = drafts.current.get(applicationId);
    return {
      body: draft?.body ?? savedBody,
      status: draft?.status ?? "saved",
      change(body) {
        if (suspended.current) return;
        const next = drafts.current.get(applicationId) ?? {
          body: savedBody, savedBody, openingId, revision: 0,
          status: "saved", timer: null, queue: Promise.resolve(),
        };
        next.body = body;
        next.openingId = openingId;
        next.revision += 1;
        next.status = "saving";
        if (next.timer !== null) clearTimeout(next.timer);
        next.timer = setTimeout(() => flush(applicationId), 600);
        drafts.current.set(applicationId, next);
        notify();
      },
      flush: () => {
        const latest = drafts.current.get(applicationId);
        // An explicit retry uses the opening the member is reviewing now. Already
        // queued writes still carry their original context and server authority gates.
        if (latest) latest.openingId = openingId;
        flush(applicationId);
      },
    };
  }

  function suspendWrites() {
    suspended.current = true;
    // Logout may change the cookie before the workspace unmounts. Fence queued work
    // now so it cannot start with another account's credentials.
    requests.reset();
    for (const draft of drafts.current.values()) {
      if (draft.timer !== null) clearTimeout(draft.timer);
      draft.timer = null;
      if (draft.status !== "saved") draft.status = "error";
    }
    notify();
  }

  function resumeWrites() {
    suspended.current = false;
    for (const [applicationId, draft] of drafts.current) {
      if (draft.status === "saved") continue;
      draft.status = "saving";
      flush(applicationId);
    }
    notify();
  }

  return {
    editor,
    hasUnconfirmed: [...drafts.current.values()].some((draft) => draft.status !== "saved"),
    suspendWrites,
    resumeWrites,
  };
}
