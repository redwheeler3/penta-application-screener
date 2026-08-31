import { type ReactNode, useState } from "react";
import { CommitteeDefaultsPanel } from "./CommitteeDefaultsPanel";
import { EligibilitySettingsPanel } from "./EligibilitySettingsPanel";

type EligibilitySubtab = "mine" | "default";

export function EligibilitySettingsView(props: {
  openingId: number;
  isAdmin: boolean;
  onError: (message: string) => void;
  onRulesUpdated: () => void;
}): ReactNode {
  const [subtab, setSubtab] = useState<EligibilitySubtab>("mine");

  return (
    <section className="settings-panel no-print" aria-label="Eligibility settings">
      <div className="settings-header">
        <h3>Eligibility Settings</h3>
      </div>
      {props.isAdmin ? (
        <div
          className="subtabs eligibility-settings-subtabs"
          role="tablist"
          aria-label="Eligibility settings sections"
        >
          <button
            type="button"
            role="tab"
            aria-selected={subtab === "mine"}
            className={`subtab${subtab === "mine" ? " active" : ""}`}
            onClick={() => setSubtab("mine")}
          >
            My rules
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subtab === "default"}
            className={`subtab${subtab === "default" ? " active" : ""}`}
            onClick={() => setSubtab("default")}
          >
            Committee default
          </button>
        </div>
      ) : null}
      {subtab === "default" && props.isAdmin ? (
        <CommitteeDefaultsPanel
          openingId={props.openingId}
          onError={props.onError}
          onEligibilityChanged={props.onRulesUpdated}
        />
      ) : (
        <EligibilitySettingsPanel
          openingId={props.openingId}
          onError={props.onError}
          onRulesUpdated={props.onRulesUpdated}
        />
      )}
    </section>
  );
}
