import { type ApiClient, publicClient } from "./client";


export function createApi(client: ApiClient) {
  const { getJson, request } = client;
  const fetchCachedEmailDeliveryStatus = (signal?: AbortSignal) =>
    getJson<{ available: boolean; delayed: boolean }>("/email-delivery/status", signal);

  async function refreshEmailDeliveryStatus(signal?: AbortSignal) {
    const response = await request("/email-delivery/status/refresh", {
      method: "POST",
      signal,
    });
    if (!response.ok) throw new Error(`Email delivery refresh failed (HTTP ${response.status})`);
    return (await response.json()) as { available: boolean; delayed: boolean };
  }
  return {
    fetchCachedEmailDeliveryStatus, refreshEmailDeliveryStatus,
  };
}

// Public/bootstrap callers and manual harnesses use the unbound client.
export const {
  fetchCachedEmailDeliveryStatus, refreshEmailDeliveryStatus,
} = createApi(publicClient);
