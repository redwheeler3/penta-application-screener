import { useEffect, useRef, useState } from "react";

import * as api from "../api/settings";
import { retryWithBackoff } from "../retry";
import type { AppSettings, SettingsResponse } from "../types";
import { useRequestScope } from "./useRequestScope";

export function useSharedSettings(options: {
  dashboardReady: boolean;
}) {
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const reads = useRequestScope();
  const dashboardRecoveryAttempted = useRef(false);

  async function load(): Promise<void> {
    const isCurrent = reads.begin();
    try {
      const payload = await retryWithBackoff(api.fetchSettings, 5);
      if (!isCurrent()) return;
      setSaved(payload);
      setDraft(payload.settings);
      setLoadFailed(false);
    } catch {
      if (isCurrent()) setLoadFailed(true);
    }
  }

  function retry() {
    setLoadFailed(false);
    void load();
  }

  async function save(): Promise<boolean> {
    if (!draft || isSaving) return false;
    const submitted = draft;
    const isCurrent = reads.capture();
    reads.invalidate();
    setIsSaving(true);
    try {
      const response = await api.saveSettings(submitted);
      if (!response.ok || !isCurrent()) return false;
      const payload = (await response.json()) as SettingsResponse;
      if (!isCurrent()) return false;
      reads.invalidate();
      setSaved(payload);
      // The response acknowledges this snapshot; later edits remain an unsaved draft.
      setDraft((current) => current === submitted ? payload.settings : current);
      setLoadFailed(false);
      return true;
    } catch {
      return false;
    } finally {
      if (isCurrent()) setIsSaving(false);
    }
  }

  useEffect(() => {
    if (options.dashboardReady && loadFailed && !dashboardRecoveryAttempted.current) {
      // One recovery cycle after the service becomes ready, then leave Retry visible.
      dashboardRecoveryAttempted.current = true;
      retry();
    }
    // Recovery uses the latest read workflow when these two conditions change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.dashboardReady, loadFailed]);

  return {
    draft,
    setDraft,
    saved,
    isSaving,
    loadFailed,
    load,
    retry,
    save,
  };
}
