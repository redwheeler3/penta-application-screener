import { type ReactNode, type SyntheticEvent, useState } from "react";

import * as api from "../api";
import { readProblem } from "../format";
import { isPickerConfigured, pickApplicationsSheet } from "../googlePicker";
import type {
  AIModelProvider,
  AppSettings,
  ReasoningEffort,
  SettingsResponse,
} from "../types";
import { NumberInput } from "./NumberInput";

const REASONING_EFFORTS: ReasoningEffort[] = ["none", "low", "medium", "high", "xhigh", "max"];
const PROVIDER_LABELS: Record<AIModelProvider, string> = {
  bedrock: "Amazon Bedrock",
  openai: "OpenAI direct",
  anthropic: "Anthropic direct",
};

export function AdminConfigurationPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isSaving: boolean;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  onError: (message: string) => void;
  onSettingsUpdated: (payload: SettingsResponse) => void;
}): ReactNode {
  const { draft, setDraft, saved } = props;

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Configuration</h3>
      </div>
      {!saved ? null : (
        <form className="settings-form" onSubmit={props.onSubmit}>
          <SheetLinkField
            saved={saved}
            onError={props.onError}
            onSettingsUpdated={props.onSettingsUpdated}
          />

          <div className="rules-section">
            <h4>AI Screening</h4>
            <div className="settings-grid">
              <label>
                <span>Spending cap (USD per run)</span>
                <NumberInput
                  min="0"
                  step="0.01"
                  value={draft.ai.spendingCapUsd}
                  onChange={(value) =>
                    setDraft({ ...draft, ai: { ...draft.ai, spendingCapUsd: value ?? 0 } })
                  }
                />
                <span className="field-hint">
                  A Rank is blocked before it starts if its estimated cost exceeds this.
                </span>
              </label>
              <label>
                <span>Discovery fan-out (parallel passes)</span>
                <NumberInput
                  min="1"
                  max="10"
                  step="1"
                  value={draft.ai.discoveryFanOut}
                  onChange={(value) =>
                    setDraft({ ...draft, ai: { ...draft.ai, discoveryFanOut: value ?? 0 } })
                  }
                />
                <span className="field-hint">
                  Discovery passes run in parallel per Rank, then settled into one criteria set.
                  More passes find more axes but cost more.
                </span>
              </label>
              <label>
                <span>Maximum concurrent AI calls</span>
                <NumberInput
                  min="1"
                  max="100"
                  step="1"
                  value={draft.ai.maxWorkers}
                  onChange={(value) =>
                    setDraft({ ...draft, ai: { ...draft.ai, maxWorkers: value ?? 0 } })
                  }
                />
                <span className="field-hint">
                  Reduce this if the selected provider throttles bursts. Direct providers
                  have account-specific limits too; switching away from AWS does not remove them.
                </span>
              </label>
              <label>
                <span>Consolidation correlation threshold</span>
                <NumberInput
                  step="0.01"
                  value={draft.ai.consolidateCorrelationThreshold}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      ai: { ...draft.ai, consolidateCorrelationThreshold: value ?? 0 },
                    })
                  }
                />
                <span className="field-hint">
                  After scoring, dimensions whose per-applicant scores correlate at or above this
                  are flagged as possible duplicates for an AI merge check. Lower catches subtler
                  overlaps; higher is stricter. The AI still confirms every merge.
                </span>
              </label>
            </div>
            <div className="ai-pass-settings">
              <div className="ai-pass-settings-head">
                <span>Pass</span><span>Model</span><span>Reasoning</span>
              </div>
              {saved.aiPasses.map((pass) => {
                const model = draft.ai[pass.modelSetting] as string;
                const effort = draft.ai[pass.reasoningSetting] as ReasoningEffort;
                const selected = saved.aiModelOptions.find((option) => option.modelId === model);
                const supportsReasoning = selected?.supportsReasoningEffort ?? false;
                return (
                  <div className="ai-pass-setting" key={pass.key}>
                    <span>{pass.label}</span>
                    <select
                      aria-label={`${pass.label} model`}
                      value={model}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          ai: { ...draft.ai, [pass.modelSetting]: event.target.value },
                        })
                      }
                    >
                      {saved.aiModelOptions.map((option) => (
                        <option
                          value={option.modelId}
                          key={option.modelId}
                          disabled={!option.configured}
                        >
                          {option.label} · {PROVIDER_LABELS[option.provider]}
                          {option.configured ? "" : " (not configured)"}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label={`${pass.label} reasoning effort`}
                      value={effort}
                      disabled={!supportsReasoning}
                      title={supportsReasoning ? undefined : "This model does not use reasoning effort."}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          ai: {
                            ...draft.ai,
                            [pass.reasoningSetting]: event.target.value as ReasoningEffort,
                          },
                        })
                      }
                    >
                      {REASONING_EFFORTS.map((value) => (
                        <option value={value} key={value}>{value}</option>
                      ))}
                    </select>
                  </div>
                );
              })}
              <span className="field-hint">
                Provider credentials are deployment secrets. Only configured direct providers
                can be selected; Bedrock access is verified when a model is invoked. Reasoning
                is saved per pass and used only by models that support it.
              </span>
            </div>
          </div>
          <div className="settings-actions">
            <button className="primary-button" type="submit" disabled={props.isSaving}>
              {props.isSaving ? "Saving…" : "Save configuration"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function SheetLinkField(props: {
  saved: SettingsResponse;
  onError: (message: string) => void;
  onSettingsUpdated: (payload: SettingsResponse) => void;
}): ReactNode {
  const [busy, setBusy] = useState(false);
  const linkedTitle = props.saved.googleSheetTitle ?? null;
  const linkedUrl = props.saved.googleSheetUrl ?? "";
  const hasLink = Boolean(props.saved.settings.googleSheetId);

  async function connectAndPick() {
    setBusy(true);
    try {
      const picked = await pickApplicationsSheet();
      if (!picked) return;
      const response = await api.linkSheet(picked.id);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not link that sheet.");
        return;
      }
      props.onSettingsUpdated((await response.json()) as SettingsResponse);
    } catch (error) {
      props.onError(
        error instanceof Error ? error.message : "Could not connect the applications sheet.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!isPickerConfigured()) {
    return (
      <div className="sheet-link-section">
        <h4>Applications sheet</h4>
        <p className="panel-hint">
          Google Picker isn't configured in this environment (missing API key / client id).
        </p>
      </div>
    );
  }

  return (
    <div className="sheet-link-section">
      <h4>Applications sheet</h4>
      {hasLink ? (
        linkedTitle ? (
          <p className="sheet-reference-line">
            Linked:{" "}
            {linkedUrl ? (
              <a className="sheet-reference" href={linkedUrl} target="_blank" rel="noreferrer noopener">
                {linkedTitle}
              </a>
            ) : (
              <strong>{linkedTitle}</strong>
            )}
          </p>
        ) : (
          <p className="panel-hint">
            A sheet is linked, but its name couldn't be read
            {linkedUrl ? (
              <>
                {" "}(
                <a className="sheet-reference" href={linkedUrl} target="_blank" rel="noreferrer noopener">
                  open it
                </a>
                )
              </>
            ) : null}
            . Try re-linking it below so sync can read it.
          </p>
        )
      ) : (
        <p className="panel-hint">No sheet linked yet.</p>
      )}
      <div className="settings-actions">
        <button type="button" className="primary-button" onClick={connectAndPick} disabled={busy}>
          {busy ? "Connecting…" : hasLink ? "Change applications sheet" : "Connect applications sheet"}
        </button>
      </div>
    </div>
  );
}
