import { useEffect, useRef, useState } from "react";

import * as api from "../api";
import type { AuthRedirect } from "../authRedirect";
import { retryWithBackoff } from "../retry";
import type { CurrentUser } from "../types";

export type SignInState =
  | "idle"
  | "requesting"
  | "emailSent"
  | "exchanging"
  | "googleDenied"
  | "invalidLink"
  | "requestFailed";

export function useSession(authRedirect: AuthRedirect) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [emailSignInEnabled, setEmailSignInEnabled] = useState(false);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [userLoadFailed, setUserLoadFailed] = useState(false);
  const [signInState, setSignInState] = useState<SignInState>(
    authRedirect.magicLinkToken
      ? "exchanging"
      : authRedirect.googleAccessDenied
        ? "googleDenied"
        : "idle",
  );
  const exchangeStarted = useRef(false);

  async function loadCurrentUser(): Promise<void> {
    setIsLoadingUser(true);
    setUserLoadFailed(false);
    try {
      const authState = await retryWithBackoff(api.fetchAuthState, 3);
      setUser(authState.user);
      setEmailSignInEnabled(authState.emailSignInEnabled);
    } catch {
      setUserLoadFailed(true);
    } finally {
      setIsLoadingUser(false);
    }
  }

  useEffect(() => {
    if (!authRedirect.magicLinkToken) {
      void loadCurrentUser();
      return;
    }

    // Strict Mode re-runs effects in development. A magic link is single-use, so exchange it
    // only once while still allowing the first request to update this mounted root component.
    if (exchangeStarted.current) return;
    exchangeStarted.current = true;
    void api
      .fetchAuthState()
      .then((authState) => setEmailSignInEnabled(authState.emailSignInEnabled))
      .catch(() => undefined);
    void exchangeMagicLink(authRedirect.magicLinkToken);
  }, [authRedirect.magicLinkToken]);

  async function exchangeMagicLink(token: string): Promise<void> {
    const response = await api.consumeCommitteeMagicLink(token);
    if (!response.ok) {
      setSignInState("invalidLink");
      setIsLoadingUser(false);
      return;
    }
    const body: { user: CurrentUser } = await response.json();
    setUser(body.user);
    setSignInState("idle");
    setIsLoadingUser(false);
  }

  async function requestMagicLink(email: string): Promise<void> {
    setSignInState("requesting");
    const response = await api.requestCommitteeMagicLink(email);
    setSignInState(response.ok ? "emailSent" : "requestFailed");
  }

  function resetSignIn(): void {
    setSignInState("idle");
  }

  async function logout() {
    await api.logout();
    setUser(null);
  }

  return {
    user,
    emailSignInEnabled,
    isAdmin: user?.role === "admin",
    isLoadingUser,
    userLoadFailed,
    signInState,
    loadCurrentUser,
    requestMagicLink,
    resetSignIn,
    logout,
  };
}
