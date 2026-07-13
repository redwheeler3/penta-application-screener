import type { AppSettings, AppStatus, StatusSource } from "./types";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Committee-facing labels for the normalized field keys. Keys not listed here
// fall back to a title-cased version of the raw key.
export const FIELD_LABELS: Record<string, string> = {
  applicant_name: "Applicant name",
  co_applicant_name: "Co-applicant name",
  applicant_age: "Applicant age",
  co_applicant_age: "Co-applicant age",
  adult_count: "Adults",
  child_count: "Number of children",
  child_details: "Children",
  household_income: "Household income",
  applicant_income: "Applicant income",
  co_applicant_income: "Co-applicant income",
  has_real_estate: "Owns real estate",
  pets_text: "Pets",
  co_applicant_phone: "Co-applicant phone",
  co_applicant_email: "Co-applicant email",
  applicant_email: "Applicant email",
  form_submission_email: "Form submission email",
  applicant_employment_start: "Applicant employment start",
  co_applicant_employment_start: "Co-applicant employment start",
};

// Normalized fields that should render as currency.
export const MONEY_FIELDS = new Set(["household_income", "applicant_income", "co_applicant_income"]);

// Human-readable labels for AI screening flag categories.
export const FLAG_CATEGORY_LABELS: Record<string, string> = {
  placeholder_name: "Placeholder name",
  suspicious_name: "Suspicious name",
  minimal_essay: "Minimal essay",
  spam_essay: "Spam essay",
  ai_generated_essay: "AI-generated essay",
  duplicated_answers: "Duplicated answers",
  internal_inconsistency: "Internal inconsistency",
  fake_contact: "Suspicious contact info",
  pet_policy: "Pet policy",
  other: "Other",
};

// Maps a filter reason code to the normalized field(s) that caused it, so the
// detail view can highlight the offending value next to the reason.
export const REASON_FIELDS: Record<string, string[]> = {
  income_below_range: ["household_income"],
  income_above_range: ["household_income"],
  income_arithmetic_mismatch: ["household_income", "applicant_income", "co_applicant_income"],
  owns_real_estate: ["has_real_estate"],
  applicant_under_min_age: ["applicant_age"],
  co_applicant_under_min_age: ["co_applicant_age"],
  child_count_mismatch: ["child_count", "child_details"],
  child_age_over_max: ["child_details"],
  too_few_children: ["child_count"],
  too_many_children: ["child_count"],
  child_age_exceeds_parent: ["child_details", "applicant_age", "co_applicant_age"],
  co_applicant_incomplete: ["co_applicant_name", "co_applicant_age", "co_applicant_phone", "co_applicant_email"],
  future_employment_start: ["applicant_employment_start", "co_applicant_employment_start"],
};

// Status and "who set it" are independent axes, shown as separate columns.
export const STATUS_LABELS: Record<AppStatus, string> = {
  eligible: "Eligible",
  ineligible: "Ineligible",
};

// Short label for the "Decided by" column. "untouched" means no actor changed the
// status, so it shows nothing.
export const SOURCE_LABELS: Record<StatusSource, string> = {
  untouched: "—",
  rules: "Rules",
  ai: "AI",
  human: "Reviewer",
};

// Longer, non-prescriptive sentence for the candidate detail page.
export const SOURCE_DESCRIPTIONS: Record<StatusSource, string> = {
  untouched: "Passed the deterministic rules; the AI pass raised no flags.",
  rules: "Set ineligible by the deterministic screening rules.",
  ai: "Flagged by the AI screening pass.",
  human: "Set by a reviewer.",
};

// Placeholder for the initial render only — the GET /settings fetch on mount
// overwrites draft and saved with the server's values (the backend's AppSettings
// schema is the source of truth for every default). Not canonical.
export const defaultSettings: AppSettings = {
  googleSheetId: "",
  incomeMin: 70000,
  incomeMax: 150000,
  minAdultAge: 18,
  maxChildAge: 17,
  minChildren: 1,
  maxChildren: 4,
  maxDogs: 1,
  maxCats: 1,
  allowOtherPets: false,
  disabledRules: [],
  ai: {
    region: "us-west-2",
    screeningModel: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    dimensionScoringModel: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    discoveryModel: "us.anthropic.claude-sonnet-4-6",
    decomposeModel: "us.anthropic.claude-sonnet-4-6",
    matchModel: "us.anthropic.claude-sonnet-4-6",
    consolidateModel: "us.anthropic.claude-sonnet-4-6",
    discoveryFanOut: 5,
    consolidateCorrelationThreshold: 0.85,
    spendingCapUsd: 1.0,
    maxWorkers: 50,
  },
};

// Kept in alphabetical order by label so the toggle grid reads predictably; the
// render sorts defensively too, so a new rule added out of order still slots in.
export const ALL_RULES = [
  { id: "applicant_under_min_age", label: "Applicant under minimum age" },
  { id: "child_age_exceeds_parent", label: "Child age exceeds parent" },
  { id: "child_age_over_max", label: "Child over max age" },
  { id: "child_count_mismatch", label: "Child count mismatch" },
  { id: "co_applicant_incomplete", label: "Co-applicant incomplete" },
  { id: "co_applicant_under_min_age", label: "Co-applicant under minimum age" },
  { id: "future_employment_start", label: "Future employment start" },
  { id: "income_above_range", label: "Income above range" },
  { id: "income_arithmetic_mismatch", label: "Income arithmetic mismatch" },
  { id: "income_below_range", label: "Income below range" },
  { id: "negative_number", label: "Negative number" },
  { id: "owns_real_estate", label: "Real estate ownership" },
  { id: "too_few_children", label: "Too few children" },
  { id: "too_many_children", label: "Too many children" },
] as const;
