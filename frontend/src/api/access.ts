import { type ApiClient } from "./client";
import type { AllowlistEntry, DeniedSignInAttempt } from "../types";

export function createApi(client: ApiClient) {
  const { getJson, request } = client;
  // --- Access allowlist (admin only) -----------------------------------------

  const fetchAllowlist = () =>
    getJson<{ entries: AllowlistEntry[] }>("/allowlist").then((p) => p.entries);

  const fetchDeniedSignInAttempts = () =>
    getJson<{ attempts: DeniedSignInAttempt[] }>("/allowlist/denied-attempts").then((p) => p.attempts);

  function upsertAllowlistEntry(email: string, role: "admin" | "member"): Promise<Response> {
    return request("/allowlist", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    });
  }

  function removeAllowlistEntry(email: string): Promise<Response> {
    return request(`/allowlist/${encodeURIComponent(email)}`, {
      method: "DELETE",
    });
  }
  return {
    fetchAllowlist, fetchDeniedSignInAttempts, upsertAllowlistEntry, removeAllowlistEntry,
  };
}
