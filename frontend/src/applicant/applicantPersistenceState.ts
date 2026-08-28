import type { ServiceRecoveryStage } from "../serviceRecovery";
import type { DraftIntent } from "./api";
import type {
  EmailChangeStatus,
  LinkConflict,
  PendingCopy,
  PersistencePhase,
} from "./applicantPersistence";
import type { ApplicantOpening } from "./types";

export type ApplicantPersistenceState = {
  phase: PersistencePhase;
  loadRecoveryStage: ServiceRecoveryStage | null;
  message: string;
  applicationId: number | null;
  workingRevision: number | null;
  submitted: boolean;
  serverHasUnsubmittedChanges: boolean;
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
  pendingEmailChange: string | null;
  emailChangeStatus: EmailChangeStatus;
  emailChangeMessage: string;
  collisionEmail: string | null;
  submissionEmailSent: boolean;
  withdrawalEmailStatus: "sent" | "failed" | "not_needed";
  withdrawalStatus: "idle" | "working" | "error";
  withdrawalMessage: string;
};

type StateUpdater<Value> = Value | ((current: Value) => Value);

export type SetApplicantPersistence = <Key extends keyof ApplicantPersistenceState>(
  key: Key,
  value: StateUpdater<ApplicantPersistenceState[Key]>,
) => void;

export type ApplicantPersistenceAction = {
  [Key in keyof ApplicantPersistenceState]: {
    key: Key;
    value: StateUpdater<ApplicantPersistenceState[Key]>;
  };
}[keyof ApplicantPersistenceState];

export const INITIAL_APPLICANT_PERSISTENCE_STATE: ApplicantPersistenceState = {
  phase: "idle",
  loadRecoveryStage: null,
  message: "",
  applicationId: null,
  workingRevision: null,
  submitted: false,
  serverHasUnsubmittedChanges: false,
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
  pendingEmailChange: null,
  emailChangeStatus: "idle",
  emailChangeMessage: "",
  collisionEmail: null,
  submissionEmailSent: true,
  withdrawalEmailStatus: "not_needed",
  withdrawalStatus: "idle",
  withdrawalMessage: "",
};

export function applicantPersistenceReducer(
  state: ApplicantPersistenceState,
  action: ApplicantPersistenceAction,
): ApplicantPersistenceState {
  const current = state[action.key];
  const value = typeof action.value === "function"
    ? (action.value as (value: typeof current) => typeof current)(current)
    : action.value;
  return { ...state, [action.key]: value };
}
