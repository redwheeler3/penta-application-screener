import { useCommitteeApi } from "../api/identity";
import { useCallback, useEffect, useRef } from "react";

import * as applicationsApi from "../api/applications";
import { useRequestScope } from "./useRequestScope";

type PrivateNoteSnapshot = {
  body: string;
  status: "saved" | "saving" | "error" | "blocked";
};

export type PrivateNoteEditor = {
  getSnapshot: () => PrivateNoteSnapshot;
  subscribe: (listener: () => void) => () => void;
  change: (body: string) => void;
  flush: () => void;
  block: () => void;
  discard: () => void;
};

type Draft = {
  snapshot: PrivateNoteSnapshot;
  savedBody: string;
  openingId: number;
  revision: number;
  timer: ReturnType<typeof setTimeout> | null;
  queue: Promise<void>;
  listeners: Set<() => void>;
  blocked: boolean;
};

/** Account-owned drafts survive editor/tab/opening changes, in memory only. Each
 * applicant has one ordered writer because private notes belong to the applicant.
 * Editors subscribe directly so typing does not rerender the whole workspace. */
export function usePrivateNotes(options: {
  onSaved: (applicationId: number, body: string) => void;
  onError: (message: string) => void;
}) {
  const { savePrivateNote } = useCommitteeApi(applicationsApi);

  const drafts = useRef(new Map<number, Draft>());
  const current = useRef(options);
  current.current = options;
  const requests = useRequestScope();
  const suspended = useRef(false);
  const releaseConfirmed = useCallback((applicationId: number, draft: Draft) => {
    // Unsent drafts survive navigation. Confirmed, unobserved notes come from the
    // next detail read instead of becoming an account-long private-note cache.
    if (draft.snapshot.status === "saved" && draft.listeners.size === 0 && drafts.current.get(applicationId) === draft) {
      drafts.current.delete(applicationId);
    }
  }, []);

  const flush = useCallback((applicationId: number) => {
    const draft = drafts.current.get(applicationId);
    if (!draft || draft.blocked || draft.snapshot.status === "saved" || suspended.current) return;
    if (draft.timer !== null) clearTimeout(draft.timer);
    draft.timer = null;
    const { snapshot: { body }, revision, openingId } = draft;
    const inAccount = requests.capture();
    draft.snapshot = { body, status: "saving" };
    draft.listeners.forEach((listener) => listener());
    draft.queue = draft.queue.then(async () => {
      const beforeSave = draft.snapshot;
      if (!inAccount() || revision !== draft.revision || draft.blocked || beforeSave.status === "saved") return;
      // Dirty/retry drafts need an acknowledgement: an earlier uncertain write may
      // have changed the server even when this text equals the last confirmed body.
      let saved: boolean;
      try {
        const response = await savePrivateNote(applicationId, openingId, body);
        saved = response.ok;
        if (response.status === 404) draft.blocked = true;
      } catch {
        saved = false;
      }
      if (!inAccount()) return;
      if (saved) {
        draft.savedBody = body;
        current.current.onSaved(applicationId, body);
        if (revision !== draft.revision && draft.snapshot.status === "saved") {
          draft.snapshot = { body, status: "saved" };
          draft.listeners.forEach((listener) => listener());
        }
      }
      if (revision === draft.revision) {
        draft.snapshot = { body, status: saved ? "saved" : draft.blocked ? "blocked" : "error" };
        if (!saved) current.current.onError("Could not save your private note. Your draft is still available in this session.");
        draft.listeners.forEach((listener) => listener());
        releaseConfirmed(applicationId, draft);
      }
    });
  }, [requests, releaseConfirmed, savePrivateNote]);

  useEffect(() => {
    const accountDrafts = drafts.current;
    const warnBeforeExit = (event: BeforeUnloadEvent) => {
      if (![...accountDrafts.values()].some((draft) => draft.snapshot.status !== "saved")) return;
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
    const initial: PrivateNoteSnapshot = { body: savedBody, status: "saved" };
    function getDraft(): Draft {
      let draft = drafts.current.get(applicationId);
      if (!draft) {
        draft = { snapshot: initial, savedBody, openingId, revision: 0,
          timer: null, queue: Promise.resolve(), listeners: new Set(), blocked: false };
        drafts.current.set(applicationId, draft);
      }
      return draft;
    }
    return {
      // Repeated reads return the same snapshot object until the draft changes,
      // as React's useSyncExternalStore requires.
      getSnapshot: () => drafts.current.get(applicationId)?.snapshot ?? initial,
      subscribe(listener) {
        const draft = getDraft();
        draft.listeners.add(listener);
        return () => {
          draft.listeners.delete(listener);
          releaseConfirmed(applicationId, draft);
        };
      },
      change(body) {
        if (suspended.current || getDraft().blocked) return;
        const next = getDraft();
        next.snapshot = { body, status: "saving" };
        next.openingId = openingId;
        next.revision += 1;
        if (next.timer !== null) clearTimeout(next.timer);
        next.timer = setTimeout(() => flush(applicationId), 600);
        next.listeners.forEach((listener) => listener());
      },
      flush: () => {
        const latest = drafts.current.get(applicationId);
        // An explicit retry uses the opening the member is reviewing now. Already
        // queued writes still carry their original context and server authority gates.
        if (latest) latest.openingId = openingId;
        flush(applicationId);
      },
      block: () => {
        const draft = getDraft();
        if (draft.blocked) return;
        draft.blocked = true;
        if (draft.timer !== null) clearTimeout(draft.timer);
        draft.timer = null;
        if (draft.snapshot.status !== "saved") {
          draft.snapshot = { ...draft.snapshot, status: "blocked" };
          draft.listeners.forEach((listener) => listener());
        }
      },
      discard: () => {
        const draft = getDraft();
        draft.revision += 1;
        if (draft.timer !== null) clearTimeout(draft.timer);
        draft.timer = null;
        draft.snapshot = { body: draft.savedBody, status: "saved" };
        draft.listeners.forEach((listener) => listener());
        releaseConfirmed(applicationId, draft);
      },
    };
  }

  const suspendWrites = useCallback(() => {
    suspended.current = true;
    // Logout may change the cookie before the workspace unmounts. Fence queued work
    // now so it cannot start with another account's credentials.
    requests.reset();
    for (const draft of drafts.current.values()) {
      if (draft.timer !== null) clearTimeout(draft.timer);
      draft.timer = null;
    }
  }, [requests]);

  function resumeWrites() {
    suspended.current = false;
    for (const [applicationId, draft] of drafts.current) {
      if (draft.snapshot.status !== "saved") flush(applicationId);
    }
  }

  return {
    editor,
    unsavedText: () => [...drafts.current.entries()]
      .filter(([, draft]) => draft.snapshot.status !== "saved")
      .map(([id, draft]) => `Applicant ${id}\n${draft.snapshot.body}`).join("\n\n"),
    hasUnconfirmed: () => [...drafts.current.values()].some((draft) => draft.snapshot.status !== "saved"),
    suspendWrites,
    resumeWrites,
  };
}
