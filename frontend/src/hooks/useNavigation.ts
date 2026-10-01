import { useEffect, useLayoutEffect, useRef, useState } from "react";

import * as api from "../api/applications";
import type { ApplicationDetail, ViewTab } from "../types";
import { useRequestScope } from "./useRequestScope";

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
  openingId: number | null;
  loadRanking: () => Promise<boolean>;
  onError: (message: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<ViewTab>("applications");
  const [selectedApplication, setSelectedApplication] = useState<ApplicationDetail | null>(null);
  const [selectedApplicationReadOnly, setSelectedApplicationReadOnly] = useState(false);
  const requests = useRequestScope();
  const requestedOpening = useRef(options.openingId);
  const currentOpening = useRef(options.openingId);
  if (currentOpening.current !== options.openingId) {
    currentOpening.current = options.openingId;
    // A cross-opening navigation can start just before React renders the selected
    // opening. Preserve that deliberate request, but cancel requests for any other opening.
    if (requestedOpening.current !== options.openingId) requests.invalidate();
  }
  const loadRankingRef = useRef(options.loadRanking);
  const onErrorRef = useRef(options.onError);
  const openingIdRef = useRef(options.openingId);
  loadRankingRef.current = options.loadRanking;
  onErrorRef.current = options.onError;
  openingIdRef.current = options.openingId;

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
      const isCurrent = requests.begin();
      requestedOpening.current = openingIdRef.current;
      const location = event.state;
      setSelectedApplication(null);
      setSelectedApplicationReadOnly(Boolean(location.retainedApplicant));
      setActiveTab(location.tab);
      if (location.tab === "ranking") void loadRankingRef.current();
      if (!location.applicantId) return;

      const loadApplication = location.retainedApplicant
        ? api.fetchRetainedApplication
        : (id: number) => {
            if (openingIdRef.current === null) return Promise.reject();
            return api.fetchApplication(id, openingIdRef.current);
          };
      void loadApplication(location.applicantId)
        .then((application) => {
          if (!isCurrent()) return;
          setSelectedApplication(application);
          setSelectedApplicationReadOnly(Boolean(location.retainedApplicant));
        })
        .catch(() => {
          if (isCurrent()) onErrorRef.current("Couldn't load that applicant. Please try again.");
        });
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [requests]);

  async function viewApplication(id: number, openingId = options.openingId) {
    if (openingId === null) return;
    if (openingId === options.openingId && currentOpening.current !== options.openingId) return;
    requestedOpening.current = openingId;
    const isCurrent = requests.begin();
    try {
      const application = await api.fetchApplication(id, openingId);
      if (!isCurrent()) return;
      if (selectedApplication?.id === id) {
        setSelectedApplication(application);
        return;
      }
      pushLocation({ screenerLocation: true, tab: activeTab, applicantId: id });
      setSelectedApplication(application);
      setSelectedApplicationReadOnly(false);
    } catch {
      if (isCurrent()) options.onError("Couldn't load that applicant. Please try again.");
    }
  }

  async function viewRetainedApplication(id: number) {
    requestedOpening.current = currentOpening.current;
    const isCurrent = requests.begin();
    try {
      const application = await api.fetchRetainedApplication(id);
      if (!isCurrent()) return;
      pushLocation({
        screenerLocation: true,
        tab: "adminSettings",
        applicantId: id,
        retainedApplicant: true,
      });
      setSelectedApplication(application);
      setSelectedApplicationReadOnly(true);
    } catch {
      if (isCurrent()) options.onError("Couldn't load that retained application.");
    }
  }

  function backToList() {
    requests.invalidate();
    if (isBrowserLocation(window.history.state) && window.history.state.applicantId) {
      window.history.back();
      return;
    }
    setSelectedApplication(null);
  }

  function navigateToView(tab: ViewTab) {
    requests.invalidate();
    if (activeTab === tab && !selectedApplication) return;
    pushLocation({ screenerLocation: true, tab });
    setSelectedApplication(null);
    setActiveTab(tab);
    if (tab === "ranking") void options.loadRanking();
  }

  function openAdminSetup() {
    requests.invalidate();
    setActiveTab("adminSettings");
    replaceLocation({ screenerLocation: true, tab: "adminSettings" });
  }

  return {
    activeTab,
    selectedApplication,
    selectedApplicationReadOnly,
    setSelectedApplication: (application: ApplicationDetail | null) => {
      requests.invalidate();
      setSelectedApplication(application);
    },
    viewApplication,
    viewRetainedApplication,
    backToList,
    navigateToView,
    openAdminSetup,
  };
}
