import { useEffect, useRef, useState } from "react";

import * as api from "../api/auth";
import { useRequestScope } from "./useRequestScope";
import type { AuthRedirect } from "../authRedirect";
import {
  retryForServiceRecovery,
  type ServiceRecoveryStage,
} from "../serviceRecovery";
import type { CurrentUser } from "../types";

export type SignInState =
  | "idle"
  | "requesting"
  | "emailSent"
  | "exchanging"
  | "googleDenied"
  | "staleLink"
  | "invalidLink"
  | "requestFailed"
  | "connectionFailed";

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
  const [userLoadRecovery, setUserLoadRecovery] = useState<ServiceRecoveryStage | null>(null);
  const [linkConflict, setLinkConflict] = useState<CommitteeLinkConflict | null>(null);
  const [linkedEmail, setLinkedEmail] = useState<string | null>(null);
  const [signInState, setSignInState] = useState<SignInState>(
    authRedirect.magicLinkToken
      ? "exchanging"
      : authRedirect.googleAccessDenied
        ? "googleDenied"
        : "idle",
  );
  const signInRequests = useRequestScope(authRedirect.magicLinkToken);
  const exchangeStarted = useRef(false);
  const userLoadInFlight = useRef(false);

  async function loadCurrentUser(): Promise<void> {
    if (userLoadInFlight.current) return;
    userLoadInFlight.current = true;
    setIsLoadingUser(true);
    setUserLoadRecovery(null);
    try {
      const authState = await retryForServiceRecovery(
        api.fetchAuthState,
        setUserLoadRecovery,
      );
      setUser(authState.user);
      setEmailSignInEnabled(authState.emailSignInEnabled);
      setUserLoadRecovery(null);
    } catch {
      setUserLoadRecovery("failed");
    } finally {
      userLoadInFlight.current = false;
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
    // A magic link is a single-use credential. Only a new token may trigger an
    // exchange; depending on the render-local workflow function would replay it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authRedirect.magicLinkToken]);

  async function inspectMagicLink(token: string): Promise<void> {
    const isCurrent = signInRequests.begin();
    try {
      const authStatePromise = api.fetchAuthState().catch(() => null);
      const response = await api.inspectCommitteeMagicLink(token);
      const authState = await authStatePromise;
      if (!isCurrent()) return;
      if (authState !== null) setEmailSignInEnabled(authState.emailSignInEnabled);
      if (!response.ok) {
        setSignInState("invalidLink");
        return;
      }
      const body = (await response.json()) as CommitteeLinkInspection;
      if (!isCurrent()) return;
      setUser(body.currentUser);
      setLinkedEmail(body.linkEmail);
      if (body.switchRequired && body.currentUser && body.linkEmail) {
        setLinkConflict({
          currentEmail: body.currentUser.email,
          linkEmail: body.linkEmail,
          linkIsValid: body.state === "valid",
        });
        setSignInState("idle");
        return;
      }
      if (body.state === "valid") {
        await exchangeMagicLink(token, false);
        return;
      }
      if (body.currentUser && body.currentUser.email === body.linkEmail) {
        setSignInState("idle");
        return;
      }
      setSignInState(body.linkEmail ? "staleLink" : "invalidLink");
    } catch {
      if (isCurrent()) setSignInState("connectionFailed");
    } finally {
      if (isCurrent()) setIsLoadingUser(false);
    }
  }

  async function exchangeMagicLink(token: string, switchCurrent: boolean): Promise<void> {
    const isCurrent = signInRequests.begin();
    try {
      setSignInState("exchanging");
      const response = await api.consumeCommitteeMagicLink(token, switchCurrent);
      if (!isCurrent()) return;
      if (!response.ok) {
        setSignInState("invalidLink");
        return;
      }
      const body: { user: CurrentUser } = await response.json();
      if (!isCurrent()) return;
      setUser(body.user);
      setLinkConflict(null);
      setLinkedEmail(null);
      setSignInState("idle");
    } catch {
      if (isCurrent()) setSignInState("connectionFailed");
    } finally {
      if (isCurrent()) setIsLoadingUser(false);
    }
  }

  function keepCurrentSession(): void {
    signInRequests.invalidate();
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
    const isCurrent = signInRequests.begin();
    setSignInState("requesting");
    const response = await api.regenerateCommitteeMagicLink(authRedirect.magicLinkToken).catch(() => null);
    if (!isCurrent()) return;
    if (response === null || !response.ok) {
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
    const isCurrent = signInRequests.begin();
    setLinkedEmail(email.trim().toLowerCase());
    setSignInState("requesting");
    const response = await api.requestCommitteeMagicLink(email, rememberDevice).catch(() => null);
    if (isCurrent()) setSignInState(response?.ok ? "emailSent" : "requestFailed");
  }

  async function retryLinkedSession(): Promise<void> {
    if (!authRedirect.magicLinkToken) return;
    setSignInState("exchanging");
    setIsLoadingUser(true);
    await inspectMagicLink(authRedirect.magicLinkToken);
  }

  function resetSignIn(): void {
    signInRequests.invalidate();
    setLinkedEmail(null);
    setSignInState("idle");
  }

  async function logout() {
    try {
      const response = await api.logout();
      if (!response.ok) return "Could not sign out. Please try again.";
      signInRequests.reset();
      setUser(null);
      return null;
    } catch {
      return "Could not sign out. Please try again.";
    }
  }

  return {
    user,
    emailSignInEnabled,
    linkConflict,
    linkedEmail,
    isAdmin: user?.role === "admin",
    isLoadingUser,
    userLoadRecovery,
    signInState,
    requestMagicLink,
    keepCurrentSession,
    openLinkedSession,
    emailNewLinkedSession,
    retryLinkedSession,
    resetSignIn,
    logout,
  };
}
