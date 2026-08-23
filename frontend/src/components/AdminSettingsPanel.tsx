import { type ReactNode, type SyntheticEvent, useState } from "react";

import type { AppSettings, CurrentUser, SettingsResponse, ViewTab } from "../types";
import { AccessPanel } from "./AccessPanel";
import { AdminConfigurationPanel } from "./AdminConfigurationPanel";
import { CommitteeDefaultsPanel } from "./CommitteeDefaultsPanel";
import { FeedbackPanel } from "./FeedbackPanel";

type AdminSubtab = "configuration" | "defaults" | "access" | "feedback";

const ADMIN_SUBTABS: Array<{ id: AdminSubtab; label: string }> = [
  { id: "configuration", label: "Configuration" },
  { id: "defaults", label: "Committee Defaults" },
  { id: "access", label: "Access" },
  { id: "feedback", label: "Feedback" },
];

export function AdminSettingsPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isSaving: boolean;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  onError: (message: string) => void;
  onSettingsUpdated: (payload: SettingsResponse) => void;
  onEligibilityChanged: () => void;
  onOpenApplicant: (id: number) => void;
  onOpenView: (tab: ViewTab) => void;
  currentUser: CurrentUser;
}): ReactNode {
  const [subtab, setSubtab] = useState<AdminSubtab>("configuration");

  return (
    <section className="settings-panel no-print" aria-label="Admin settings">
      <div className="settings-header">
        <h3>Admin Settings</h3>
      </div>
      <div
        className="subtabs admin-settings-subtabs"
        role="tablist"
        aria-label="Admin settings sections"
      >
        {ADMIN_SUBTABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={subtab === tab.id}
            className={`subtab${subtab === tab.id ? " active" : ""}`}
            onClick={() => setSubtab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {subtab === "feedback" ? (
        <FeedbackPanel
          onError={props.onError}
          onOpenApplicant={props.onOpenApplicant}
          onOpenView={props.onOpenView}
        />
      ) : subtab === "access" ? (
        <AccessPanel currentUser={props.currentUser} onError={props.onError} />
      ) : subtab === "defaults" ? (
        <CommitteeDefaultsPanel
          onError={props.onError}
          onEligibilityChanged={props.onEligibilityChanged}
        />
      ) : (
        <AdminConfigurationPanel
          draft={props.draft}
          setDraft={props.setDraft}
          saved={props.saved}
          isSaving={props.isSaving}
          onSubmit={props.onSubmit}
          onError={props.onError}
          onSettingsUpdated={props.onSettingsUpdated}
        />
      )}
    </section>
  );
}
