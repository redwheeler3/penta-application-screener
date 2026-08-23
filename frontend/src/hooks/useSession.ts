import { useEffect, useState } from "react";

import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type { CurrentUser } from "../types";

export function useSession() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [userLoadFailed, setUserLoadFailed] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);

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
    void loadCurrentUser();
    if (new URLSearchParams(window.location.search).get("access") === "denied") {
      setAccessDenied(true);
    }
  }, []);

  function login() {
    window.location.href = api.authLoginUrl();
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
    accessDenied,
    loadCurrentUser,
    login,
    logout,
  };
}
