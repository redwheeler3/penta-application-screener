import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { problemMessage, readProblemBody } from "../api/problems";
import type { DraftIntent } from "./api";
import {
  type ApplicantDraft,
  type ApplicantOpening,
  type WorkingApplicationAnswers,
  workingAnswers,
} from "./types";

export type PersistencePhase =
  | "idle"
  | "working"
  | "email_sent"
  | "saved"
  | "submitted"
  | "withdrawn"
  | "link_ready"
  | "link_conflict"
  | "link_expired"
  | "link_invalid"
  | "applications_unavailable"
  | "access_link_sent"
  | "authentication_required"
  | "email_failed"
  | "stale_copy"
  | "load_error"
  | "session_expired"
  | "error";

export type ApplicationResponse = {
  applicationId: number;
  primaryEmail: string;
  pendingEmailChange: string | null;
  answers: WorkingApplicationAnswers | null;
  workingSavedAt: string | null;
  workingRevision: number;
  submitted: boolean;
  hasUnsubmittedChanges: boolean;
  canEdit: boolean;
  openings: ApplicantOpening[];
};

export type EmailChangeStatus = "idle" | "sending" | "sent" | "confirmed" | "error";
export type EmailSendStatus = "sent" | "recent" | "failed";

export type LinkConflict = {
  currentEmail: string;
  linkEmail: string;
  applicationEmail: string | null;
  purpose: "applicant_access" | "email_change";
  linkIsValid: boolean;
};

export type PendingCopy = {
  savedAnswers: WorkingApplicationAnswers;
  savedOpeningIds: number[];
  guestAnswers: WorkingApplicationAnswers;
  guestOpeningIds: number[];
};

export type AccessLinkBody = {
  state: "valid" | "expired" | "used" | "replaced" | "invalid" | "abandoned" | "unavailable" | "email_in_use";
  purpose: "applicant_access" | "email_change" | null;
  currentEmail: string | null;
  linkEmail: string | null;
  applicationEmail: string | null;
  switchRequired: boolean;
  applicationId: number | null;
  pendingIntent: DraftIntent | null;
  pendingCopy: PendingCopy | null;
};

export function linkBody(response: Response): Promise<AccessLinkBody> {
  return response.json() as Promise<AccessLinkBody>;
}

export function accessCredentialFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("applicant-link");
}

export async function responseDetail(response: Response): Promise<string> {
  return (await responseProblem(response)).detail;
}

export async function responseProblem(response: Response): Promise<{ code: string | null; detail: string }> {
  if (response.status >= 500) {
    return { code: null, detail: TECH_SUPPORT_ERROR_MESSAGE };
  }
  const body = await readProblemBody(response);
  return {
    code: body?.code ?? null,
    detail: problemMessage(body) ?? TECH_SUPPORT_ERROR_MESSAGE,
  };
}

export function workingSnapshot(draft: ApplicantDraft, openingIds: number[]): string {
  return JSON.stringify({ answers: workingAnswers(draft), openingIds });
}

export function updateSnapshotEmail(snapshot: string | null, email: string): string | null {
  if (snapshot === null) return null;
  const stored = JSON.parse(snapshot) as {
    answers: WorkingApplicationAnswers;
    openingIds: number[];
  };
  return JSON.stringify({
    ...stored,
    answers: {
      ...stored.answers,
      applicant: { ...stored.answers.applicant, email },
    },
  });
}

export function defaultOpeningIds(openings: ApplicantOpening[]): number[] {
  const selected = openings.filter((opening) => opening.selected).map((opening) => opening.id);
  const open = openings.filter((opening) => opening.phase === "open");
  if (
    open.length === 1
    && !open[0].hasParticipated
    && !selected.includes(open[0].id)
  ) selected.push(open[0].id);
  return selected;
}

export function validBrowserOpeningIds(
  storedIds: number[],
  openings: ApplicantOpening[],
): number[] {
  const stored = new Set(storedIds);
  return openings
    .filter((opening) => (
      opening.phase === "archived"
        ? opening.selected
        : stored.has(opening.id)
    ))
    .map((opening) => opening.id);
}
