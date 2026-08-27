import type { AllowlistEntry, DeniedSignInAttempt } from "../types";
import { getJson, request } from "./client";

// --- Access allowlist (admin only) -----------------------------------------

export const fetchAllowlist = () =>
  getJson<{ entries: AllowlistEntry[] }>("/allowlist").then((p) => p.entries);

export const fetchDeniedSignInAttempts = () =>
  getJson<{ attempts: DeniedSignInAttempt[] }>("/allowlist/denied-attempts").then((p) => p.attempts);

export function upsertAllowlistEntry(email: string, role: "admin" | "member"): Promise<Response> {
  return request("/allowlist", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
}

export function removeAllowlistEntry(email: string): Promise<Response> {
  return request(`/allowlist/${encodeURIComponent(email)}`, {
    method: "DELETE",
  });
}

