import type { CurrentUser } from "../types";
import { credentialRequest, getJson, identityClient, request, signalSessionChange, url } from "./client";

export type AuthState = {
  user: CurrentUser | null;
  emailSignInEnabled: boolean;
};

export function fetchAuthState(signal?: AbortSignal): Promise<AuthState> {
  return getJson<AuthState>("/auth/me", signal);
}
export function googleSignInUrl(rememberDevice = false): string {
  return url(`/auth/google/login?remember_device=${rememberDevice}`);
}

export function requestCommitteeMagicLink(email: string, rememberDevice: boolean): Promise<Response> {
  return request("/auth/magic-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, rememberDevice }),
  });
}

export function inspectCommitteeMagicLink(token: string): Promise<Response> {
  return request("/auth/magic-link/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function consumeCommitteeMagicLink(token: string, switchCurrent = false, expectedUserId: number | null = null): Promise<Response> {
  return credentialRequest("committee", "/auth/magic-link/consume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, switchCurrent }),
  }, identityClient({ kind: "committee", id: expectedUserId }));
}

export function regenerateCommitteeMagicLink(token: string): Promise<Response> {
  return request("/auth/magic-link/regenerate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export async function logout(expectedUserId: number | null): Promise<Response> {
  const response = await identityClient({ kind: "committee", id: expectedUserId }).request("/auth/logout", { method: "POST" });
  if (response.ok) signalSessionChange("committee");
  return response;
}
