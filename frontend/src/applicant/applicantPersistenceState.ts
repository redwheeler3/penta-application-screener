import type { ServiceRecoveryStage } from "../serviceRecovery";
import type { DraftIntent } from "./api";
import type {
  ApplicationResponse,
  EmailChangeStatus,
  LinkConflict,
  PendingCopy,
  PersistencePhase,
} from "./applicantPersistence";
import { validBrowserOpeningIds } from "./applicantPersistence";
import type { ApplicantOpening } from "./types";

export type ApplicantPersistenceState = {
  phase: PersistencePhase;
  loadRecoveryStage: ServiceRecoveryStage | null;
  message: string;
  applicationId: number | null;
  workingRevision: number | null;
  openings: ApplicantOpening[];
  openingIds: number[];
  canEdit: boolean;
  openingsLoaded: boolean;
  pendingDraftToken: string | null;
  accessToken: string | null;
  accessEmail: string | null;
  accessPurpose: "applicant_access" | "email_change";
  accessApplicationEmail: string | null;
  linkConflict: LinkConflict | null;
  pendingCopy: PendingCopy | null;
  lastIntent: DraftIntent;
  reviewAfterAccess: boolean;
  savedAnswers: string | null;
  primaryEmail: string | null;
  googleSignInLinked: boolean;
  googleDisconnectedByEmailChange: boolean;
  pendingEmailChange: string | null;
  emailChangeStatus: EmailChangeStatus;
  emailChangeMessage: string;
  collisionEmail: string | null;
  withdrawalStatus: "idle" | "working" | "error";
  withdrawalMessage: string;
};

type StateUpdater<Value> = Value | ((current: Value) => Value);

export type SetApplicantPersistence = <Key extends keyof ApplicantPersistenceState>(
  key: Key,
  value: StateUpdater<ApplicantPersistenceState[Key]>,
) => void;

type FieldChange = {
  [Key in keyof ApplicantPersistenceState]: {
    key: Key;
    value: StateUpdater<ApplicantPersistenceState[Key]>;
  };
}[keyof ApplicantPersistenceState];

export type ApplicantPersistenceAction = FieldChange
  | { type: "application_restored"; application: ApplicationResponse; openingIds: number[]; snapshot: string | null }
  | { type: "save_started"; intent: DraftIntent }
  | { type: "save_completed"; snapshot: string; phase: "saved" | "submitted" | "email_sent" | "email_failed";
      application?: ApplicationResponse; message?: string; draftToken?: string }
  | { type: "action_failed"; message: string; phase?: PersistencePhase }
  | { type: "session_ended"; phase: "idle" | "withdrawn" }
  | { type: "lifecycle_refreshed"; application: ApplicationResponse };

export const INITIAL_APPLICANT_PERSISTENCE_STATE: ApplicantPersistenceState = {
  phase: "idle",
  loadRecoveryStage: null,
  message: "",
  applicationId: null,
  workingRevision: null,
  openings: [],
  openingIds: [],
  canEdit: false,
  openingsLoaded: false,
  pendingDraftToken: null,
  accessToken: null,
  accessEmail: null,
  accessPurpose: "applicant_access",
  accessApplicationEmail: null,
  linkConflict: null,
  pendingCopy: null,
  lastIntent: "save",
  reviewAfterAccess: false,
  savedAnswers: null,
  primaryEmail: null,
  googleSignInLinked: false,
  googleDisconnectedByEmailChange: false,
  pendingEmailChange: null,
  emailChangeStatus: "idle",
  emailChangeMessage: "",
  collisionEmail: null,
  withdrawalStatus: "idle",
  withdrawalMessage: "",
};

export function applicantPersistenceReducer(
  state: ApplicantPersistenceState,
  action: ApplicantPersistenceAction,
): ApplicantPersistenceState {
  if ("type" in action) {
    switch (action.type) {
      case "application_restored": {
        const application = action.application;
        return {
          ...state,
          applicationId: application.applicationId,
          workingRevision: application.workingRevision,
          primaryEmail: application.primaryEmail,
          googleSignInLinked: application.googleSignInLinked,
          pendingEmailChange: application.pendingEmailChange,
          openings: application.openings,
          canEdit: application.canEdit,
          openingsLoaded: true,
          openingIds: action.openingIds,
          savedAnswers: action.snapshot,
          phase: "idle",
        };
      }
      case "save_started":
        return { ...state, lastIntent: action.intent, message: "", phase: "working" };
      case "save_completed":
        return {
          ...state,
          ...(action.application ? {
            workingRevision: action.application.workingRevision,
            openings: action.application.openings,
            canEdit: action.application.canEdit,
          } : {}),
          ...(action.draftToken ? { pendingDraftToken: action.draftToken } : {}),
          savedAnswers: action.snapshot,
          message: action.message ?? "",
          phase: action.phase,
        };
      case "action_failed":
        return { ...state, message: action.message, phase: action.phase ?? "error" };
      case "session_ended":
        return {
          ...INITIAL_APPLICANT_PERSISTENCE_STATE,
          openings: state.openings,
          openingsLoaded: state.openingsLoaded,
          canEdit: state.canEdit,
          phase: action.phase,
        };
      case "lifecycle_refreshed": {
        const application = action.application;
        const stale = state.workingRevision !== null
          && state.workingRevision !== application.workingRevision;
        return {
          ...state,
          openings: application.openings,
          openingIds: validBrowserOpeningIds(state.openingIds, application.openings),
          canEdit: application.canEdit,
          ...(stale ? {
            message: "This application changed in another tab or browser.", phase: "stale_copy" as const,
          } : { workingRevision: application.workingRevision }),
        };
      }
    }
  }
  const current = state[action.key];
  const value = typeof action.value === "function"
    ? (action.value as (value: typeof current) => typeof current)(current)
    : action.value;
  return { ...state, [action.key]: value };
}
