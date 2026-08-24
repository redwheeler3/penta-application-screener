import type { AppStatus, EligibilityRules, StatusSource } from "./types";

// Prod is single-origin: FastAPI serves this bundle, so API calls are relative ("").
// Dev keeps the two-origin split (Vite on :5173, API on :8000), so DEV falls back to the
// backend's dev URL. An explicit VITE_API_BASE_URL overrides either (e.g. a split deploy).
export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

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

// Human-readable labels for AI screening flag categories — each the enum value title-cased,
// so a label never drifts from the category a screener sees elsewhere (e.g. fake_contact reads
// "Fake contact", not "Suspicious contact info" which read like a name check).
export const FLAG_CATEGORY_LABELS: Record<string, string> = {
  placeholder_name: "Placeholder name",
  minimal_essay: "Minimal essay",
  spam_essay: "Spam essay",
  ai_generated_essay: "AI-generated essay",
  internal_inconsistency: "Internal inconsistency",
  fake_contact: "Fake contact",
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
  pets_over_limit: ["pets_text"],
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
  // Pet limits are deterministic, but they depend on pet facts extracted during Screen.
  ai: "Set ineligible by the AI screening pass — a flag it raised or the pet count it read.",
  human: "Set by a reviewer.",
};

// The numeric eligibility thresholds, in display order, with member-facing labels and input
// bounds. Single source of truth for the three surfaces that render them: the member's
// EligibilitySettingsPanel form, the admin CommitteeDefaultsPanel form, and the divergence
// diff (which needs key+label only). `allowOtherPets` is boolean, rendered separately.
type EligibilityNumericField = {
  key: keyof EligibilityRules;
  label: string;
  min: string;
  max?: string;
};

export const ELIGIBILITY_GENERAL_NUMERIC_FIELDS: EligibilityNumericField[] = [
  { key: "incomeMin", label: "Income minimum", min: "0" },
  { key: "incomeMax", label: "Income maximum", min: "0" },
  { key: "minAdultAge", label: "Min adult age", min: "1", max: "100" },
  { key: "maxChildAge", label: "Max child age", min: "0", max: "100" },
  { key: "minChildren", label: "Min children per unit", min: "0", max: "20" },
  { key: "maxChildren", label: "Max children per unit", min: "0", max: "20" },
];

export const ELIGIBILITY_PET_NUMERIC_FIELDS: EligibilityNumericField[] = [
  { key: "maxDogs", label: "Max dogs", min: "0", max: "10" },
  { key: "maxCats", label: "Max cats", min: "0", max: "10" },
];

export const ELIGIBILITY_NUMERIC_FIELDS = [
  ...ELIGIBILITY_GENERAL_NUMERIC_FIELDS,
  ...ELIGIBILITY_PET_NUMERIC_FIELDS,
];

// The five AI passes in PIPELINE order — screening first, then the Rank chain (decompose →
// match → score → consolidate). Single source of truth for the eval subtab order
// (AIQualityView) and the judge's per-pass case grouping (RunnableEval), so the two render
// the way the app runs and can't drift out of order.
export const AI_PASS_PIPELINE_ORDER = [
  "screening",
  "decomposition",
  "matching",
  "scoring",
  "consolidation",
] as const;
