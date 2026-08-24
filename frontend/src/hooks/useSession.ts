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
  | "staleLink"
  | "invalidLink"
  | "requestFailed";

export type CommitteeLinkConflict = {
  currentEmail: string;
  linkEmail: string;
  linkIsValid: boolean;
  newLinkSent?: boolean;
};

type CommitteeLinkInspection = {
  state: "valid" | "expired" | "used" | "replaced" | "invalid";
  currentUser: CurrentUser | null;
  linkEmail: string | null;
  switchRequired: boolean;
};

export function useSession(authRedirect: AuthRedirect) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [emailSignInEnabled, setEmailSignInEnabled] = useState(false);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [userLoadFailed, setUserLoadFailed] = useState(false);
  const [linkConflict, setLinkConflict] = useState<CommitteeLinkConflict | null>(null);
  const [linkedEmail, setLinkedEmail] = useState<string | null>(null);
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
    void inspectMagicLink(authRedirect.magicLinkToken);
  }, [authRedirect.magicLinkToken]);

  async function inspectMagicLink(token: string): Promise<void> {
    const authStatePromise = api.fetchAuthState().catch(() => null);
    const response = await api.inspectCommitteeMagicLink(token);
    const authState = await authStatePromise;
    if (authState !== null) setEmailSignInEnabled(authState.emailSignInEnabled);
    if (!response.ok) {
      setSignInState("invalidLink");
      setIsLoadingUser(false);
      return;
    }
    const body = (await response.json()) as CommitteeLinkInspection;
    setUser(body.currentUser);
    setLinkedEmail(body.linkEmail);
    if (body.switchRequired && body.currentUser && body.linkEmail) {
      setLinkConflict({
        currentEmail: body.currentUser.email,
        linkEmail: body.linkEmail,
        linkIsValid: body.state === "valid",
      });
      setSignInState("idle");
      setIsLoadingUser(false);
      return;
    }
    if (body.state === "valid") {
      await exchangeMagicLink(token, false);
      return;
    }
    if (body.currentUser && body.currentUser.email === body.linkEmail) {
      setSignInState("idle");
      setIsLoadingUser(false);
      return;
    }
    setSignInState(body.linkEmail ? "staleLink" : "invalidLink");
    setIsLoadingUser(false);
  }

  async function exchangeMagicLink(token: string, switchCurrent: boolean): Promise<void> {
    setSignInState("exchanging");
    const response = await api.consumeCommitteeMagicLink(token, switchCurrent);
    if (!response.ok) {
      setSignInState("invalidLink");
      setIsLoadingUser(false);
      return;
    }
    const body: { user: CurrentUser } = await response.json();
    setUser(body.user);
    setLinkConflict(null);
    setLinkedEmail(null);
    setSignInState("idle");
    setIsLoadingUser(false);
  }

  function keepCurrentSession(): void {
    setLinkConflict(null);
    setLinkedEmail(null);
    setSignInState("idle");
  }

  async function openLinkedSession(): Promise<void> {
    if (!authRedirect.magicLinkToken) return;
    await exchangeMagicLink(authRedirect.magicLinkToken, true);
  }

  async function emailNewLinkedSession(): Promise<void> {
    if (!authRedirect.magicLinkToken) return;
    setSignInState("requesting");
    const response = await api.regenerateCommitteeMagicLink(authRedirect.magicLinkToken);
    if (!response.ok) {
      setSignInState("requestFailed");
      return;
    }
    if (linkConflict) {
      setLinkConflict((current) => current ? { ...current, newLinkSent: true } : null);
      setSignInState("idle");
    } else {
      setSignInState("emailSent");
    }
  }

  async function requestMagicLink(email: string, rememberDevice: boolean): Promise<void> {
    setSignInState("requesting");
    const response = await api.requestCommitteeMagicLink(email, rememberDevice);
    setSignInState(response.ok ? "emailSent" : "requestFailed");
  }

  function resetSignIn(): void {
    setLinkedEmail(null);
    setSignInState("idle");
  }

  async function logout() {
    await api.logout();
    setUser(null);
  }

  return {
    user,
    emailSignInEnabled,
    linkConflict,
    linkedEmail,
    isAdmin: user?.role === "admin",
    isLoadingUser,
    userLoadFailed,
    signInState,
    loadCurrentUser,
    requestMagicLink,
    keepCurrentSession,
    openLinkedSession,
    emailNewLinkedSession,
    resetSignIn,
    logout,
  };
}
