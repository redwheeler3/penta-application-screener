import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/settings";
import { deferred } from "../../testSupport";
import type { EligibilityRules } from "../../types";
import { CommitteeDefaultsPanel } from "./CommitteeDefaultsPanel";
import { EligibilitySettingsPanel } from "./EligibilitySettingsPanel";

vi.mock("../../api/settings", () => ({
  fetchEligibilityCheckCatalog: vi.fn(), fetchCommitteeDefaultRules: vi.fn(),
  fetchEligibilityRules: vi.fn(), saveCommitteeDefaultRules: vi.fn(),
  saveEligibilityRules: vi.fn(), resetEligibilityRules: vi.fn(),
}));

const rules = (minAdultAge: number): EligibilityRules => ({
  incomeMin: 0, incomeMax: 200000, minAdultAge, maxChildAge: 18, minChildren: 0,
  maxChildren: 4, maxDogs: 1, maxCats: 1, allowOtherPets: true,
  employmentRequirement: "none", disabledChecks: [],
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchEligibilityCheckCatalog).mockResolvedValue({ deterministic: [], ai: [] });
  vi.mocked(api.fetchCommitteeDefaultRules).mockImplementation(async (id) => rules(id === 1 ? 18 : 30));
  vi.mocked(api.fetchEligibilityRules).mockImplementation(async (id) => ({ rules: rules(id === 1 ? 18 : 30), isDefault: false }));
});

function editor(kind: string, openingId: number, onUpdated = vi.fn()) {
  return kind === "default"
    ? <CommitteeDefaultsPanel openingId={openingId} onError={vi.fn()} onEligibilityChanged={onUpdated} />
    : <EligibilitySettingsPanel openingId={openingId} onError={vi.fn()} onRulesUpdated={onUpdated} />;
}

function accepted(kind: string, age = 18) {
  return Response.json(kind === "default" ? rules(age) : { rules: rules(age), isDefault: false });
}

it.each(["default", "mine"])("preserves edits made while the %s rules save is pending", async (kind) => {
  const pending = deferred<Response>();
  const save = vi.mocked(kind === "default" ? api.saveCommitteeDefaultRules : api.saveEligibilityRules);
  save.mockReturnValue(pending.promise);
  render(editor(kind, 1));
  const input = await screen.findByRole("textbox", { name: "Min adult age" });
  fireEvent.submit(input.closest("form")!);
  fireEvent.change(input, { target: { value: "25" } });
  await act(async () => { pending.resolve(accepted(kind)); });
  expect(input).toHaveValue("25");
  expect(screen.queryByRole("button", { name: "Saved" })).not.toBeInTheDocument();
  fireEvent.submit(input.closest("form")!);
  expect(save).toHaveBeenLastCalledWith(1, rules(25));
});

it.each(["default", "mine"])("ignores an earlier opening %s save while the new opening is saving", async (kind) => {
  const earlier = deferred<Response>();
  const current = deferred<Response>();
  vi.mocked(kind === "default" ? api.saveCommitteeDefaultRules : api.saveEligibilityRules)
    .mockReturnValueOnce(earlier.promise).mockReturnValueOnce(current.promise);
  const onUpdated = vi.fn();
  const view = render(editor(kind, 1, onUpdated));
  const input = await screen.findByRole("textbox", { name: "Min adult age" });
  fireEvent.submit(input.closest("form")!);
  view.rerender(editor(kind, 2, onUpdated));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Min adult age" })).toHaveValue("30"));
  fireEvent.submit(screen.getByRole("textbox", { name: "Min adult age" }).closest("form")!);
  await act(async () => { earlier.resolve(accepted(kind)); });
  expect(screen.getByRole("textbox", { name: "Min adult age" })).toHaveValue("30");
  expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  expect(onUpdated).not.toHaveBeenCalled();
  await act(async () => { current.resolve(accepted(kind, 30)); });
  expect(onUpdated).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Saved" })).toBeEnabled();
});

it.each(["default", "mine"])("adopts normalization for an unchanged %s draft", async (kind) => {
  vi.mocked(kind === "default" ? api.saveCommitteeDefaultRules : api.saveEligibilityRules)
    .mockResolvedValue(accepted(kind, 20));
  render(editor(kind, 1));
  const input = await screen.findByRole("textbox", { name: "Min adult age" });
  await act(async () => { fireEvent.submit(input.closest("form")!); });
  expect(input).toHaveValue("20");
  expect(screen.getByRole("button", { name: "Saved" })).toBeEnabled();
});

it.each(["default", "mine"])("allows retry after a rejected %s save", async (kind) => {
  vi.mocked(kind === "default" ? api.saveCommitteeDefaultRules : api.saveEligibilityRules)
    .mockRejectedValueOnce(new Error("offline"));
  render(editor(kind, 1));
  const input = await screen.findByRole("textbox", { name: "Min adult age" });
  await act(async () => { fireEvent.submit(input.closest("form")!); });
  expect(screen.getByRole("button", { name: /Save .*rules|Save committee defaults/ })).toBeEnabled();
  expect(input).toHaveValue("18");
});

it("serializes save and reset while preserving edits made during reset", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.resetEligibilityRules).mockReturnValueOnce(pending.promise);
  render(editor("mine", 1));
  const input = await screen.findByRole("textbox", { name: "Min adult age" });
  fireEvent.click(screen.getByRole("button", { name: "Reset to committee default" }));
  fireEvent.change(input, { target: { value: "25" } });
  fireEvent.submit(input.closest("form")!);
  expect(api.saveEligibilityRules).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Resetting" })).toBeDisabled();
  await act(async () => { pending.resolve(Response.json({ rules: rules(18), isDefault: true })); });
  expect(input).toHaveValue("25");
  expect(screen.getByText(/You're using the committee default/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save eligibility rules" })).toBeEnabled();
});
