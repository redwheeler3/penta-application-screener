import type { ScreeningEstimateResponse } from "../types";
import { getJson, streamRequest } from "./client";

export const fetchScreeningEstimate = (signal?: AbortSignal) =>
  getJson<ScreeningEstimateResponse>("/screening/run/estimate", signal);
export const runScreening = () => streamRequest("/screening/run");
