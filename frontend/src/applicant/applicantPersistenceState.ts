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

export type ApplicantPersistenceUpdate = Partial<ApplicantPersistenceState>
  | ((current: ApplicantPersistenceState) => Partial<ApplicantPersistenceState>);

export type UpdateApplicantPersistence = (update: ApplicantPersistenceUpdate) => void;

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
  update: ApplicantPersistenceUpdate,
): ApplicantPersistenceState {
  return { ...state, ...(typeof update === "function" ? update(state) : update) };
}

export function resetApplicantSession(
  state: ApplicantPersistenceState, phase: "idle" | "withdrawn" = "idle",
): ApplicantPersistenceState {
  return {
    ...INITIAL_APPLICANT_PERSISTENCE_STATE,
    openings: state.openings,
    openingsLoaded: state.openingsLoaded,
    canEdit: state.canEdit,
    phase,
  };
}
