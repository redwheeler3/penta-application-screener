import type { ApiClient } from "./client";

export function createApi({ request }: ApiClient) {
  async function refreshCachedResults(openingId: number, signal: AbortSignal): Promise<boolean> {
    const response = await request(`/cached-results/refresh?opening_id=${openingId}`, { method: "POST", signal });
    if (!response.ok) throw new Error(`Cached result refresh failed (HTTP ${response.status})`);
    return ((await response.json()) as { changed: boolean }).changed;
  }
  return { refreshCachedResults };
}
