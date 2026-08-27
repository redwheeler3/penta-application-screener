// Mirrors backend AISettings. The UI edits spendingCapUsd and discoveryFanOut; the
// rest are round-tripped so a save never resets them.
export type ReasoningEffort = "none" | "low" | "medium" | "high" | "xhigh" | "max";

export type AISettings = {
  region: string;
  screeningModel: string;
  screeningReasoningEffort: ReasoningEffort;
  dimensionScoringModel: string;
  dimensionScoringReasoningEffort: ReasoningEffort;
  discoveryModel: string;
  discoveryReasoningEffort: ReasoningEffort;
  decomposeModel: string;
  decomposeReasoningEffort: ReasoningEffort;
  matchModel: string;
  matchReasoningEffort: ReasoningEffort;
  consolidateModel: string;
  consolidateReasoningEffort: ReasoningEffort;
  // Parallel discovery calls per Rank.
  discoveryFanOut: number;
  // Pearson r at/above which post-score consolidation nominates a duplicate pair (0–1).
  consolidateCorrelationThreshold: number;
  spendingCapUsd: number;
  maxWorkers: number;
};

export type AIModelProvider = "bedrock" | "openai" | "anthropic";

export type AIModelOption = {
  modelId: string;
  label: string;
  provider: AIModelProvider;
  supportsReasoningEffort: boolean;
  configured: boolean;
};

// Shared infrastructure settings. Member-specific screening policy lives in EligibilityRules.
export type AppSettings = {
  ai: AISettings;
};

export type SettingsResponse = {
  settings: AppSettings;
  aiModelOptions: AIModelOption[];
  aiPasses: AIPassOption[];
};

export type AIPassOption = {
  key: string;
  label: string;
  modelSetting: keyof AISettings;
  reasoningSetting: keyof AISettings;
};

// Members inherit the committee defaults until they save their own screening rules.
// disabledChecks contains both deterministic reason codes and AI screening categories.
export type EligibilityRules = {
  incomeMin: number;
  incomeMax: number;
  minAdultAge: number;
  maxChildAge: number;
  minChildren: number;
  maxChildren: number;
  maxDogs: number;
  maxCats: number;
  allowOtherPets: boolean;
  employmentRequirement: "none" | "at_least_one" | "all";
  disabledChecks: string[];
};

// isDefault: true when the member is still reading the shared committee default (they
// haven't saved their own rules yet); false once they've diverged.
export type EligibilityRulesResponse = {
  rules: EligibilityRules;
  isDefault: boolean;
};
