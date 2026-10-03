import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/auth";
import { useSession } from "./useSession";

vi.mock("../api/auth", () => ({ fetchAuthState: vi.fn(), logout: vi.fn() }));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchAuthState).mockResolvedValue({
    user: { id: 1, email: "member@example.com", displayName: "Synthetic member", role: "member", avatarUrl: null },
    emailSignInEnabled: true,
  });
});

it.each(["http", "network"])("retains the committee session on a %s logout failure", async (failure) => {
  if (failure === "http") vi.mocked(api.logout).mockResolvedValue(new Response(null, { status: 503 }));
  else vi.mocked(api.logout).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.user?.id).toBe(1));
  let error: string | null = null;
  await act(async () => { error = await result.current.logout(); });
  expect(error).toContain("Could not sign out");
  expect(result.current.user?.id).toBe(1);
});

it("clears the committee session only after confirmed logout", async () => {
  vi.mocked(api.logout).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.user?.id).toBe(1));
  await act(async () => { expect(await result.current.logout()).toBeNull(); });
  expect(result.current.user).toBeNull();
});
