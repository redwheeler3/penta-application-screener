import { ChevronLeft, FileCheck2, Save, Trash2 } from "lucide-react";
import { type FormEvent, type InvalidEvent, useEffect, useRef, useState } from "react";

import { BrandLockup } from "../components/shared/BrandLockup";
import { HeaderAccount } from "../components/shared/HeaderAccount";
import {
  AccessLinkDecision,
  AccessLinkReady,
  AccessLinkSent,
  ApplicationEntry,
  ApplicationLoadError,
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
  ApplicationComplete,
  ApplicationDeleted,
  ApplicationDeletion,
  ApplicationReview,
  type DraftConfirmation,
  DraftActionConfirmation,
  PersistenceActionStatus,
  PrivateChangesNotice,
} from "./ApplicantReview";
import {
  hasDraftContent,
  remembersDevice,
  saveApplicationDraft,
  setRememberDevice,
} from "./draftStorage";
import {
  type ApplicantDraft,
  emptyApplicantDraft,
} from "./types";
import { useApplicantPersistence } from "./useApplicantPersistence";

export function ApplicantApp() {
  const [draft, setDraft] = useState(emptyApplicantDraft);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [declarationAccepted, setDeclarationAccepted] = useState(false);
  const [rememberDevice, setRememberDeviceState] = useState(remembersDevice);
  const [emailChangeOpen, setEmailChangeOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [draftConfirmation, setDraftConfirmation] = useState<DraftConfirmation | null>(null);
  const [guestStarted, setGuestStarted] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const invalidTarget = useRef<HTMLElement | null>(null);
  const openingsRef = useRef<HTMLElement | null>(null);
  const [openingError, setOpeningError] = useState(false);
  const persistence = useApplicantPersistence(draft, setDraft, changeRememberDevice);

  useEffect(() => {
    if (
      !persistence.authenticated
      || !rememberDevice
      || persistence.applicationId == null
      || persistence.workingRevision == null
    ) return;
    const timeout = window.setTimeout(
      () => setSavedAt(saveApplicationDraft(
        persistence.applicationId!,
        draft,
        persistence.openingIds,
        persistence.workingRevision!,
      )),
      350,
    );
    return () => window.clearTimeout(timeout);
  }, [
    draft,
    persistence.applicationId,
    persistence.authenticated,
    persistence.openingIds,
    persistence.workingRevision,
    rememberDevice,
  ]);

  useEffect(() => {
    if (!persistence.reviewAfterAccess) return;
    setReviewing(true);
    persistence.clearReviewAfterAccess();
  }, [persistence.reviewAfterAccess]);

  useEffect(() => {
    if (
      (persistence.authenticated && rememberDevice) ||
      !persistence.hasUnsavedChanges ||
      !hasDraftContent(draft)
    ) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = true;
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [draft, persistence.authenticated, persistence.hasUnsavedChanges, rememberDevice]);

  useEffect(() => {
    if (
      persistence.pendingEmailChange ||
      persistence.emailChangeStatus === "confirmed" ||
      (persistence.emailChangeStatus === "error" && persistence.emailChangeMessage)
    ) {
      setEmailChangeOpen(true);
    }
  }, [persistence.emailChangeStatus, persistence.pendingEmailChange]);

  useEffect(() => {
    if (!persistence.pendingEmailChange) return;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void persistence.refreshEmailIdentity();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => document.removeEventListener("visibilitychange", refreshWhenVisible);
  }, [persistence.pendingEmailChange]);

  function update(updater: DraftUpdater): void {
    setReviewing(false);
    setDeclarationAccepted(false);
    setDraftConfirmation(null);
    setDraft(updater);
  }

  async function review(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const currentSelected = persistence.openings.some((opening) => (
      opening.phase !== "archived" && persistence.openingIds.includes(opening.id)
    ));
    const withdrawing = persistence.openings.some((opening) => (
      opening.phase !== "archived"
      && opening.participating
      && !persistence.openingIds.includes(opening.id)
    ));
    if (!currentSelected && !withdrawing) {
      setOpeningError(true);
      const top = (openingsRef.current?.getBoundingClientRect().top ?? 0) + window.scrollY - 110;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      return;
    }
    setOpeningError(false);
    validateFormFields(formRef.current);
    if (!formRef.current?.reportValidity()) return;
    if (!(await persistence.prepareGuestReview())) return;
    if (!(await persistence.saveForReview())) return;
    setReviewing(true);
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

  function discardLocalDraft(): void {
    setDraftConfirmation(null);
    void persistence.discardDraft();
    setDraft(emptyApplicantDraft());
    setSavedAt(null);
    setReviewing(false);
  }

  async function revertToSubmitted(): Promise<void> {
    setDraftConfirmation(null);
    if (await persistence.revertToSubmitted()) {
      setSavedAt(null);
      setReviewing(false);
      setDeclarationAccepted(false);
    }
  }

  function changeRememberDevice(remember: boolean): void {
    setRememberDevice(remember);
    setRememberDeviceState(remember);
    if (!remember) setSavedAt(null);
  }

  async function signOut(): Promise<void> {
    if (!(await persistence.signOut())) return;
    setDraft(emptyApplicantDraft());
    setSavedAt(null);
    setReviewing(false);
    setRememberDeviceState(false);
    setGuestStarted(false);
  }

  async function cancelPendingEmailChange(): Promise<void> {
    if (await persistence.stopEmailChange()) setEmailChangeOpen(false);
  }

  const showDeleteApplication = persistence.authenticated
    && persistence.openingsLoaded
    && ![
      "deleted",
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
  const hasActiveOpening = persistence.openings.some((opening) => (
    opening.phase === "open" || opening.phase === "closed"
  ));
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
          {persistence.authenticated && rememberDevice ? (
            <DraftStatus savedAt={savedAt} hasContent={hasDraftContent(draft)} />
          ) : null}
        </div>

        {persistence.phase === "deleted" ? (
          <ApplicationDeleted emailSent={persistence.deletionEmailSent} />
        ) : persistence.phase === "session_expired" ? (
          <ApplicationSessionExpired onEmail={() => void persistence.emailSessionAccessLink()} />
        ) : persistence.phase === "submitted" ? (
          <ApplicationComplete submitted emailSent={persistence.submissionEmailSent} />
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
        ) : !persistence.openingsLoaded && (
          persistence.phase === "load_error" || persistence.phase === "error"
        ) ? (
          <ApplicationLoadError
            message={persistence.message}
            onRetry={() => void persistence.retryInitialLoad()}
          />
        ) : !persistence.authenticated && !hasActiveOpening ? (
          <ApplicationsUnavailable />
        ) : !persistence.authenticated && !guestStarted ? (
          <ApplicationEntry
            allowGuest={hasOpenOpening}
            busy={persistence.busy}
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
            authenticated={persistence.authenticated}
            onRetry={() => void persistence.resendCurrentIntent()}
            onReload={() => void persistence.reloadLatestApplication()}
            onDeclarationChange={setDeclarationAccepted}
            onSubmit={() => void persistence.start("submit")}
            onEdit={() => {
              persistence.clearActionFeedback();
              setReviewing(false);
            }}
          />
        ) : !persistence.openingsLoaded ? (
          <p className="applicant-loading" role="status">Loading application details…</p>
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
            {persistence.hasUnsubmittedChanges ? <PrivateChangesNotice /> : null}
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
              emailChangeNeedsReauthentication={persistence.emailChangeNeedsReauthentication}
              onOpenEmailChange={() => {
                persistence.clearEmailChangeFeedback();
                setEmailChangeOpen(true);
              }}
              onCloseEmailChange={() => setEmailChangeOpen(false)}
              onRequestEmailChange={(email) => void persistence.beginEmailChange(email)}
              onRequestReauthentication={() => void persistence.emailReauthenticationLink()}
              onCancelEmailChange={() => void cancelPendingEmailChange()}
            />
            <HousingSection draft={draft} update={update} />
            <EssaysSection draft={draft} update={update} />
            <EmploymentSection draft={draft} update={update} />
            <IncomeSection draft={draft} update={update} />

            <div className="applicant-actions">
              {draftConfirmation ? (
                <DraftActionConfirmation
                  action={draftConfirmation}
                  onCancel={() => setDraftConfirmation(null)}
                  onConfirm={() => {
                    if (draftConfirmation === "clear") discardLocalDraft();
                    else void revertToSubmitted();
                  }}
                />
              ) : persistence.authenticated ? (
                persistence.hasSubmittedApplication && persistence.hasUnsubmittedChanges ? (
                  <button className="text-button" type="button" onClick={() => setDraftConfirmation("revert")}>
                    <ChevronLeft size={16} /> Revert to last submitted application
                  </button>
                ) : <span />
              ) : (
                <button className="applicant-danger-link" type="button" onClick={() => setDraftConfirmation("clear")}>
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

        {showDeleteApplication ? (
          <ApplicationDeletion
            open={deleteConfirmOpen}
            status={persistence.deletionStatus}
            message={persistence.deletionMessage}
            onOpen={() => setDeleteConfirmOpen(true)}
            onCancel={() => {
              persistence.clearDeletionFeedback();
              setDeleteConfirmOpen(false);
            }}
            onDelete={() => void persistence.removeApplication()}
            onReauthenticate={() => void persistence.emailDeletionReauthentication()}
          />
        ) : null}
      </main>

      <footer className="applicant-footer">
        <p>
          <a href="https://www.pentacoop.com/privacy.html">Privacy Policy</a>
          <span aria-hidden="true">·</span>
          <a href="https://www.pentacoop.com/terms.html">Terms of Service</a>
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
