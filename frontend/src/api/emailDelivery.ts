import { getJson } from "./client";

export const fetchPublicEmailDeliveryStatus = (signal?: AbortSignal) =>
  getJson<{ delayed: boolean }>("/email-delivery/status", signal);
