import { getJson, request } from "./client";

export const fetchCachedEmailDeliveryStatus = (signal?: AbortSignal) =>
  getJson<{ available: boolean; delayed: boolean }>("/email-delivery/status", signal);

export async function refreshEmailDeliveryStatus(signal?: AbortSignal) {
  const response = await request("/email-delivery/status/refresh", {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new Error(`Email delivery refresh failed (HTTP ${response.status})`);
  return (await response.json()) as { available: boolean; delayed: boolean };
}
