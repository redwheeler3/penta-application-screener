import type { ScreeningEstimateResponse } from "../types";
import { getJson, streamRequest } from "./client";

export const fetchScreeningEstimate = (openingId: number, signal?: AbortSignal) =>
  getJson<ScreeningEstimateResponse>(`/screening/run/estimate?opening_id=${openingId}`, signal);
export const runScreening = (openingId: number) =>
  streamRequest(`/screening/run?opening_id=${openingId}`);
