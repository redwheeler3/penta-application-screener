import { useEffect, useLayoutEffect, useRef, useState } from "react";

import * as api from "../api";
import type { ApplicationDetail, ViewTab } from "../types";

type BrowserLocation = {
  screenerLocation: true;
  tab: ViewTab;
  applicantId?: number;
  retainedApplicant?: boolean;
};

function isBrowserLocation(value: unknown): value is BrowserLocation {
  return (
    typeof value === "object" &&
    value !== null &&
    "screenerLocation" in value &&
    (value as BrowserLocation).screenerLocation === true &&
    "tab" in value
  );
}

function replaceLocation(location: BrowserLocation) {
  window.history.replaceState(location, "", window.location.pathname);
}

function pushLocation(location: BrowserLocation) {
  window.history.pushState(location, "", window.location.pathname);
}

export function useNavigation(options: {
  loadRanking: () => Promise<boolean>;
  onError: (message: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<ViewTab>("applications");
  const [selectedApplication, setSelectedApplication] = useState<ApplicationDetail | null>(null);
  const [selectedApplicationReadOnly, setSelectedApplicationReadOnly] = useState(false);
  const loadRankingRef = useRef(options.loadRanking);
  const onErrorRef = useRef(options.onError);
  loadRankingRef.current = options.loadRanking;
  onErrorRef.current = options.onError;

  const scrolledDetailId = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (!selectedApplication) {
      scrolledDetailId.current = null;
      return;
    }
    if (scrolledDetailId.current === selectedApplication.id) return;
    scrolledDetailId.current = selectedApplication.id;
    document.querySelector(".app-detail")?.scrollIntoView({ block: "start" });
  }, [selectedApplication]);

  useEffect(() => {
    replaceLocation({ screenerLocation: true, tab: "applications" });

    const onPopState = (event: PopStateEvent) => {
      if (!isBrowserLocation(event.state)) return;
      const location = event.state;
      setSelectedApplication(null);
      setSelectedApplicationReadOnly(Boolean(location.retainedApplicant));
      setActiveTab(location.tab);
      if (location.tab === "ranking") void loadRankingRef.current();
      if (!location.applicantId) return;

      const loadApplication = location.retainedApplicant
        ? api.fetchRetainedApplication
        : api.fetchApplication;
      void loadApplication(location.applicantId)
        .then(setSelectedApplication)
        .catch(() => onErrorRef.current("Couldn't load that applicant. Please try again."));
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  async function viewApplication(id: number) {
    try {
      const application = await api.fetchApplication(id);
      if (selectedApplication?.id === id) {
        setSelectedApplication(application);
        return;
      }
      pushLocation({ screenerLocation: true, tab: activeTab, applicantId: id });
      setSelectedApplication(application);
      setSelectedApplicationReadOnly(false);
    } catch {
      options.onError("Couldn't load that applicant. Please try again.");
    }
  }

  async function viewRetainedApplication(id: number) {
    try {
      const application = await api.fetchRetainedApplication(id);
      pushLocation({
        screenerLocation: true,
        tab: "adminSettings",
        applicantId: id,
        retainedApplicant: true,
      });
      setSelectedApplication(application);
      setSelectedApplicationReadOnly(true);
    } catch {
      options.onError("Couldn't load that retained application.");
    }
  }

  function backToList() {
    if (isBrowserLocation(window.history.state) && window.history.state.applicantId) {
      window.history.back();
      return;
    }
    setSelectedApplication(null);
  }

  function navigateToView(tab: ViewTab) {
    if (activeTab === tab && !selectedApplication) return;
    pushLocation({ screenerLocation: true, tab });
    setSelectedApplication(null);
    setActiveTab(tab);
    if (tab === "ranking") void options.loadRanking();
  }

  function openAdminSetup() {
    setActiveTab("adminSettings");
    replaceLocation({ screenerLocation: true, tab: "adminSettings" });
  }

  return {
    activeTab,
    selectedApplication,
    selectedApplicationReadOnly,
    setSelectedApplication,
    viewApplication,
    viewRetainedApplication,
    backToList,
    navigateToView,
    openAdminSetup,
  };
}
