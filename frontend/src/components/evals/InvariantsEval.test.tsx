import { act, fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { deferred, renderCommittee as render } from "../../testSupport";
import { InvariantsEval } from "./InvariantsEval";
import type { InvariantsResult } from "../../types";

const api = vi.hoisted(() => ({ fetchEvalInvariants: vi.fn(), rebaselineEval: vi.fn() }));
vi.mock("../../api/evals", () => ({ createApi: () => api }));
it.each([true, false])("keeps a successful re-baseline when the initial read finishes first=%s", async oldFirst => {
  const initial = deferred<InvariantsResult>();
  const old = { hasFixture: true, dimensions: 3, invariants: [] };
  const fresh = { hasFixture: true, dimensions: 7, invariants: [{ check: "Synthetic", passed: false, violations: ["Synthetic breach"] }] };
  api.fetchEvalInvariants.mockReturnValue(initial.promise);
  api.rebaselineEval.mockResolvedValue(Response.json(fresh));
  render(<InvariantsEval />);
  if (oldFirst) await act(async () => initial.resolve(old));
  fireEvent.click(screen.getByText("Re-baseline from latest Rank"));
  fireEvent.click(screen.getByRole("button", { name: "Re-baseline" }));
  await screen.findByText("Synthetic breach");
  if (!oldFirst) await act(async () => initial.resolve(old));
  expect(screen.getByText("7 dimensions in the baseline")).toBeVisible();
  expect(screen.getByText("Synthetic breach")).toBeVisible();
});
it("releases the action and preserves the confirmed result on a failed write", async () => {
  api.fetchEvalInvariants.mockResolvedValue({hasFixture:true, dimensions:3, invariants:[]});
  api.rebaselineEval.mockRejectedValue(new Error("Synthetic failure"));
  render(<InvariantsEval />);
  await screen.findByText("3 dimensions in the baseline");
  fireEvent.click(screen.getByText("Re-baseline from latest Rank"));
  fireEvent.click(screen.getByRole("button", { name: "Re-baseline" }));
  await screen.findByText("Synthetic failure");
  expect(screen.getByText("3 dimensions in the baseline")).toBeVisible();
  expect(screen.getByText("Re-baseline from latest Rank")).toBeEnabled();
});
