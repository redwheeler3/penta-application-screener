import { useEffect, useState } from "react";

import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type { AppSettings, SettingsResponse } from "../types";

export function useSharedSettings(options: {
  dashboardReady: boolean;
}) {
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  function apply(payload: SettingsResponse) {
    setSaved(payload);
    setDraft(payload.settings);
    setLoadFailed(false);
  }

  async function load(): Promise<void> {
    try {
      apply(await retryWithBackoff(api.fetchSettings, 5));
    } catch {
      setLoadFailed(true);
    }
  }

  function retry() {
    setLoadFailed(false);
    void load();
  }

  async function save(): Promise<boolean> {
    if (!draft) return false;
    setIsSaving(true);
    try {
      const response = await api.saveSettings(draft);
      if (!response.ok) return false;
      apply((await response.json()) as SettingsResponse);
      return true;
    } finally {
      setIsSaving(false);
    }
  }

  useEffect(() => {
    if (options.dashboardReady && loadFailed) retry();
    // `load` and `retry` intentionally close over the latest state; this effect is gated by
    // the two primitive conditions that determine whether recovery is needed.
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
