import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/auth";
import { useSession } from "./useSession";
import { deferred } from "../testSupport";

vi.mock("../api/auth", () => ({
  fetchAuthState: vi.fn(), logout: vi.fn(), requestCommitteeMagicLink: vi.fn(),
  inspectCommitteeMagicLink: vi.fn(), consumeCommitteeMagicLink: vi.fn(), regenerateCommitteeMagicLink: vi.fn(),
}));

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

it("releases an email request after a network failure", async () => {
  vi.mocked(api.requestCommitteeMagicLink).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.isLoadingUser).toBe(false));
  await act(() => result.current.requestMagicLink("member@example.com", false));
  expect(result.current.signInState).toBe("requestFailed");
  expect(result.current.linkedEmail).toBe("member@example.com");
});

it.each(["inspection", "exchange"])("allows a failed link %s to be checked again", async (failure) => {
  const inspected = { state: "valid", currentUser: null, linkEmail: "member@example.com", switchRequired: false };
  vi.mocked(api.inspectCommitteeMagicLink).mockImplementation(async () => Response.json(inspected));
  vi.mocked(api.consumeCommitteeMagicLink).mockRejectedValue(new Error("Synthetic network failure"));
  if (failure === "inspection") vi.mocked(api.inspectCommitteeMagicLink).mockRejectedValueOnce(new Error("Synthetic network failure"));
  const { result } = renderHook(() => useSession({ magicLinkToken: "synthetic-token", googleAccessDenied: false }));
  await waitFor(() => expect(result.current.signInState).toBe("connectionFailed"));
  expect(result.current.isLoadingUser).toBe(false);
  vi.mocked(api.consumeCommitteeMagicLink).mockResolvedValue(Response.json({ user: {
    id: 2, email: "member@example.com", role: "member", displayName: "Synthetic member", avatarUrl: null,
  } }));
  await act(() => result.current.retryLinkedSession());
  expect(result.current.user?.id).toBe(2);
  expect(result.current.signInState).toBe("idle");
  expect(api.consumeCommitteeMagicLink).toHaveBeenLastCalledWith("synthetic-token", false, null);
});

it("releases a failed replacement-link request", async () => {
  vi.mocked(api.inspectCommitteeMagicLink).mockResolvedValue(Response.json({
    state: "expired", currentUser: null, linkEmail: "member@example.com", switchRequired: false,
  }));
  vi.mocked(api.regenerateCommitteeMagicLink).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderHook(() => useSession({ magicLinkToken: "synthetic-token", googleAccessDenied: false }));
  await waitFor(() => expect(result.current.signInState).toBe("staleLink"));
  await act(() => result.current.emailNewLinkedSession());
  expect(result.current.signInState).toBe("requestFailed");
});

it("does not restore an email request that was reset while pending", async () => {
  const request = deferred<Response>();
  vi.mocked(api.requestCommitteeMagicLink).mockReturnValue(request.promise);
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.isLoadingUser).toBe(false));
  let pending!: Promise<void>;
  act(() => { pending = result.current.requestMagicLink("member@example.com", false); });
  act(() => result.current.resetSignIn());
  await act(async () => { request.resolve(new Response(null, { status: 204 })); await pending; });
  expect(result.current.signInState).toBe("idle");
  expect(result.current.linkedEmail).toBeNull();
});

it("freezes a changed session without replacing the old account until acknowledged", async () => {
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.user?.id).toBe(1));
  vi.mocked(api.fetchAuthState).mockResolvedValue({ user: {
    id: 2, email: "other@example.test", displayName: "Other", role: "member", avatarUrl: null,
  }, emailSignInEnabled: true });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.sessionChanged).toBe(true));
  expect(result.current.user?.id).toBe(1);
  await act(() => result.current.acceptSessionChange());
  expect(result.current.user?.id).toBe(2);
  expect(result.current.sessionChanged).toBe(false);
});

it("keeps session recovery and old-account work available if continuation cannot refresh", async () => {
  const { result } = renderHook(() => useSession({ magicLinkToken: null, googleAccessDenied: false }));
  await waitFor(() => expect(result.current.user?.id).toBe(1));
  act(() => window.dispatchEvent(new CustomEvent("penta-session-changed", {
    detail: { kind: "committee", reason: "mismatch" },
  })));
  vi.mocked(api.fetchAuthState).mockRejectedValue(new Error("offline"));
  await act(async () => expect(await result.current.acceptSessionChange()).toBe(false));
  expect(result.current.user?.id).toBe(1);
  expect(result.current.sessionChanged).toBe(true);
});
