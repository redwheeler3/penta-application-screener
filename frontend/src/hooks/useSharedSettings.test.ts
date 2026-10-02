import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/settings";
import { deferred } from "../testSupport";
import type { AppSettings, SettingsResponse } from "../types";
import { useSharedSettings } from "./useSharedSettings";

vi.mock("../api/settings", () => ({ saveSettings: vi.fn(), fetchSettings: vi.fn() }));

const settings: AppSettings = { ai: {
  region: "test", screeningModel: "test", screeningReasoningEffort: "none",
  dimensionScoringModel: "test", dimensionScoringReasoningEffort: "none",
  discoveryModel: "test", discoveryReasoningEffort: "none",
  decomposeModel: "test", decomposeReasoningEffort: "none",
  matchModel: "test", matchReasoningEffort: "none",
  consolidateModel: "test", consolidateReasoningEffort: "none",
  discoveryFanOut: 5, consolidateCorrelationThreshold: 0.9, spendingCapUsd: 10, maxWorkers: 3,
} };
const payload = (value: AppSettings): SettingsResponse => ({
  settings: value, aiPasses: [], aiModelOptions: [],
});
const withCap = (spendingCapUsd: number): AppSettings => ({ ai: { ...settings.ai, spendingCapUsd } });

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchSettings).mockResolvedValue(payload(settings));
});

it("acknowledges the submitted snapshot while preserving edits made during a save", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.saveSettings).mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useSharedSettings({ dashboardReady: false }));
  await act(() => result.current.load());
  let saving!: Promise<boolean>;
  act(() => { saving = result.current.save(); });
  act(() => result.current.setDraft(withCap(22)));
  await act(async () => {
    pending.resolve(Response.json(payload(settings)));
    expect(await saving).toBe(true);
  });
  expect(api.saveSettings).toHaveBeenCalledWith(settings);
  expect(result.current.saved?.settings.ai.spendingCapUsd).toBe(10);
  expect(result.current.draft?.ai.spendingCapUsd).toBe(22);
  expect(result.current.isSaving).toBe(false);
});

it("accepts server normalization when the submitted draft has not been edited", async () => {
  vi.mocked(api.saveSettings).mockResolvedValue(Response.json(payload(withCap(9.99))));
  const { result } = renderHook(() => useSharedSettings({ dashboardReady: false }));
  await act(() => result.current.load());
  await act(async () => { expect(await result.current.save()).toBe(true); });
  expect(result.current.saved?.settings.ai.spendingCapUsd).toBe(9.99);
  expect(result.current.draft?.ai.spendingCapUsd).toBe(9.99);
});

it("does not acknowledge or discard draft edits when a save fails", async () => {
  vi.mocked(api.saveSettings).mockResolvedValue(new Response(null, { status: 503 }));
  const { result } = renderHook(() => useSharedSettings({ dashboardReady: false }));
  await act(() => result.current.load());
  act(() => result.current.setDraft(withCap(22)));
  await act(async () => { expect(await result.current.save()).toBe(false); });
  expect(result.current.saved?.settings.ai.spendingCapUsd).toBe(10);
  expect(result.current.draft?.ai.spendingCapUsd).toBe(22);
  expect(result.current.isSaving).toBe(false);
});

it("does not let an earlier settings read roll back a completed save", async () => {
  const pending = deferred<SettingsResponse>();
  const { result } = renderHook(() => useSharedSettings({ dashboardReady: false }));
  await act(() => result.current.load());
  vi.mocked(api.fetchSettings).mockReturnValueOnce(pending.promise);
  let loading!: Promise<void>;
  act(() => { loading = result.current.load(); });
  act(() => result.current.setDraft(withCap(22)));
  vi.mocked(api.saveSettings).mockResolvedValue(Response.json(payload(withCap(22))));
  await act(() => result.current.save());
  await act(async () => { pending.resolve(payload(settings)); await loading; });
  expect(result.current.saved?.settings.ai.spendingCapUsd).toBe(22);
  expect(result.current.draft?.ai.spendingCapUsd).toBe(22);
});
