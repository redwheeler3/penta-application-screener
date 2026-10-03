import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/openings";
import { deferred } from "../../testSupport";
import type { Opening } from "../../types";
import { OpeningEditor } from "./OpeningEditor";

vi.mock("../../api/openings", () => ({ updateOpening: vi.fn(), fetchOpenings: vi.fn(), previewOpening: vi.fn(), createOpening: vi.fn() }));
const opening = { id: 1, intakeMode: "applications", unitSizeBedrooms: 2, housingChargeCents: 100_000,
  applicationOpenDate: "2026-10-01", applicationCloseDate: "2026-10-31", moveInDate: "2026-11-30" } as Opening;
const values = { unitSizeBedrooms: 2, housingChargeCents: 100_000,
  applicationOpenDate: "2026-10-01", applicationCloseDate: "2026-10-31", moveInDate: "2026-11-30" };
function setup() {
  const onSaved = vi.fn();
  const onError = vi.fn();
  function Host() {
    const [busy, setBusy] = useState(false);
    return <OpeningEditor opening={opening} busy={busy} setBusy={setBusy} onSaved={onSaved} onError={onError} onCancel={vi.fn()} />;
  }
  render(<Host />);
  return { onSaved, onError };
}
beforeEach(() => vi.resetAllMocks());

it("preserves later edits and advances only the acknowledged opening snapshot", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.updateOpening).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(Response.json({ openings: [], saved: { ...values, id: 1, housingChargeCents: 200_000 } }));
  const { onSaved } = setup();
  const charge = screen.getByRole("textbox", { name: /Monthly housing charge/ });
  fireEvent.change(charge, { target: { value: "1500" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  fireEvent.change(charge, { target: { value: "2000" } });
  await act(async () => { pending.resolve(Response.json({ openings: [], saved: { ...values, id: 1, housingChargeCents: 150_000 } })); });
  expect(charge).toHaveValue("2000");
  expect(onSaved).toHaveBeenLastCalledWith([], "Opening updated. Your newer edits are still unsaved.", false);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save changes" })); });
  expect(api.updateOpening).toHaveBeenLastCalledWith(1, { ...values, housingChargeCents: 150_000 }, { ...values, housingChargeCents: 200_000 });
  expect(onSaved).toHaveBeenLastCalledWith([], "Opening updated.", true);
});

it("keeps stale edits until saved facts are explicitly reloaded", async () => {
  vi.mocked(api.updateOpening).mockResolvedValue(Response.json({ code: "stale_opening", detail: "Opening changed." }, { status: 409 }));
  vi.mocked(api.fetchOpenings).mockResolvedValue([{ ...opening, housingChargeCents: 180_000 }]);
  setup();
  const charge = screen.getByRole("textbox", { name: /Monthly housing charge/ });
  fireEvent.change(charge, { target: { value: "1500" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save changes" })); });
  expect(charge).toHaveValue("1500");
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reload saved facts" })); });
  expect(charge).toHaveValue("1800");
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
});

it("retains edits and releases controls after an unconfirmed save", async () => {
  vi.mocked(api.updateOpening).mockRejectedValue(new Error("Synthetic network failure"));
  const { onError } = setup();
  fireEvent.change(screen.getByRole("textbox", { name: /Monthly housing charge/ }), { target: { value: "1500" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save changes" })); });
  expect(onError).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  expect(screen.getByRole("textbox", { name: /Monthly housing charge/ })).toHaveValue("1500");
});

it("does not report a save into an editor that has been closed", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.updateOpening).mockReturnValue(pending.promise);
  const { onSaved } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(api.updateOpening).toHaveBeenCalledOnce());
  // The entire admin surface can be left while a request is pending.
  const { cleanup } = await import("@testing-library/react");
  cleanup();
  await act(async () => { pending.resolve(Response.json({ openings: [], saved: { ...values, id: 1 } })); });
  expect(onSaved).not.toHaveBeenCalled();
});
