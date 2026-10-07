import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { VacancyNotificationsPanel } from "./VacancyNotificationsPanel";

const api = vi.hoisted(() => ({
  fetchVacancySubscriptionReport: vi.fn<ReturnType<typeof import("../../api/vacancySubscriptions").createApi>["fetchVacancySubscriptionReport"]>(),
  lookupVacancySubscription: vi.fn<ReturnType<typeof import("../../api/vacancySubscriptions").createApi>["lookupVacancySubscription"]>(),
  saveVacancySubscription: vi.fn<ReturnType<typeof import("../../api/vacancySubscriptions").createApi>["saveVacancySubscription"]>(),
  deleteVacancySubscription: vi.fn<ReturnType<typeof import("../../api/vacancySubscriptions").createApi>["deleteVacancySubscription"]>(),
}));

vi.mock("../../api/vacancySubscriptions", () => ({
  createApi: () => api,
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

it("keeps the email locked until a save acknowledgement settles", async () => {
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
  expect(screen.getByPlaceholderText("person@example.com")).toHaveValue("a@example.com");
  expect(screen.getByText("Subscription saved.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete subscription" })).toBeEnabled();
});


it.each(["save", "delete"])("locks address and preferences during %s and releases them after failure", async (action) => {
  api.lookupVacancySubscription.mockResolvedValue(Response.json({ subscription: subscription("a@example.com") }));
  const pending = deferred<Response>();
  api.saveVacancySubscription.mockReturnValue(pending.promise);
  api.deleteVacancySubscription.mockReturnValue(pending.promise);
  render(<VacancyNotificationsPanel onError={vi.fn()} />);
  await act(async () => lookup("a@example.com"));
  fireEvent.click(screen.getByRole("button", { name: action === "save" ? "Replace preferences" : "Delete subscription" }));
  const email = screen.getByPlaceholderText("person@example.com");
  expect(email).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "2 bedrooms" })).toBeDisabled();
  fireEvent.change(email, { target: { value: " A@example.com " } });
  expect(email).toHaveValue("a@example.com");
  fireEvent.click(screen.getByRole("button", { name: action === "save" ? "Delete subscription" : "Replace preferences" }));
  expect(action === "save" ? api.deleteVacancySubscription : api.saveVacancySubscription).not.toHaveBeenCalled();
  await act(async () => pending.reject(new Error("Offline")));
  expect(email).toBeEnabled();
  expect(screen.getByRole("checkbox", { name: "2 bedrooms" })).toBeChecked();
  expect(screen.getByRole("button", { name: "Replace preferences" })).toBeEnabled();
});
