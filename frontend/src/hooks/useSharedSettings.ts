import { useEffect, useState } from "react";

import * as api from "../api";
import { resolveSheetId } from "../format";
import { retryWithBackoff } from "../retry";
import type { AppSettings, CurrentUser, SettingsResponse } from "../types";

export function useSharedSettings(options: {
  user: CurrentUser | null;
  dashboardReady: boolean;
  onMissingSheet: () => void;
}) {
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  function apply(payload: SettingsResponse) {
    const sheetId = resolveSheetId(payload);
    setSaved(payload);
    setDraft({ ...payload.settings, googleSheetId: sheetId });
    setLoadFailed(false);
    if (!sheetId) options.onMissingSheet();
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

  const linkedSheetId = saved?.settings.googleSheetId ?? "";
  const linkedSheetTitle = saved?.googleSheetTitle ?? null;
  useEffect(() => {
    if (!options.user || !linkedSheetId || linkedSheetTitle) return;

    const retrySheetTitle = () => {
      if (document.visibilityState !== "visible") return;
      void api
        .fetchSettings()
        .then((payload) => {
          if (!payload.googleSheetTitle) return;
          setSaved((current) =>
            current && current.settings.googleSheetId === payload.settings.googleSheetId
              ? { ...current, googleSheetTitle: payload.googleSheetTitle }
              : current,
          );
        })
        .catch(() => {});
    };

    document.addEventListener("visibilitychange", retrySheetTitle);
    return () => document.removeEventListener("visibilitychange", retrySheetTitle);
  }, [options.user, linkedSheetId, linkedSheetTitle]);

  return {
    draft,
    setDraft,
    saved,
    isSaving,
    loadFailed,
    load,
    retry,
    save,
    apply,
    hasLinkedSheet: Boolean(saved && resolveSheetId(saved)),
    loadState: saved ? ("ready" as const) : loadFailed ? ("error" as const) : ("loading" as const),
  };
}
