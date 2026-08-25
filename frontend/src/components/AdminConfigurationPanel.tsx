import { type ReactNode, type SyntheticEvent } from "react";

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
}): ReactNode {
  const { draft, setDraft, saved } = props;

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Configuration</h3>
      </div>
      {!saved ? null : (
        <form className="settings-form" onSubmit={props.onSubmit}>
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
