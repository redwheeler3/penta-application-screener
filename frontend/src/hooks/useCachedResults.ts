import { useCallback, useEffect, useRef } from "react";

import * as cachedResultsApi from "../api/cachedResults";
import { useCommitteeApi } from "../api/identity";
import { useRequestScope } from "./useRequestScope";

/** Reuse available output in the background without delaying reads or requesting AI work. */
export function useCachedResults(openingId: number | null, paused: boolean, onChanged: () => void) {
  const api = useCommitteeApi(cachedResultsApi);
  const requests = useRequestScope(paused ? null : openingId);
  const activeRequest = useRef<AbortController | null>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const refresh = useCallback(async () => {
    if (paused || openingId === null || !requests.isFor(openingId)) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const isCurrent = requests.begin();
    try {
      if (await api.refreshCachedResults(openingId, controller.signal) && isCurrent()) changed.current();
    } catch {
      // Keep the last consumed output. Focus/intake refresh retries this free bookkeeping.
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [api, openingId, paused, requests]);

  useEffect(() => {
    void refresh();
    return () => activeRequest.current?.abort();
  }, [refresh]);
  return refresh;
}
