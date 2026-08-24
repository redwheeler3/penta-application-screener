import { useEffect, useRef, useState } from "react";

import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type { CurrentUser } from "../types";

export type SignInState =
  | "idle"
  | "requesting"
  | "emailSent"
  | "exchanging"
  | "invalidLink"
  | "requestFailed";

export function useSession(initialMagicLinkToken: string | null) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [userLoadFailed, setUserLoadFailed] = useState(false);
  const [signInState, setSignInState] = useState<SignInState>(
    initialMagicLinkToken ? "exchanging" : "idle",
  );
  const exchangeStarted = useRef(false);

  async function loadCurrentUser(): Promise<void> {
    setIsLoadingUser(true);
    setUserLoadFailed(false);
    try {
      setUser(await retryWithBackoff(api.fetchCurrentUser, 3));
    } catch {
      setUserLoadFailed(true);
    } finally {
      setIsLoadingUser(false);
    }
  }

  useEffect(() => {
    if (!initialMagicLinkToken) {
      void loadCurrentUser();
      return;
    }

    // Strict Mode re-runs effects in development. A magic link is single-use, so exchange it
    // only once while still allowing the first request to update this mounted root component.
    if (exchangeStarted.current) return;
    exchangeStarted.current = true;
    void exchangeMagicLink(initialMagicLinkToken);
  }, [initialMagicLinkToken]);

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
