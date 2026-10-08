import { useCommitteeApi } from "../api/identity";
import { useRef } from "react";

import * as applicationsApi from "../api/applications";
import type { ApplicationUpdate, AppStatus, CommitteeActionResult } from "../types";
import { useRequestScope } from "./useRequestScope";

type CandidateActionsOptions = {
  openingId: number | null;
  rankingLoaded: boolean;
  onApplicationUpdated: (application: ApplicationUpdate, openingId: number) => void;
  onError: (message: string) => void;
  refreshDashboard: () => Promise<void>;
  reloadApplications: () => Promise<void>;
  loadRanking: () => Promise<boolean>;
};

/** Candidate writes and the derived views that must refresh after each kind of change. */
export function useCandidateActions(options: CandidateActionsOptions) {
  const api = useCommitteeApi(applicationsApi);

  const { openingId } = options;
  const requests = useRequestScope(openingId);
  const current = useRef(options);
  const writeQueues = useRef(new Map<string, Promise<void>>());
  current.current = options;

  async function mutate(
    applicationId: number,
    field: "status" | "committeeNotes" | "starredByMe" | "shortlisted",
    send: (openingId: number) => Promise<Response>,
    failureMessage: string,
  ): Promise<CommitteeActionResult> {
    if (openingId === null || !requests.isFor(openingId)) return "rejected";
    const isCurrent = requests.capture();
    // Same-field edits stay ordered. Narrow acknowledgements let independent fields
    // save concurrently without replacing unrelated detail data.
    const owner = field === "status" || field === "shortlisted" ? `${openingId}:${applicationId}` : String(applicationId);
    const queueKey = `${owner}:${field}`;
    const result = (writeQueues.current.get(queueKey) ?? Promise.resolve()).then(async (): Promise<CommitteeActionResult> => {
      if (!isCurrent()) return "rejected";
      try {
        const response = await send(openingId);
        if (!isCurrent()) return "rejected";
        if (!response.ok) {
          current.current.onError(failureMessage);
          return response.status >= 500 ? "unconfirmed" : "rejected";
        }
        const payload: { application: ApplicationUpdate } = await response.json();
        if (!isCurrent()) return "rejected";
        if (payload.application?.id !== applicationId || !(field in payload.application)) {
          throw new Error("Save acknowledgement is incomplete.");
        }
        // Navigation reconciles this receipt with matching displayed or pending detail.
        current.current.onApplicationUpdated(payload.application, openingId);
        return "saved";
      } catch {
        if (isCurrent()) current.current.onError(failureMessage);
        return "unconfirmed";
      }
    });
    const tail = result.then(() => {}, () => {});
    writeQueues.current.set(queueKey, tail);
    void tail.then(() => {
      if (writeQueues.current.get(queueKey) === tail) writeQueues.current.delete(queueKey);
    });
    return result;
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

  async function overrideStatus(id: number, status: AppStatus, reviewedFingerprint: string): Promise<void> {
    if ((await mutate(id, "status", (opening) => api.overrideStatus(id, opening, status, reviewedFingerprint), "Could not update eligibility.")) === "saved") {
      refreshEligibilityViews();
    }
  }

  async function clearStatusOverride(id: number): Promise<void> {
    if ((await mutate(id, "status", (opening) => api.clearStatusOverride(id, opening), "Could not clear the eligibility override.")) === "saved") {
      refreshEligibilityViews();
    }
  }

  async function addCommitteeNote(id: number, body: string, creationKey: string): Promise<CommitteeActionResult> {
    return mutate(
      id, "committeeNotes", (opening) => api.addCommitteeNote(id, opening, body, creationKey), "Could not add the committee note.",
    );
  }

  async function updateCommitteeNote(id: number, noteId: number, body: string): Promise<boolean> {
    return (await mutate(
      id, "committeeNotes", (opening) => api.updateCommitteeNote(id, opening, noteId, body), "Could not update the committee note.",
    )) === "saved";
  }

  async function deleteCommitteeNote(id: number, noteId: number): Promise<boolean> {
    return (await mutate(
      id, "committeeNotes", (opening) => api.deleteCommitteeNote(id, opening, noteId), "Could not delete the committee note.",
    )) === "saved";
  }

  async function toggleStar(id: number, starred: boolean): Promise<void> {
    const outcome = await mutate(
      id, "starredByMe", (opening) => api.setStar(id, opening, starred),
      starred ? "Could not add to favourites." : "Could not remove from favourites.",
    );
    if (outcome === "saved") refreshSavedViews();
  }

  async function toggleShortlist(id: number, shortlisted: boolean): Promise<void> {
    const outcome = await mutate(
      id, "shortlisted", (opening) => api.setShortlist(id, opening, shortlisted),
      shortlisted ? "Could not add to the shared shortlist." : "Could not remove from the shared shortlist.",
    );
    if (outcome === "saved") refreshSavedViews();
  }

  return {
    overrideStatus, clearStatusOverride,
    addCommitteeNote, updateCommitteeNote, deleteCommitteeNote,
    toggleStar, toggleShortlist, refreshEligibilityViews,
  };
}
