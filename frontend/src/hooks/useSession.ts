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

  const [sessionChanged, setSessionChanged] = useState(false);
  const identityReads = useRequestScope();
  const userRef = useRef(user);
  userRef.current = user;
  const revalidationPending = useRef(false);
  async function revalidateSession() {
    if (revalidationPending.current || userRef.current === null) return;
    revalidationPending.current = true;
    const isCurrent = identityReads.begin();
    try {
      const state = await api.fetchAuthState();
      if (isCurrent() && (state.user?.id !== userRef.current?.id || state.user?.role !== userRef.current?.role)) {
        setSessionChanged(true);
      }
    } catch { /* Identity headers still protect every action while offline. */ }
    finally { revalidationPending.current = false; }
  }
  const revalidateRef = useRef(revalidateSession);
  revalidateRef.current = revalidateSession;
  useEffect(() => {
    if (!user) return;
    const visible = () => { if (document.visibilityState === "visible") void revalidateRef.current(); };
    const storage = (event: StorageEvent) => { if (event.key === "penta-session-change:committee") void revalidateRef.current(); };
    const changed = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.kind === "committee") {
        if (detail.reason === "mismatch") setSessionChanged(true);
        else void revalidateRef.current();
      }
    };
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("storage", storage);
    window.addEventListener("penta-session-changed", changed);
    return () => {
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("storage", storage);
      window.removeEventListener("penta-session-changed", changed);
    };
  }, [user]);

  async function acceptSessionChange() {
    const isCurrent = identityReads.begin();
    try {
      const state = await api.fetchAuthState();
      if (!isCurrent()) return false;
      signInRequests.reset();
      setUser(state.user);
      setSessionChanged(false);
      return true;
    } catch { return false; }
  }

  async function loadCurrentUser(): Promise<void> {
    if (userLoadInFlight.current) return;
    userLoadInFlight.current = true;
    const isCurrent = identityReads.begin();
    setIsLoadingUser(true);
    setUserLoadRecovery(null);
    try {
      const authState = await retryForServiceRecovery(
        api.fetchAuthState,
        setUserLoadRecovery,
      );
      if (!isCurrent()) return;
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
      userRef.current = body.currentUser;
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
      identityReads.invalidate();
      const response = await api.consumeCommitteeMagicLink(token, switchCurrent, userRef.current?.id ?? null);
      if (!isCurrent()) return;
      if (!response.ok) {
        setSignInState("invalidLink");
        return;
      }
      const body: { user: CurrentUser } = await response.json();
      if (!isCurrent()) return;
      identityReads.invalidate();
      setSessionChanged(false);
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
      identityReads.invalidate();
      const response = await api.logout(userRef.current?.id ?? null);
      if (!response.ok) return "Could not sign out. Please try again.";
      identityReads.invalidate();
      signInRequests.reset();
      setSessionChanged(false);
      setUser(null);
      return null;
    } catch {
      return "Could not sign out. Please try again.";
    }
  }

  return {
    user,
    sessionChanged,
    acceptSessionChange,
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
