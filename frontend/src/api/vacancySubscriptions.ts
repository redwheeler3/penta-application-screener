import type { VacancySubscription, VacancySubscriptionReport } from "../types";
import { getJson, request } from "./client";

export const fetchVacancySubscriptionReport = () =>
  getJson<VacancySubscriptionReport>("/vacancy-subscriptions/report");

export const lookupVacancySubscription = (email: string) =>
  request("/vacancy-subscriptions/admin/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });

export const saveVacancySubscription = (
  email: string,
  unitSizes: number[],
  source: string,
) =>
  request("/vacancy-subscriptions/admin", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, unitSizes, source }),
  });

export const deleteVacancySubscription = (email: string, source: string) =>
  request("/vacancy-subscriptions/admin/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, source }),
  });

export type VacancySubscriptionLookup = { subscription: VacancySubscription | null };
