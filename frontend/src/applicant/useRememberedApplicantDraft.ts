import { useCallback, useEffect, useRef, useState } from "react";

import {
  observeRememberedStorage,
  rememberedStorageScope,
  saveApplicationDraft,
  setRememberDevice,
} from "./draftStorage";
import type { ApplicantDraft } from "./types";

type DraftSnapshot = {
  authenticated: boolean;
  applicationId: number | null;
  workingRevision: number | null;
  draft: ApplicantDraft;
  openingIds: number[];
};

/** Own browser consent and acknowledgements separately from the server save workflow. */
export function useRememberedApplicantDraft(snapshot: DraftSnapshot) {
  const [scope, setScope] = useState(rememberedStorageScope);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const accepted = useRef<DraftSnapshot | null>(null);
  const consentRequest = useRef(0);

  const reset = useCallback(() => {
    consentRequest.current += 1;
    accepted.current = null;
    setScope(null);
    setSavedAt(null);
  }, []);

  useEffect(() => observeRememberedStorage(reset), [reset]);

  async function changeRememberDevice(remember: boolean) {
    const request = ++consentRequest.current;
    try {
      const consent = await setRememberDevice(remember);
      if (request !== consentRequest.current) return;
      accepted.current = null;
      setScope(rememberedStorageScope() === consent ? consent : null);
      setSavedAt(null);
    } catch {
      if (request === consentRequest.current) reset();
    }
  }

  useEffect(() => {
    if (!snapshot.authenticated || scope === null || snapshot.applicationId === null || snapshot.workingRevision === null) return;
    let current = true;
    const timeout = window.setTimeout(() => {
      void saveApplicationDraft(snapshot.applicationId!, snapshot.draft, snapshot.openingIds,
        snapshot.workingRevision!, scope).then((when) => {
        if (!current) return;
        accepted.current = when === null ? null : snapshot;
        setSavedAt(when);
      }).catch(() => {
        if (current) {
          accepted.current = null;
          setSavedAt(null);
        }
      });
    }, 350);
    return () => {
      current = false;
      window.clearTimeout(timeout);
    };
    // The snapshot groups the exact submitted fields; its render-local wrapper is not a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot.authenticated, snapshot.applicationId, snapshot.workingRevision, snapshot.draft, snapshot.openingIds, scope]);

  function currentDraftIsStored(): boolean {
    const stored = accepted.current;
    return scope !== null && rememberedStorageScope() === scope && stored !== null
      && stored.applicationId === snapshot.applicationId && stored.workingRevision === snapshot.workingRevision
      && stored.draft === snapshot.draft && stored.openingIds === snapshot.openingIds;
  }

  return { rememberDevice: scope !== null, savedAt, changeRememberDevice, reset, currentDraftIsStored };
}
