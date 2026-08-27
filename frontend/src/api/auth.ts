import type { CurrentUser } from "../types";
import { getJson, request, url } from "./client";

export type AuthState = {
  user: CurrentUser | null;
  emailSignInEnabled: boolean;
};

export function fetchAuthState(): Promise<AuthState> {
  return getJson<AuthState>("/auth/me");
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

export function consumeCommitteeMagicLink(token: string, switchCurrent = false): Promise<Response> {
  return request("/auth/magic-link/consume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, switchCurrent }),
  });
}

export function regenerateCommitteeMagicLink(token: string): Promise<Response> {
  return request("/auth/magic-link/regenerate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function logout(): Promise<Response> {
  return request("/auth/logout", { method: "POST" });
}

