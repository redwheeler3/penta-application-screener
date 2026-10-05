import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import * as api from "../api/applications";
import type { ApplicationDetail, ApplicationUpdate, ViewTab } from "../types";
import { useRequestScope, type RequestIsCurrent } from "./useRequestScope";

type BrowserLocation = {
  screenerLocation: true;
  tab: ViewTab;
  openingId: number | null;
  applicantId?: number;
  retainedApplicant?: boolean;
};

function isBrowserLocation(value: unknown): value is BrowserLocation {
  if (typeof value !== "object" || value === null) return false;
  const location = value as BrowserLocation;
  return location.screenerLocation === true
    && ["applications", "ranking", "eligibilitySettings", "adminSettings", "observability", "evals"].includes(location.tab)
    && (location.openingId === null || (Number.isInteger(location.openingId) && location.openingId > 0))
    && (location.applicantId === undefined || (Number.isInteger(location.applicantId) && location.applicantId > 0))
    && (location.retainedApplicant === undefined || typeof location.retainedApplicant === "boolean");
}

function sameLocation(left: unknown, right: BrowserLocation): boolean {
  return isBrowserLocation(left) && left.tab === right.tab && left.openingId === right.openingId
    && left.applicantId === right.applicantId
    && Boolean(left.retainedApplicant) === Boolean(right.retainedApplicant);
}

function replaceLocation(location: BrowserLocation) {
  window.history.replaceState(location, "", window.location.pathname);
}

function pushLocation(location: BrowserLocation) {
  if (!sameLocation(window.history.state, location)) {
    window.history.pushState(location, "", window.location.pathname);
  }
}

