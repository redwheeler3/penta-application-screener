// Shared types for the screener UI. Most mirror a backend schema; the comment on
// each says which and any non-obvious semantics (null vs [] etc.).

// The top-level views selectable in the tab strip (App's activeTab). Shared so a
// navigation callback (e.g. a feedback context link) and the state stay in lockstep.
export type ViewTab =
  | "applications"
  | "ranking"
  | "observability"
  | "evals"
  | "eligibilitySettings"
  | "adminSettings";

export type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

// One approved committee email address and its coarse activity summary. Admin-only surface.
export type AllowlistEntry = {
  email: string;
  role: "admin" | "member";
  displayName: string | null;
  firstActiveAt: string | null;
  lastActiveAt: string | null;
};

export type DeniedSignInAttempt = {
  displayName: string;
  email: string;
  firstDeniedAt: string;
  lastDeniedAt: string;
  count: number;
};

export type OpeningPhase = "draft" | "upcoming" | "open" | "closed" | "archived";

export type OpeningDetails = {
  id: number;
  unitSizeBedrooms: number;
  housingChargeCents: number;
  applicationOpenDate: string;
  applicationCloseDate: string;
  moveInDate: string;
};

export type Opening = OpeningDetails & {
  phase: OpeningPhase;
  publishedAt: string | null;
  submissionCount: number;
  selectedApplicationId: number | null;
  selectedApplicantName: string | null;
  noHouseholdSelected: boolean;
  decisionPermanent: boolean;
  needsDecision: boolean;
  createdAt: string;
  updatedAt: string;
};

export type OpeningWrite = Omit<OpeningDetails, "id">;

export type OpeningSelectionCandidate = {
  applicationId: number;
  applicantName: string | null;
  primaryEmail: string;
};

export type OpeningSelection = {
  openingId: number;
  phase: OpeningPhase;
  selectedApplicationId: number | null;
  selectedApplicantName: string | null;
  noHouseholdSelected: boolean;
  decisionPermanent: boolean;
  activeParticipantCount: number;
  candidates: OpeningSelectionCandidate[];
};

// A member's feedback item. Members submit body + context; identity/version/time are
// server-stamped. The admin Feedback subtab reads the full shape.
export type FeedbackItem = {
  id: number;
  body: string;
  userEmail: string;
  userName: string;
  route: string | null;
  activeTab: string | null;
  analysisId: number | null;
  applicantId: number | null;
  // The applicant's current name, resolved on read; null if no applicant context or the
  // applicant was since removed.
  applicantName: string | null;
  appVersion: string;
  createdAt: string;
  resolvedAt: string | null;
};
