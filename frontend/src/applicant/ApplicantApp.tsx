import { FileCheck2, Save, Trash2 } from "lucide-react";
import { type ComponentProps, type FormEvent, type InvalidEvent, useEffect, useRef, useState } from "react";

import { BrandLockup } from "../components/shared/BrandLockup";
import { HeaderAccount } from "../components/shared/HeaderAccount";
import {
  AccessLinkDecision,
  AccessLinkReady,
  AccessLinkSent,
  ApplicationEntry,
  ApplicationLoading,
  ApplicationLoadRecovery,
  ApplicationsUnavailable,
  ApplicationSessionExpired,
  ExpiredAccessLink,
  InvalidAccessLink,
  PendingCopyDecision,
} from "./ApplicantAccessScreens";
import {
  type DraftUpdater,
  validateEmailField,
  validateFormFields,
} from "./ApplicantFormFields";
import {
  EmploymentSection,
  EssaysSection,
  HouseholdSection,
  HousingSection,
  IncomeSection,
  Introduction,
  OpeningSelection,
} from "./ApplicantFormSections";
import {
  ApplicationSubmitted,
  ApplicationWithdrawn,
  ApplicationWithdrawal,
  ApplicationReview,
  ClearDraftConfirmation,
  PersistenceActionStatus,
} from "./ApplicantReview";
import {
  applicantGoogleSignInUrl,
  takeApplicantGoogleAccessResult,
} from "./api";
import { hasDraftContent } from "./draftStorage";
import { useRememberedApplicantDraft } from "./useRememberedApplicantDraft";
import { emptyApplicantDraft, residenceHistoryCutoff } from "./applicationDraft";
import { useApplicantPersistence } from "./useApplicantPersistence";
import { workingSnapshot } from "./applicantPersistence";
import { useEmailDeliveryStatus } from "../hooks/useEmailDeliveryStatus";

