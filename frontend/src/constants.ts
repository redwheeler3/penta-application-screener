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
  // Pets became a deterministic per-member reason in M15 1e (was an AI pet_policy flag).
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
  // AI covers both a flag the screening pass raised AND a pet-limit verdict: pets are
  // deterministic, but the AI must read the pet counts from free text first, so they
  // land with the AI pass, not the Sync-time rules (M15 1g).
  ai: "Set ineligible by the AI screening pass — a flag it raised or the pet count it read.",
  human: "Set by a reviewer.",
};

// The numeric eligibility thresholds, in display order, with member-facing labels and input
// bounds. Single source of truth for the three surfaces that render them: the member's
// EligibilitySettingsPanel form, the admin CommitteeDefaultsPanel form, and the divergence
// diff (which needs key+label only). `allowOtherPets` is boolean, rendered separately.
export const ELIGIBILITY_NUMERIC_FIELDS: {
  key: keyof EligibilityRules;
  label: string;
  min: string;
  max?: string;
}[] = [
  { key: "incomeMin", label: "Income minimum", min: "0" },
  { key: "incomeMax", label: "Income maximum", min: "0" },
  { key: "minAdultAge", label: "Min adult age", min: "1", max: "100" },
  { key: "maxChildAge", label: "Max child age", min: "0", max: "100" },
  { key: "minChildren", label: "Min children per unit", min: "0", max: "20" },
  { key: "maxChildren", label: "Max children per unit", min: "0", max: "20" },
  { key: "maxDogs", label: "Max dogs", min: "0", max: "10" },
  { key: "maxCats", label: "Max cats", min: "0", max: "10" },
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

// The two groups of toggleable checks a member can switch off (M15 1g Move 2). Both feed the
// SAME flat `disabledChecks` list on EligibilityRules — the split is presentation only, so a
// member sees the trust difference between a deterministic threshold and an AI judgment.
// Kept alphabetical by label; the render sorts defensively too.

// Each check carries a short `description` — a plain-language sentence of what trips it,
// shown as an info-icon tooltip beside the toggle. Wording tracks the backend: deterministic
// descriptions paraphrase the hard-filter reason messages (app/domain/hard_filters.py); AI
// descriptions paraphrase the screening prompt's flag bullets (app/ai/screening.py). Keep them
// in sync when either source changes.

// DETERMINISTIC rules — Sync-knowable threshold checks over the normalized form fields.
export const DETERMINISTIC_CHECKS = [
  {
    id: "applicant_under_min_age",
    label: "Applicant under minimum age",
    description: "The primary applicant is younger than the minimum adult age.",
  },
  {
    id: "child_age_exceeds_parent",
    label: "Child age exceeds parent",
    description: "A listed child's age is at or above the youngest parent's age.",
  },
  {
    id: "child_age_over_max",
    label: "Child over max age",
    description: "A listed child is older than the maximum child age.",
  },
  {
    id: "child_count_mismatch",
    label: "Child count mismatch",
    description: "The stated number of children doesn't match the child details provided.",
  },
  {
    id: "co_applicant_incomplete",
    label: "Co-applicant incomplete",
    description: "Co-applicant details are only partially filled in.",
  },
  {
    id: "co_applicant_under_min_age",
    label: "Co-applicant under minimum age",
    description: "The co-applicant is younger than the minimum adult age.",
  },
  {
    id: "future_employment_start",
    label: "Future employment start",
    description: "An employment start date is in the future.",
  },
  {
    id: "income_above_range",
    label: "Income above range",
    description: "Household gross income is above the allowed maximum.",
  },
  {
    id: "income_arithmetic_mismatch",
    label: "Income arithmetic mismatch",
    description: "The stated household income doesn't match the sum of the individual incomes.",
  },
  {
    id: "income_below_range",
    label: "Income below range",
    description: "Household gross income is below the required minimum.",
  },
  {
    id: "negative_number",
    label: "Negative number",
    description: "A numeric field (income, ages, counts) holds a negative value.",
  },
  {
    id: "owns_real_estate",
    label: "Real estate ownership",
    description: "The applicant reported owning real estate.",
  },
  {
    id: "too_few_children",
    label: "Too few children",
    description: "The household has fewer children than the minimum required.",
  },
  {
    id: "too_many_children",
    label: "Too many children",
    description: "The household has more children than the maximum allowed.",
  },
] as const;

// AI screening checks — need the model to run (Screen), so they attribute to the AI source.
// The 9 flag categories plus the pet check (a deterministic verdict over AI-extracted pet
// facts — see M15 1g; it groups here because it presents as AI to the member). ids match the
// backend: flag categories are the FlagCategory values, pets is the `pets_over_limit` reason.
export const AI_CHECKS = [
  {
    id: "pets_over_limit",
    label: "Pet policy",
    description: "The pets the AI read from the application exceed your dog, cat, or other-pet limits.",
  },
  {
    id: "placeholder_name",
    label: FLAG_CATEGORY_LABELS.placeholder_name,
    description: "A name field (applicant, co-applicant, or child) holds a placeholder or non-name.",
  },
  {
    id: "minimal_essay",
    label: FLAG_CATEGORY_LABELS.minimal_essay,
    description: "An essay answer is essentially non-responsive — empty, a single word, or a short fragment.",
  },
  {
    id: "spam_essay",
    label: FLAG_CATEGORY_LABELS.spam_essay,
    description: "An essay is clearly spam or advertising, rather than a genuine answer.",
  },
  {
    id: "ai_generated_essay",
    label: FLAG_CATEGORY_LABELS.ai_generated_essay,
    description: "An essay reads as machine-generated rather than written by the applicant.",
  },
  {
    id: "internal_inconsistency",
    label: FLAG_CATEGORY_LABELS.internal_inconsistency,
    description: "A direct factual contradiction between fields or essays (email fields excluded).",
  },
  {
    id: "fake_contact",
    label: FLAG_CATEGORY_LABELS.fake_contact,
    description: "A contact field is a placeholder or keyboard-mash (e.g. 'asdf@asdf.asdf', '111-111-1111').",
  },
  {
    id: "other",
    label: FLAG_CATEGORY_LABELS.other,
    description: "A data-integrity concern the AI surfaced that doesn't fit the other categories.",
  },
] as const;
