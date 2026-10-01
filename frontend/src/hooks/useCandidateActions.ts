import { useRef } from "react";

import * as api from "../api/applications";
import type { ApplicationDetail, AppStatus } from "../types";
import { useRequestScope } from "./useRequestScope";

type CandidateActionsOptions = {
  openingId: number | null;
  selectedApplication: ApplicationDetail | null;
  rankingLoaded: boolean;
  onApplicationUpdated: (application: ApplicationDetail) => void;
  onError: (message: string) => void;
  refreshDashboard: () => Promise<void>;
  reloadApplications: () => Promise<void>;
  loadRanking: () => Promise<boolean>;
};

/** Candidate writes and the derived views that must refresh after each kind of change. */
export function useCandidateActions(options: CandidateActionsOptions) {
  const { openingId } = options;
  const requests = useRequestScope(openingId);
  const current = useRef(options);
  current.current = options;

  async function mutate(
    applicationId: number,
    send: (openingId: number) => Promise<Response>,
    failureMessage: string,
  ): Promise<ApplicationDetail | null> {
    if (openingId === null || !requests.isFor(openingId)) return null;
    const isCurrent = requests.capture();
    try {
      const response = await send(openingId);
      if (!isCurrent()) return null;
      if (!response.ok) {
        current.current.onError(failureMessage);
        return null;
      }
      const payload: { application: ApplicationDetail } = await response.json();
      if (!isCurrent()) return null;
      // A completed save must not reopen a detail the member has since left.
      if (current.current.selectedApplication?.id === applicationId) {
        current.current.onApplicationUpdated(payload.application);
      }
      return payload.application;
    } catch {
      if (isCurrent()) current.current.onError(failureMessage);
      return null;
    }
  }

  function refreshEligibilityViews(): void {
    const views = current.current;
    void views.refreshDashboard();
    void views.reloadApplications();
    if (views.rankingLoaded) void views.loadRanking();
  }

  function refreshSavedViews(): void {
    const views = current.current;
    // Facets derive from the whole cached pool, including applicants filtered out of the list.
    void views.reloadApplications();
    if (views.rankingLoaded) void views.loadRanking();
  }

  async function overrideStatus(id: number, status: AppStatus): Promise<void> {
    if (await mutate(id, (opening) => api.overrideStatus(id, opening, status), "Could not update eligibility.")) {
      refreshEligibilityViews();
    }
  }

  async function clearStatusOverride(id: number): Promise<void> {
    if (await mutate(id, (opening) => api.clearStatusOverride(id, opening), "Could not clear the eligibility override.")) {
      refreshEligibilityViews();
    }
  }

  async function savePrivateNote(id: number, note: string): Promise<boolean> {
    return Boolean(await mutate(
      id, (opening) => api.savePrivateNote(id, opening, note), "Could not save your private note.",
    ));
  }

  async function addCommitteeNote(id: number, body: string): Promise<boolean> {
    return Boolean(await mutate(
      id, (opening) => api.addCommitteeNote(id, opening, body), "Could not add the committee note.",
    ));
  }

  async function updateCommitteeNote(id: number, noteId: number, body: string): Promise<boolean> {
    return Boolean(await mutate(
      id, (opening) => api.updateCommitteeNote(id, opening, noteId, body), "Could not update the committee note.",
    ));
  }

  async function deleteCommitteeNote(id: number, noteId: number): Promise<boolean> {
    return Boolean(await mutate(
      id, (opening) => api.deleteCommitteeNote(id, opening, noteId), "Could not delete the committee note.",
    ));
  }

  async function toggleStar(id: number, starred: boolean): Promise<void> {
    const application = await mutate(
      id, (opening) => api.setStar(id, opening, starred),
      starred ? "Could not add to favourites." : "Could not remove from favourites.",
    );
    if (application) refreshSavedViews();
  }

  async function toggleShortlist(id: number, shortlisted: boolean): Promise<void> {
    const application = await mutate(
      id, (opening) => api.setShortlist(id, opening, shortlisted),
      shortlisted ? "Could not add to the shared shortlist." : "Could not remove from the shared shortlist.",
    );
    if (application) refreshSavedViews();
  }

  return {
    overrideStatus, clearStatusOverride, savePrivateNote,
    addCommitteeNote, updateCommitteeNote, deleteCommitteeNote,
    toggleStar, toggleShortlist, refreshEligibilityViews,
  };
}