export function ApplicantApp() {
  const [draft, setDraft] = useState(emptyApplicantDraft);
  const [reviewedSnapshot, setReviewedSnapshot] = useState<string | null>(null);
  const [declarationAccepted, setDeclarationAccepted] = useState(false);
  const [emailChangeOpen, setEmailChangeOpen] = useState(false);
  const [withdrawConfirmOpen, setWithdrawConfirmOpen] = useState(false);
  const [clearingDraft, setClearingDraft] = useState(false);
  const [guestStarted, setGuestStarted] = useState(false);
  const [googleAccessResult, setGoogleAccessResult] = useState(takeApplicantGoogleAccessResult);
  const formRef = useRef<HTMLFormElement>(null);
  const invalidTarget = useRef<HTMLElement | null>(null);
  const openingsRef = useRef<HTMLElement | null>(null);
  const [openingError, setOpeningError] = useState(false);
  const persistence = useApplicantPersistence(draft, setDraft, changeRememberDevice);
  const housingHistoryCutoff = residenceHistoryCutoff(persistence.openings);
  const reviewInputs = useRef({ persistence, snapshot: "" });
  reviewInputs.current = {
    persistence,
    snapshot: JSON.stringify([persistence.applicationId, workingSnapshot(draft, persistence.openingIds), housingHistoryCutoff]),
  };
  const reviewing = persistence.canEdit && reviewedSnapshot === reviewInputs.current.snapshot;

  const browserDraft = useRememberedApplicantDraft({
    authenticated: persistence.authenticated, applicationId: persistence.applicationId,
    workingRevision: persistence.workingRevision, draft, openingIds: persistence.openingIds,
  });
  const { savedAt, rememberDevice } = browserDraft;

  useEffect(() => {
    // An email submit intent can restore an incomplete saved copy or require a
    // choice between copies. Validate the chosen, mounted form before review.
    if (!persistence.reviewAfterAccess || !persistence.openingsLoaded
      || persistence.pendingCopy || persistence.busy || persistence.phase !== "idle"
      || !formRef.current) return;
    persistence.clearReviewAfterAccess();
    if (validateReview()) {
      setDeclarationAccepted(false);
      setReviewedSnapshot(reviewInputs.current.snapshot);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persistence.reviewAfterAccess, persistence.openingsLoaded, persistence.pendingCopy,
    persistence.busy, persistence.phase, persistence.canEdit, draft, persistence.openingIds]);

  useEffect(() => {
    if (
      !persistence.hasUnsavedChanges ||
      !hasDraftContent(draft)
    ) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      if (browserDraft.currentDraftIsStored()) return;
      event.preventDefault();
      event.returnValue = true;
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [draft, persistence.hasUnsavedChanges, browserDraft]);

  useEffect(() => {
    if (
      persistence.pendingEmailChange ||
      persistence.emailChangeStatus === "confirmed" ||
      (persistence.emailChangeStatus === "error" && persistence.emailChangeMessage)
    ) {
      setEmailChangeOpen(true);
    }
  }, [
    persistence.emailChangeMessage,
    persistence.emailChangeStatus,
    persistence.pendingEmailChange,
  ]);

  function update(updater: DraftUpdater): void {
    setReviewedSnapshot(null);
    setDeclarationAccepted(false);
    setClearingDraft(false);
    setDraft(updater);
  }

  function validateReview(): boolean {
    const current = reviewInputs.current.persistence;
    if (!current.canEdit || !formRef.current) return false;
    const currentSelected = current.openings.some((opening) => (
      opening.phase !== "archived" && current.openingIds.includes(opening.id)
    ));
    const withdrawing = current.openings.some((opening) => (
      opening.phase !== "archived"
      && opening.participating
      && !current.openingIds.includes(opening.id)
    ));
    if (!currentSelected && !withdrawing) {
      setOpeningError(true);
      const top = (openingsRef.current?.getBoundingClientRect().top ?? 0) + window.scrollY - 110;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      return false;
    }
    setOpeningError(false);
    validateFormFields(formRef.current);
    return formRef.current.reportValidity();
  }

  async function review(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!validateReview()) return;
    const validated = reviewInputs.current.snapshot;
    if (!(await persistence.prepareGuestReview())) return;
    if (reviewInputs.current.snapshot !== validated || !validateReview()) return;
    if (!(await persistence.saveForReview())) return;
    if (reviewInputs.current.snapshot !== validated || !validateReview()) return;
    setDeclarationAccepted(false);
    setReviewedSnapshot(validated);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function saveAndReturnLater(): void {
    const emailInput = formRef.current?.querySelector<HTMLInputElement>("input[data-email]");
    validateEmailField(emailInput ?? null);
    if (!emailInput?.checkValidity()) {
      emailInput?.reportValidity();
      emailInput?.focus();
      return;
    }
    void persistence.start("save");
  }

  function revealInvalidField(event: InvalidEvent<HTMLFormElement>): void {
    if (invalidTarget.current) return;
    invalidTarget.current = event.target as HTMLElement;
    window.requestAnimationFrame(() => {
      const target = invalidTarget.current;
      invalidTarget.current = null;
      if (!target) return;
      const top = target.getBoundingClientRect().top + window.scrollY - 110;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      target.focus({ preventScroll: true });
    });
  }

  async function discardLocalDraft(): Promise<void> {
    const discarded = draft;
    if (!(await persistence.discardDraft())) return;
    setClearingDraft(false);
    setDraft((current) => current === discarded ? emptyApplicantDraft() : current);
    browserDraft.reset();
    setReviewedSnapshot(null);
  }

  async function changeRememberDevice(remember: boolean): Promise<void> {
    await browserDraft.changeRememberDevice(remember);
  }

  async function signOut(): Promise<void> {
    if (!(await persistence.signOut())) return;
    setGoogleAccessResult(null);
    resetApplicantStateAfterExit();
  }

  async function withdrawApplication(): Promise<void> {
    if (!(await persistence.withdrawApplication())) return;
    resetApplicantStateAfterExit();
  }

  function resetApplicantStateAfterExit(): void {
    setDraft(emptyApplicantDraft());
    browserDraft.reset();
    setReviewedSnapshot(null);
    setDeclarationAccepted(false);
    setEmailChangeOpen(false);
    setWithdrawConfirmOpen(false);
    setClearingDraft(false);
    setGuestStarted(false);
    setOpeningError(false);
  }

  async function cancelPendingEmailChange(): Promise<void> {
    if (await persistence.stopEmailChange()) setEmailChangeOpen(false);
  }

  const showWithdrawApplication = persistence.authenticated
    && persistence.openingsLoaded
    && persistence.canEdit
    && ![
      "withdrawn",
      "session_expired",
      "link_ready",
      "link_conflict",
      "link_expired",
      "link_invalid",
      "applications_unavailable",
      "access_link_sent",
      "load_error",
      "submitted",
    ].includes(persistence.phase);
  const hasOpenOpening = persistence.openings.some((opening) => opening.phase === "open");

  return (
    <div className="applicant-surface">
      <header className="applicant-header">
        <div className="applicant-header-inner penta-header-inner">
          <a className="applicant-brand" href="https://www.pentacoop.com/">
            <BrandLockup />
          </a>
          {persistence.authenticated && persistence.phase !== "session_expired" ? (
            <HeaderAccount email={persistence.primaryEmail || draft.applicant.email || null} onSignOut={() => void signOut()} />
          ) : null}
        </div>
      </header>

      <main className="applicant-main">
        <div className="applicant-title-row">
          <div>
            <h1>Application for Membership</h1>
          </div>
          {persistence.authenticated
          && rememberDevice
          && persistence.canEdit
          && persistence.phase !== "applications_unavailable" ? (
            <DraftStatus savedAt={savedAt} hasContent={hasDraftContent(draft)} />
          ) : null}
        </div>

        {persistence.browserStorageMessage || browserDraft.message ? (
          <p className="application-entry-error" role="alert">{persistence.browserStorageMessage || browserDraft.message}</p>
        ) : null}
        {persistence.authenticated && googleAccessResult === "session_conflict" ? (
          <div className="application-session-conflict" role="alert">
            <div>
              <strong>Your current application is still open</strong>
              <span>Sign out before continuing with a different Google account.</span>
            </div>
            <button className="applicant-secondary-button compact" type="button" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        ) : null}

        {persistence.phase === "withdrawn" ? (
          <ApplicationWithdrawn />
        ) : persistence.phase === "session_expired" ? (
          <ApplicationSessionExpired
            googleSignInUrl={applicantGoogleSignInUrl(rememberDevice)}
            rememberDevice={rememberDevice}
            onRememberDeviceChange={changeRememberDevice}
            onEmail={() => void persistence.emailSessionAccessLink()}
          />
        ) : persistence.phase === "submitted" ? (
          <ApplicationSubmitted
            authenticated={persistence.authenticated}
            openings={persistence.openings.filter((opening) =>
              persistence.openingIds.includes(opening.id)
            )}
            onReturn={() => {
              persistence.returnToApplication();
              setReviewedSnapshot(null);
              setDeclarationAccepted(false);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        ) : persistence.phase === "access_link_sent" ? (
          <AccessLinkSent
            purpose={persistence.accessPurpose}
            message={persistence.message}
          />
        ) : persistence.phase === "link_ready" && persistence.accessEmail ? (
          <AccessLinkReady
            email={persistence.accessEmail}
            applicationEmail={persistence.accessApplicationEmail}
            purpose={persistence.accessPurpose}
            onOpen={(remember) => void persistence.openReadyApplication(remember)}
          />
        ) : persistence.phase === "link_conflict" && persistence.linkConflict ? (
          <AccessLinkDecision
            conflict={persistence.linkConflict}
            onKeepCurrent={() => void persistence.keepCurrentApplication()}
            onOpenLinked={(remember) => void persistence.openLinkedApplication(remember)}
            onEmailNew={() => void persistence.emailNewAccessLink()}
          />
        ) : persistence.phase === "link_expired" ? (
          <ExpiredAccessLink purpose={persistence.accessPurpose} onEmailNew={() => void persistence.emailNewAccessLink()} />
        ) : persistence.phase === "link_invalid" ? (
          <InvalidAccessLink />
        ) : persistence.phase === "applications_unavailable" ? (
          <ApplicationsUnavailable />
        ) : persistence.pendingCopy ? (
          <PendingCopyDecision
            pendingCopy={persistence.pendingCopy}
            openings={persistence.openings}
            busy={persistence.busy}
            error={persistence.phase === "error" ? persistence.message : null}
            onChoose={(choice) => void persistence.reconcilePendingCopy(choice)}
          />
        ) : !persistence.openingsLoaded ? (
          persistence.loadRecoveryStage !== null
            || persistence.phase === "load_error"
            || persistence.phase === "error"
            ? <ApplicationLoadRecovery stage={persistence.loadRecoveryStage ?? "failed"} />
            : <ApplicationLoading />
        ) : !persistence.authenticated && !persistence.canSignIn ? (
          <ApplicationsUnavailable />
        ) : !persistence.authenticated && !guestStarted ? (
          <ApplicationEntryWithDeliveryStatus
            allowGuest={hasOpenOpening}
            busy={persistence.busy}
            googleError={googleAccessResult}
            googleSignInUrl={applicantGoogleSignInUrl(rememberDevice)}
            rememberDevice={rememberDevice}
            onRememberDeviceChange={changeRememberDevice}
            onContinueGuest={() => setGuestStarted(true)}
            onEmailLink={persistence.requestEntryLink}
          />
        ) : reviewing ? (
          <ApplicationReview
            draft={draft}
            openings={persistence.openings}
            selectedOpeningIds={persistence.openingIds}
            declarationAccepted={declarationAccepted}
            persistencePhase={persistence.phase}
            persistenceMessage={persistence.message}
            onRetry={() => void persistence.resendCurrentIntent()}
            onReload={() => void persistence.reloadLatestApplication()}
            onDeclarationChange={setDeclarationAccepted}
            onSubmit={() => void persistence.start("submit")}
            onEdit={() => {
              persistence.clearActionFeedback();
              setReviewedSnapshot(null);
            }}
          />
        ) : !persistence.canEdit ? (
          <ApplicationsUnavailable />
        ) : (
          <form
            ref={formRef}
            className="application-form"
            onSubmit={review}
            onInvalid={revealInvalidField}
          >
            <Introduction />
            <OpeningSelection
              sectionRef={openingsRef}
              openings={persistence.openings}
              selectedIds={persistence.openingIds}
              showError={openingError}
              onChange={(openingId, selected) => {
                setOpeningError(false);
                persistence.setOpeningSelected(openingId, selected);
              }}
            />
            <HouseholdSection
              draft={draft}
              update={update}
              authenticated={persistence.authenticated}
              emailChangeOpen={emailChangeOpen}
              primaryEmail={persistence.primaryEmail}
              pendingEmailChange={persistence.pendingEmailChange}
              emailChangeStatus={persistence.emailChangeStatus}
              emailChangeMessage={persistence.emailChangeMessage}
              googleDisconnectedByEmailChange={persistence.googleDisconnectedByEmailChange}
              onOpenEmailChange={() => {
                persistence.clearEmailChangeFeedback();
                setEmailChangeOpen(true);
              }}
              onCloseEmailChange={() => setEmailChangeOpen(false)}
              onRequestEmailChange={(email) => void persistence.beginEmailChange(email)}
              onCancelEmailChange={() => void cancelPendingEmailChange()}
            />
            <HousingSection
              draft={draft}
              update={update}
              residenceHistoryCutoff={housingHistoryCutoff}
            />
            <EssaysSection draft={draft} update={update} />
            <EmploymentSection draft={draft} update={update} />
            <IncomeSection draft={draft} update={update} />

            <div className="applicant-actions">
              {clearingDraft ? (
                <ClearDraftConfirmation
                  onCancel={() => setClearingDraft(false)}
                  onConfirm={() => void discardLocalDraft()}
                />
              ) : persistence.authenticated ? (
                <span />
              ) : (
                <button className="applicant-danger-link" type="button" onClick={() => setClearingDraft(true)}>
                  <Trash2 size={16} /> Clear this draft
                </button>
              )}
              <div className="applicant-action-stack">
                <PersistenceActionStatus
                  phase={persistence.phase}
                  message={persistence.message}
                  onRetry={() => void persistence.resendCurrentIntent()}
                  onReload={() => void persistence.reloadLatestApplication()}
                />
                <div className="applicant-action-group">
                  <button
                    className="applicant-secondary-button"
                    type="button"
                    disabled={persistence.busy}
                    onClick={saveAndReturnLater}
                  >
                    <Save size={17} /> Save and return later
                  </button>
                  <button className="applicant-primary-button" type="submit" disabled={persistence.busy}>
                    {persistence.authenticated ? "Save and review" : "Review application"}
                    <FileCheck2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          </form>
        )}

        {showWithdrawApplication ? (
          <ApplicationWithdrawal
            open={withdrawConfirmOpen}
            status={persistence.withdrawalStatus}
            message={persistence.withdrawalMessage}
            onOpen={() => setWithdrawConfirmOpen(true)}
            onCancel={() => {
              persistence.clearWithdrawalFeedback();
              setWithdrawConfirmOpen(false);
            }}
            onWithdraw={() => void withdrawApplication()}
          />
        ) : null}
      </main>

      <footer className="applicant-footer">
        <p>
          <a href="https://www.pentacoop.com/privacy.html" target="_blank" rel="noopener noreferrer">
            Privacy Policy
          </a>
          <span aria-hidden="true">·</span>
          <a href="https://www.pentacoop.com/terms.html" target="_blank" rel="noopener noreferrer">
            Terms of Service
          </a>
        </p>
        <p>
          Website designed by{" "}
          <a href="https://www.jeffo.net" target="_blank" rel="noopener noreferrer">
            Jeff Oriecuia
          </a>
        </p>
      </footer>
    </div>
  );
}

function DraftStatus(props: { savedAt: Date | null; hasContent: boolean }) {
  if (!props.hasContent) return null;
  return (
    <div className="draft-status" role="status">
      <Save size={16} />
      <span>
        Saved on this device
        {props.savedAt ? <small>{formatSavedTime(props.savedAt)}</small> : null}
      </span>
    </div>
  );
}

function formatSavedTime(savedAt: Date): string {
  return `Last saved ${savedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function ApplicationEntryWithDeliveryStatus(
  props: Omit<ComponentProps<typeof ApplicationEntry>, "emailDelayed">,
) {
  const emailDelayed = useEmailDeliveryStatus();
  return <ApplicationEntry {...props} emailDelayed={emailDelayed} />;
}
