import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import * as api from "../api/applications";
import { deferred } from "../testSupport";
import type { ApplicationDetail } from "../types";
import { useNavigation } from "./useNavigation";

vi.mock("../api/applications", () => ({ fetchApplication: vi.fn() }));

it("does not reopen an applicant after navigating away from a pending detail request", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1, loadRanking: vi.fn(), onError: vi.fn() }));
  let request!: Promise<void>;
  act(() => { request = result.current.viewApplication(1); });
  act(() => result.current.navigateToView("adminSettings"));
  await act(async () => { response.resolve({ id: 1 } as ApplicationDetail); await request; });
  expect(result.current.selectedApplication).toBeNull();
  expect(result.current.activeTab).toBe("adminSettings");
  expect(window.history.state.applicantId).toBeUndefined();
});

it("preserves a deliberate cross-opening detail request as React renders the selected opening", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result, rerender } = renderHook(({ openingId }) => useNavigation({
    openingId, loadRanking: vi.fn(), onError: vi.fn(),
  }), { initialProps: { openingId: 1 } });
  let request!: Promise<void>;
  act(() => { request = result.current.viewApplication(7, 2); });
  rerender({ openingId: 2 });
  await act(async () => { response.resolve({ id: 7 } as ApplicationDetail); await request; });
  expect(result.current.selectedApplication?.id).toBe(7);
});
