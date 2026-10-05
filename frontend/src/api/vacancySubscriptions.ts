import type { VacancySubscription, VacancySubscriptionReport } from "../types";
import type { ApiClient } from "./client";

export function createApi({ getJson, request }: ApiClient) {
  const fetchVacancySubscriptionReport = () =>
    getJson<VacancySubscriptionReport>("/vacancy-subscriptions/report");

  const lookupVacancySubscription = (email: string) =>
    request("/vacancy-subscriptions/admin/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

  const saveVacancySubscription = (
    email: string,
    unitSizes: number[],
    source: string,
  ) =>
    request("/vacancy-subscriptions/admin", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, unitSizes, source }),
    });

  const deleteVacancySubscription = (email: string) =>
    request("/vacancy-subscriptions/admin/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

  return { fetchVacancySubscriptionReport, lookupVacancySubscription, saveVacancySubscription, deleteVacancySubscription };
}

export type VacancySubscriptionLookup = { subscription: VacancySubscription | null };
