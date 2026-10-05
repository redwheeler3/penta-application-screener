import { type ApiClient } from "./client";
import type { ScreeningEstimateResponse } from "../types";

export function createApi(client: ApiClient) {
  const { getJson, streamRequest } = client;
  const fetchScreeningEstimate = (openingId: number, signal?: AbortSignal) =>
    getJson<ScreeningEstimateResponse>(`/screening/run/estimate?opening_id=${openingId}`, signal);

  const runScreening = (openingId: number, signal?: AbortSignal) =>
    streamRequest(`/screening/run?opening_id=${openingId}`, signal);
  return {
    fetchScreeningEstimate, runScreening,
  };
}
