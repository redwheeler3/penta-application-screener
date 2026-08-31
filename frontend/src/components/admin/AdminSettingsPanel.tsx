import { type ReactNode, type SyntheticEvent } from "react";

import type { AppSettings, CurrentUser, SettingsResponse, ViewTab } from "../../types";
import { AccessPanel } from "./AccessPanel";
import { AdminConfigurationPanel } from "./AdminConfigurationPanel";
import { EmailDeliveryPanel } from "./EmailDeliveryPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { OpeningsPanel } from "./OpeningsPanel";
import { VacancyNotificationsPanel } from "./VacancyNotificationsPanel";

export type AdminSubtab = "configuration" | "openings" | "notifications" | "emailDelivery" | "access" | "feedback";

const ADMIN_SUBTABS: Array<{ id: AdminSubtab; label: string }> = [
  { id: "configuration", label: "Configuration" },
  { id: "openings", label: "Openings" },
  { id: "notifications", label: "Notifications" },
  { id: "emailDelivery", label: "Email Delivery" },
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
  onEligibilityChanged: () => void;
  onOpenApplicant: (id: number) => void;
  onOpenOpeningApplicant: (id: number, openingId: number) => void;
  onOpenView: (tab: ViewTab) => void;
  currentUser: CurrentUser;
  subtab: AdminSubtab;
  onSubtabChange: (subtab: AdminSubtab) => void;
  onPoolChanged: () => void;
  onOpenRetainedApplicant: (id: number) => void;
}): ReactNode {
  const subtab = props.subtab;

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
            onClick={() => props.onSubtabChange(tab.id)}
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
      ) : subtab === "openings" ? (
        <OpeningsPanel
          onError={props.onError}
          onPoolChanged={props.onPoolChanged}
          onOpenApplicant={props.onOpenOpeningApplicant}
          onOpenRetainedApplicant={props.onOpenRetainedApplicant}
        />
      ) : subtab === "notifications" ? (
        <VacancyNotificationsPanel onError={props.onError} />
      ) : subtab === "emailDelivery" ? (
        <EmailDeliveryPanel onError={props.onError} />
      ) : (
        <AdminConfigurationPanel
          draft={props.draft}
          setDraft={props.setDraft}
          saved={props.saved}
          isSaving={props.isSaving}
          onSubmit={props.onSubmit}
        />
      )}
    </section>
  );
}
