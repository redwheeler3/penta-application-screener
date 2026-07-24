import type { AppStatus, StatusSource } from "./types";

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

// Maps AI screening flag categories to the normalized fields they concern. These
// use the same red field treatment as deterministic filter reasons in the detail view.
// (Pets are no longer a flag as of M15 1e — see pets_over_limit in REASON_FIELDS.)
export const FLAG_FIELDS: Record<string, string[]> = {};

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

// The two groups of toggleable checks a member can switch off (M15 1g Move 2). Both feed the
// SAME flat `disabledChecks` list on EligibilityRules — the split is presentation only, so a
// member sees the trust difference between a deterministic threshold and an AI judgment.
// Kept alphabetical by label; the render sorts defensively too.

// DETERMINISTIC rules — Sync-knowable threshold checks over the normalized form fields.
export const DETERMINISTIC_CHECKS = [
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

// AI screening checks — need the model to run (Screen), so they attribute to the AI source.
// The 9 flag categories plus the pet check (a deterministic verdict over AI-extracted pet
// facts — see M15 1g; it groups here because it presents as AI to the member). ids match the
// backend: flag categories are the FlagCategory values, pets is the `pets_over_limit` reason.
export const AI_CHECKS = [
  { id: "pets_over_limit", label: "Pet policy" },
  { id: "placeholder_name", label: FLAG_CATEGORY_LABELS.placeholder_name },
  { id: "suspicious_name", label: FLAG_CATEGORY_LABELS.suspicious_name },
  { id: "minimal_essay", label: FLAG_CATEGORY_LABELS.minimal_essay },
  { id: "spam_essay", label: FLAG_CATEGORY_LABELS.spam_essay },
  { id: "ai_generated_essay", label: FLAG_CATEGORY_LABELS.ai_generated_essay },
  { id: "duplicated_answers", label: FLAG_CATEGORY_LABELS.duplicated_answers },
  { id: "internal_inconsistency", label: FLAG_CATEGORY_LABELS.internal_inconsistency },
  { id: "fake_contact", label: FLAG_CATEGORY_LABELS.fake_contact },
  { id: "other", label: FLAG_CATEGORY_LABELS.other },
] as const;
