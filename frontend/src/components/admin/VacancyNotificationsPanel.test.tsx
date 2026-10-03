import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/vacancySubscriptions";
import { deferred } from "../../testSupport";
import { VacancyNotificationsPanel } from "./VacancyNotificationsPanel";

vi.mock("../../api/vacancySubscriptions", () => ({
  fetchVacancySubscriptionReport: vi.fn(), lookupVacancySubscription: vi.fn(),
  saveVacancySubscription: vi.fn(), deleteVacancySubscription: vi.fn(),
}));

function subscription(email: string) {
  return { email, unitSizes: [2], source: "Synthetic support request",
    firstConsentedAt: "2026-09-01T00:00:00Z", consentedAt: "2026-09-01T00:00:00Z" };
}

function lookup(email: string) {
  fireEvent.change(screen.getByPlaceholderText("person@example.com"), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: "Look up" }));
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchVacancySubscriptionReport).mockResolvedValue({
    total: 0, oneBedroom: 0, twoBedroom: 0, threeBedroom: 0, latestSignupAt: null, months: [],
  });
});

it("ignores a late lookup for the previous email and keeps the newer lookup busy", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.lookupVacancySubscription).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  render(<VacancyNotificationsPanel onError={vi.fn()} />);
  lookup("a@example.com");
  lookup("b@example.com");
  await act(async () => { first.resolve(Response.json({ subscription: subscription("a@example.com") })); });
  expect(screen.queryByRole("button", { name: "Delete subscription" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Look up" })).toBeDisabled();
  await act(async () => { second.resolve(Response.json({ subscription: subscription("b@example.com") })); });
  expect(screen.getByRole("button", { name: "Delete subscription" })).toBeEnabled();
  vi.mocked(api.deleteVacancySubscription).mockResolvedValue(new Response(null, { status: 204 }));
  fireEvent.click(screen.getByRole("button", { name: "Delete subscription" }));
  expect(api.deleteVacancySubscription).toHaveBeenCalledExactlyOnceWith("b@example.com");
});

it("removes accepted lookup actions immediately when the address changes", async () => {
  vi.mocked(api.lookupVacancySubscription).mockResolvedValue(Response.json({ subscription: subscription("a@example.com") }));
  render(<VacancyNotificationsPanel onError={vi.fn()} />);
  await act(async () => { lookup("A@example.com"); });
  expect(screen.getByRole("button", { name: "Replace preferences" })).toBeEnabled();
  fireEvent.change(screen.getByPlaceholderText("person@example.com"), { target: { value: "b@example.com" } });
  expect(screen.queryByRole("button", { name: "Delete subscription" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Replace preferences" })).not.toBeInTheDocument();
  expect(api.saveVacancySubscription).not.toHaveBeenCalled();
  expect(api.deleteVacancySubscription).not.toHaveBeenCalled();
});

it("ignores a save acknowledgement after switching addresses", async () => {
  const saved = deferred<Response>();
  vi.mocked(api.lookupVacancySubscription).mockResolvedValue(Response.json({ subscription: null }));
  vi.mocked(api.saveVacancySubscription).mockReturnValue(saved.promise);
  render(<VacancyNotificationsPanel onError={vi.fn()} />);
  await act(async () => { lookup("a@example.com"); });
  fireEvent.click(screen.getByRole("checkbox", { name: "2 bedrooms" }));
  fireEvent.click(screen.getByRole("button", { name: "Add subscription" }));
  expect(api.saveVacancySubscription).toHaveBeenCalledWith("a@example.com", [2], "Tech support request");
  fireEvent.change(screen.getByPlaceholderText("person@example.com"), { target: { value: "b@example.com" } });
  await act(async () => { saved.resolve(Response.json({ subscription: subscription("a@example.com") })); });
  expect(screen.queryByText("Subscription saved.")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete subscription" })).not.toBeInTheDocument();
});