export function useNavigation(options: {
  openingId: number | null;
  selectOpening: (openingId: number, isCurrent: RequestIsCurrent) => Promise<boolean>;
  loadRanking: () => Promise<boolean>;
  onError: (message: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<ViewTab>("applications");
  const [selectedApplication, setSelectedApplication] = useState<ApplicationDetail | null>(null);
  const [selectedApplicationReadOnly, setSelectedApplicationReadOnly] = useState(false);
  const requests = useRequestScope();
  const current = useRef({ ...options, activeTab, selectedApplication });
  current.current = { ...options, activeTab, selectedApplication };
  const pendingLocation = useRef<BrowserLocation | null>(null);
  const pendingDetail = useRef<{ location: BrowserLocation; receipts: ApplicationUpdate } | null>(null);
  const requestedOpening = useRef(options.openingId);
  const renderedOpening = useRef(options.openingId);
  if (renderedOpening.current !== options.openingId) {
    renderedOpening.current = options.openingId;
    // Preserve our deliberate opening restoration; cancel detail reads if another
    // owner changes the opening instead (for example a refreshed opening list).
    if (requestedOpening.current !== options.openingId) {
      requests.invalidate();
      pendingLocation.current = null;
    }
  }

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

  const loadLocation = useCallback(async (location: BrowserLocation, addHistory: boolean): Promise<boolean> => {
    requestedOpening.current = location.openingId;
    pendingLocation.current = location;
    const reading = location.applicantId === undefined ? null
      : { location, receipts: { id: location.applicantId } as ApplicationUpdate };
    pendingDetail.current = reading;
    const isCurrent = requests.begin();
    const openingChanged = location.openingId !== current.current.openingId;
    setSelectedApplication(null);
    setSelectedApplicationReadOnly(false);
    setActiveTab(location.tab);
    try {
      const opening = location.openingId !== null && openingChanged
        ? current.current.selectOpening(location.openingId, isCurrent) : Promise.resolve(true);
      const application = location.applicantId === undefined
        ? Promise.resolve(null)
        : location.retainedApplicant
          ? api.fetchRetainedApplication(location.applicantId)
          : location.openingId !== null
            ? api.fetchApplication(location.applicantId, location.openingId)
            : Promise.reject(new Error("Missing opening"));
      // Resolve detail in parallel with the list. Publish it only after the
      // recorded opening has been accepted, without adding serial latency.
      const [selected, detail] = await Promise.all([opening, application]);
      if (!isCurrent()) return false;
      if (!selected) throw new Error("Opening unavailable");
      pendingLocation.current = null;
      if (addHistory) pushLocation(location);
      setSelectedApplication(detail && reading ? { ...detail, ...reading.receipts } : detail);
      if (pendingDetail.current === reading) pendingDetail.current = null;
      setSelectedApplicationReadOnly(Boolean(location.retainedApplicant));
      // Opening changes refresh ranking after React installs the new scoped hooks.
      // Same-opening history needs a read here.
      if (location.tab === "ranking" && !openingChanged) void current.current.loadRanking();
      return true;
    } catch {
      if (!isCurrent()) return false;
      pendingLocation.current = null;
      requests.invalidate(); // Fence a list read still pending after detail failed.
      replaceLocation({ screenerLocation: true, tab: location.tab, openingId: current.current.openingId });
      current.current.onError("Couldn't load that view. Please try again.");
      return false;
    }
  }, [requests]);

  useEffect(() => {
    replaceLocation({ screenerLocation: true, tab: "applications", openingId: current.current.openingId });
    const onPopState = (event: PopStateEvent) => {
      if (!isBrowserLocation(event.state)) return;
      // A root/retained review recorded before any opening existed has no opening
      // to restore. Use the current server-selected context and record it truthfully.
      const location = event.state.openingId === null && (!event.state.applicantId || event.state.retainedApplicant)
        ? { ...event.state, openingId: current.current.openingId } : event.state;
      replaceLocation(location);
      void loadLocation(location, false);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [loadLocation]);

  useEffect(() => {
    if (pendingLocation.current !== null) return;
    if (isBrowserLocation(window.history.state) && window.history.state.openingId === options.openingId) return;
    requests.invalidate();
    setSelectedApplication(null);
    setSelectedApplicationReadOnly(false);
    // Install the server-chosen opening into the initial root entry; keep later
    // externally changed opening/list entries truthful too.
    replaceLocation({ screenerLocation: true, tab: current.current.activeTab, openingId: options.openingId });
  }, [options.openingId, requests]);

  async function viewApplication(id: number, openingId = current.current.openingId) {
    if (openingId === null) return;
    await loadLocation({ screenerLocation: true, tab: current.current.activeTab, openingId, applicantId: id }, true);
  }

  async function viewRetainedApplication(id: number) {
    await loadLocation({ screenerLocation: true, tab: "adminSettings", openingId: current.current.openingId,
      applicantId: id, retainedApplicant: true }, true);
  }

  function changeOpening(openingId: number): Promise<boolean> {
    return loadLocation({ screenerLocation: true, tab: current.current.activeTab, openingId }, true);
  }

  function backToList() {
    requests.invalidate();
    pendingLocation.current = null;
    if (isBrowserLocation(window.history.state) && window.history.state.applicantId) {
      window.history.back();
      return;
    }
    setSelectedApplication(null);
    setSelectedApplicationReadOnly(false);
  }

  function navigateToView(tab: ViewTab) {
    requests.invalidate();
    pendingLocation.current = null;
    pushLocation({ screenerLocation: true, tab, openingId: current.current.openingId });
    setSelectedApplication(null);
    setSelectedApplicationReadOnly(false);
    setActiveTab(tab);
    if (tab === "ranking") void current.current.loadRanking();
  }

  function onOpeningRankingLoaded(openingId: number, hasCriteria: boolean) {
    // The opening refresh can finish after another navigation. Inspect the live
    // location before loading or redirecting, and preserve a detail being restored.
    if (current.current.openingId !== openingId || current.current.activeTab !== "ranking") return;
    if (hasCriteria) void current.current.loadRanking();
    else if (!current.current.selectedApplication && !pendingLocation.current?.applicantId) {
      navigateToView("applications");
    }
  }

  function clearSelectedApplication() {
    requests.invalidate();
    pendingLocation.current = null;
    setSelectedApplication(null);
    setSelectedApplicationReadOnly(false);
    replaceLocation({ screenerLocation: true, tab: current.current.activeTab, openingId: current.current.openingId });
  }

  return {
    activeTab, selectedApplication, selectedApplicationReadOnly,
    updateSelectedApplication: (update: ApplicationUpdate, openingId?: number) => {
      // Acknowledgements are not navigation; don't cancel another applicant's read.
      const reading = pendingDetail.current;
      if (reading && pendingLocation.current === reading.location && reading.location.applicantId === update.id
        && (openingId === undefined || openingId === reading.location.openingId)) {
        reading.receipts = { ...reading.receipts, ...update };
      }
      setSelectedApplication((value) => value?.id === update.id
        && (openingId === undefined || openingId === current.current.openingId) ? { ...value, ...update } : value);
    },
    clearSelectedApplication,
    viewApplication, viewRetainedApplication, changeOpening, backToList, navigateToView,
    onOpeningRankingLoaded,
  };
}
