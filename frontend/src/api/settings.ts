import type {
  AppSettings,
  EligibilityCheckCatalog,
  EligibilityRules,
  EligibilityRulesResponse,
  SettingsResponse,
} from "../types";
import { getJson, request } from "./client";

export const fetchSettings = () => getJson<SettingsResponse>("/settings");

export function saveSettings(draft: AppSettings): Promise<Response> {
  return request("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
}
// --- Eligibility rules (per member) ----------------------------------------
// The numeric screening rules each member tunes for themselves. A member reads the
// shared committee default until they save their own (see EligibilityRulesResponse).

export const fetchEligibilityRules = (openingId: number) =>
  getJson<EligibilityRulesResponse>(`/eligibility-rules?opening_id=${openingId}`);

export const fetchEligibilityCheckCatalog = () =>
  getJson<EligibilityCheckCatalog>("/eligibility-rules/catalog");

export function saveEligibilityRules(openingId: number, rules: EligibilityRules): Promise<Response> {
  return request(`/eligibility-rules?opening_id=${openingId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  });
}

// Remove the member override and return the committee defaults now in effect.
export function resetEligibilityRules(openingId: number): Promise<Response> {
  return request(`/eligibility-rules?opening_id=${openingId}`, { method: "DELETE" });
}

// The shared baseline a member follows until they save an override.
export const fetchCommitteeDefaultRules = (openingId: number) =>
  getJson<EligibilityRules>(`/eligibility-rules/committee-default?opening_id=${openingId}`);

// Editing the committee default does not rewrite member override rows.
export function saveCommitteeDefaultRules(openingId: number, rules: EligibilityRules): Promise<Response> {
  return request(`/eligibility-rules/committee-default?opening_id=${openingId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  });
}
