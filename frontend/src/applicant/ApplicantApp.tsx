import { CheckCircle2, ChevronLeft, FileCheck2, Mail, Plus, Save, ShieldCheck, Trash2 } from "lucide-react";
import { type FormEvent, type InvalidEvent, useEffect, useRef, useState } from "react";

import { BrandLockup } from "../BrandLockup";
import { HeaderAccount } from "../HeaderAccount";
import { TECH_SUPPORT_EMAIL } from "../support";
import {
  hasDraftContent,
  remembersDevice,
  saveApplicationDraft,
  setRememberDevice,
} from "./draftStorage";
import {
  type ApplicantDraft,
  type EmploymentDraft,
  householdIncome,
  emptyApplicantDraft,
  newChild,
  type PersonDraft,
  type ReferenceDraft,
  type YesNo,
} from "./types";
import { useApplicantPersistence } from "./useApplicantPersistence";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/;
const EMAIL_INVALID_MESSAGE = "This is not a valid email address.";
const PHONE_PATTERN = /^[0-9]{3}-[0-9]{3}-[0-9]{4}$/;

type DraftUpdater = (current: ApplicantDraft) => ApplicantDraft;

export function ApplicantApp() {
  const [draft, setDraft] = useState(emptyApplicantDraft);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [declarationAccepted, setDeclarationAccepted] = useState(false);
  const [rememberDevice, setRememberDeviceState] = useState(remembersDevice);
  const [emailChangeOpen, setEmailChangeOpen] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const invalidTarget = useRef<HTMLElement | null>(null);
  const persistence = useApplicantPersistence(draft, setDraft, changeRememberDevice);

  useEffect(() => {
    if (!persistence.authenticated || !rememberDevice || persistence.applicationId == null) return;
    const timeout = window.setTimeout(
      () => setSavedAt(saveApplicationDraft(persistence.applicationId!, draft)),
      350,
    );
    return () => window.clearTimeout(timeout);
  }, [draft, persistence.applicationId, persistence.authenticated, rememberDevice]);

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
    setDraft(updater);
  }

  function review(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    validateFormFields(formRef.current);
    if (!formRef.current?.reportValidity()) return;
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
    if (!window.confirm("Clear the answers in this form?")) return;
    void persistence.discardDraft();
    setDraft(emptyApplicantDraft());
    setSavedAt(null);
    setReviewing(false);
  }

  function changeRememberDevice(remember: boolean): void {
    setRememberDevice(remember);
    setRememberDeviceState(remember);
    if (!remember) setSavedAt(null);
  }

  function signOut(): void {
    void persistence.signOut();
    setDraft(emptyApplicantDraft());
    setSavedAt(null);
    setReviewing(false);
    setRememberDeviceState(false);
  }

  async function cancelPendingEmailChange(): Promise<void> {
    if (await persistence.stopEmailChange()) setEmailChangeOpen(false);
  }

  return (
    <div className="applicant-surface">
      <header className="applicant-header">
        <div className="applicant-header-inner penta-header-inner">
          <a className="applicant-brand" href="https://www.pentacoop.com/">
            <BrandLockup />
          </a>
          {persistence.authenticated ? (
            <HeaderAccount email={persistence.primaryEmail || draft.applicant.email || null} onSignOut={signOut} />
          ) : null}
        </div>
      </header>

      <main className="applicant-main">
        <div className="applicant-title-row">
          <div>
            <h1>{reviewing ? "Review your application" : "Application for Membership"}</h1>
            {reviewing ? (
              <p>Check your answers before continuing to the secure submission step.</p>
            ) : null}
          </div>
          {persistence.authenticated && rememberDevice ? (
            <DraftStatus savedAt={savedAt} hasContent={hasDraftContent(draft)} />
          ) : null}
        </div>

        <PersistenceNotice
          phase={persistence.phase}
          message={persistence.message}
        />

        {persistence.phase === "submitted" ? (
          <ApplicationComplete submitted />
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
        ) : reviewing ? (
          <ApplicationReview
            draft={draft}
            declarationAccepted={declarationAccepted}
            persistencePhase={persistence.phase}
            authenticated={persistence.authenticated}
            onRetry={() => void persistence.resendCurrentIntent()}
            onDeclarationChange={setDeclarationAccepted}
            onSubmit={() => void persistence.start("submit")}
            onEdit={() => setReviewing(false)}
          />
        ) : (
          <form
            ref={formRef}
            className="application-form"
            onSubmit={review}
            onInvalid={revealInvalidField}
          >
            <Introduction />
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
              onEmailReturnLink={persistence.emailReturnLink}
              persistenceBusy={persistence.busy}
            />
            <HousingSection draft={draft} update={update} />
            <EssaysSection draft={draft} update={update} />
            <EmploymentSection draft={draft} update={update} />
            <IncomeSection draft={draft} update={update} />

            <div className="applicant-actions">
              <button
                className="applicant-danger-link"
                type="button"
                onClick={discardLocalDraft}
              >
                <Trash2 size={16} />
                Clear this draft
              </button>
              <div className="applicant-action-stack">
                <PersistenceActionStatus
                  phase={persistence.phase}
                  onRetry={() => void persistence.resendCurrentIntent()}
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
                  <button className="applicant-primary-button" type="submit">
                    Review application
                    <FileCheck2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          </form>
        )}
      </main>

      <footer className="applicant-footer">
        <span>© Penta Co-operative Housing Association</span>
        <a href="https://www.pentacoop.com/privacy.html">Privacy</a>
        <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">Technical help</a>
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

function Introduction() {
  return (
    <section className="application-intro">
      <div className="intro-icon"><ShieldCheck size={24} /></div>
      <div>
        <h2>Before you begin</h2>
        <p>
          Penta is a family-oriented housing co-op near Jericho Beach. Please answer every required
          question so the membership committee has a complete picture of your household.
        </p>
        <p>
          We use your information to assess housing and membership eligibility and, if you are
          shortlisted, to verify references, income, and credit.
        </p>
      </div>
    </section>
  );
}

function HouseholdSection(props: {
  draft: ApplicantDraft;
  update: (fn: DraftUpdater) => void;
  authenticated: boolean;
  emailChangeOpen: boolean;
  primaryEmail: string | null;
  pendingEmailChange: string | null;
  emailChangeStatus: "idle" | "sending" | "sent" | "confirmed" | "error";
  emailChangeMessage: string;
  emailChangeNeedsReauthentication: boolean;
  onOpenEmailChange: () => void;
  onCloseEmailChange: () => void;
  onRequestEmailChange: (email: string) => void;
  onRequestReauthentication: () => void;
  onCancelEmailChange: () => void;
  onEmailReturnLink: () => Promise<boolean>;
  persistenceBusy: boolean;
}) {
  const { draft, update } = props;
  const [returnLinkStatus, setReturnLinkStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  useEffect(() => {
    setReturnLinkStatus("idle");
  }, [draft.applicant.email]);

  async function sendReturnLink(): Promise<void> {
    setReturnLinkStatus("sending");
    setReturnLinkStatus(await props.onEmailReturnLink() ? "sent" : "error");
  }

  return (
    <FormSection number="1" title="Your household" description="Start with the people who would live in the co-op.">
      <Subheading title="Primary applicant" required />
      <PersonFields
        value={draft.applicant}
        required
        onChange={(applicant) => update((current) => ({ ...current, applicant }))}
        leadingFields={(
          <>
            <PrimaryEmailField
              value={draft.applicant.email}
              locked={props.authenticated}
              wide={props.authenticated && !props.emailChangeOpen}
              showChangeAction={!props.emailChangeOpen}
              onChange={(email) => update((current) => ({
                ...current,
                applicant: { ...current.applicant, email },
              }))}
              onChangeEmail={props.onOpenEmailChange}
            />
            {!props.authenticated ? (
              <ReturnLinkAction
                email={draft.applicant.email}
                status={returnLinkStatus}
                disabled={props.persistenceBusy}
                onSend={() => void sendReturnLink()}
              />
            ) : null}
            {props.authenticated && props.emailChangeOpen && props.primaryEmail ? (
              <EmailChangeField
                currentEmail={props.primaryEmail}
                pendingEmail={props.pendingEmailChange}
                status={props.emailChangeStatus}
                message={props.emailChangeMessage}
                needsReauthentication={props.emailChangeNeedsReauthentication}
                onRequest={props.onRequestEmailChange}
                onRequestReauthentication={props.onRequestReauthentication}
                onCancelPending={props.onCancelEmailChange}
                onClose={props.onCloseEmailChange}
              />
            ) : null}
          </>
        )}
      />

      <ToggleCard
        checked={draft.hasCoApplicant}
        onChange={(hasCoApplicant) => update((current) => ({ ...current, hasCoApplicant }))}
        title="Include a co-applicant"
        description="Uncheck this if no other adult will be part of your household. Only the primary applicant can edit the application."
      />
      {draft.hasCoApplicant ? (
        <div className="conditional-fields">
          <Subheading title="Co-applicant" required />
          <PersonFields
            value={draft.coApplicant}
            required
            leadingFields={(
              <>
                <TextField
                  label="Email"
                  email
                  value={draft.coApplicant.email}
                  required
                  onChange={(email) => update((current) => ({
                    ...current,
                    coApplicant: { ...current.coApplicant, email },
                  }))}
                />
                <TextField
                  label="Relationship to applicant"
                  value={draft.coApplicant.relationship}
                  required
                  onChange={(relationship) => update((current) => ({
                    ...current,
                    coApplicant: { ...current.coApplicant, relationship },
                  }))}
                />
              </>
            )}
            onChange={(coApplicant) =>
              update((current) => ({
                ...current,
                coApplicant: { ...current.coApplicant, ...coApplicant },
              }))
            }
          />
        </div>
      ) : null}

      <div className="section-divider" />
      <div className="subheading-row">
        <Subheading title="Children" />
        <button
          className="applicant-secondary-button compact"
          type="button"
          onClick={() => update((current) => ({ ...current, children: [...current.children, newChild()] }))}
        >
          <Plus size={16} /> Add a child
        </button>
      </div>
      <p className="field-help">Add every child who would live in the unit.</p>
      {draft.children.length ? (
        <div className="repeat-grid">
          {draft.children.map((child, index) => (
            <div className="repeat-card" key={child.id}>
              <div className="repeat-card-heading">
                <strong>Child {index + 1}</strong>
                <button
                  className="text-button danger"
                  type="button"
                  onClick={() =>
                    update((current) => ({
                      ...current,
                      children: current.children.filter((item) => item.id !== child.id),
                    }))
                  }
                >
                  Remove
                </button>
              </div>
              <div className="field-grid three-column">
                <TextField label="First name" value={child.firstName} required onChange={(firstName) => updateChild(update, child.id, { firstName })} />
                <TextField label="Last name" value={child.lastName} required onChange={(lastName) => updateChild(update, child.id, { lastName })} />
                <DateField label="Date of birth" value={child.birthDate} required autoComplete="bday" onChange={(birthDate) => updateChild(update, child.id, { birthDate })} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-inline">No children added yet.</p>
      )}
    </FormSection>
  );
}

function HousingSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
  const { draft, update } = props;
  const setAddress = (patch: Partial<ApplicantDraft["currentAddress"]>) =>
    update((current) => ({ ...current, currentAddress: { ...current.currentAddress, ...patch } }));
  return (
    <FormSection number="2" title="Current housing" description="Tell us where you live now and about your housing history.">
      <Subheading title="Current address" required />
      <div className="field-grid">
        <TextField label="Street address" value={draft.currentAddress.street} required wide onChange={(street) => setAddress({ street })} />
        <TextField label="Apartment, suite, etc." value={draft.currentAddress.street2} wide onChange={(street2) => setAddress({ street2 })} />
        <TextField label="City" value={draft.currentAddress.city} required onChange={(city) => setAddress({ city })} />
        <TextField label="Province or state" value={draft.currentAddress.provinceOrState} required onChange={(provinceOrState) => setAddress({ provinceOrState })} />
        <TextField label="Postal or ZIP code" value={draft.currentAddress.postalOrZipCode} required onChange={(postalOrZipCode) => setAddress({ postalOrZipCode })} />
        <TextField label="Country" value={draft.currentAddress.country} required onChange={(country) => setAddress({ country })} />
      </div>
      <div className="field-grid">
        <YesNoField label="Have you lived here for two years or more?" value={draft.livedAtCurrentAddressTwoYears} onChange={(value) => update((current) => ({ ...current, livedAtCurrentAddressTwoYears: value }))} />
        <YesNoField label="Do you own the home where you currently live?" value={draft.ownsCurrentHome} onChange={(value) => update((current) => ({ ...current, ownsCurrentHome: value }))} />
        <YesNoField label="Do you own any other real estate?" value={draft.ownsOtherRealEstate} onChange={(value) => update((current) => ({ ...current, ownsOtherRealEstate: value }))} />
      </div>

      {draft.ownsCurrentHome === "no" ? (
        <div className="conditional-fields">
          <Subheading title="Current landlord" required />
          <p className="field-help">
            We contact your landlord only if you are selected for an interview.
          </p>
          <ReferenceFields value={draft.currentLandlord} required onChange={(currentLandlord) => update((current) => ({ ...current, currentLandlord }))} />
        </div>
      ) : null}

      {draft.ownsCurrentHome === "no" && draft.livedAtCurrentAddressTwoYears === "no" ? (
        <div className="conditional-fields">
          <Subheading title="Previous landlord or housing reference" required />
          <p className="field-help">
            Because you have lived at your current address for less than two years, please include
            your previous landlord or housing reference.
          </p>
          <ReferenceFields value={draft.previousLandlord} required onChange={(previousLandlord) => update((current) => ({ ...current, previousLandlord }))} />
        </div>
      ) : null}
    </FormSection>
  );
}

function EssaysSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
  const setEssay = (patch: Partial<ApplicantDraft["essays"]>) =>
    props.update((current) => ({ ...current, essays: { ...current.essays, ...patch } }));
  return (
    <FormSection number="3" title="Tell us more about you" description="Co-op living is collaborative. Detailed, personal answers help the committee understand what your household would bring to the community.">
      <div className="essay-fields">
        <TextArea label="Who is in your household, and what would you like us to know about you?" help="Include your employment background, interests, and values." value={props.draft.essays.householdIntroduction} required onChange={(householdIntroduction) => setEssay({ householdIntroduction })} />
        <TextArea label="What skills could your household contribute to Penta?" help="Think about the running, care, and maintenance of the co-op." value={props.draft.essays.skillsToContribute} required onChange={(skillsToContribute) => setEssay({ skillsToContribute })} />
        <TextArea label="What previous co-op experience does your household have?" help="Describe that experience, or simply say that you have none." value={props.draft.essays.previousCoopExperience} required onChange={(previousCoopExperience) => setEssay({ previousCoopExperience })} />
        <TextArea label="Why does your household want to live in a co-op?" help="Describe how your household would contribute as members of Penta." value={props.draft.essays.whyCoop} required onChange={(whyCoop) => setEssay({ whyCoop })} />
        <TextArea label="Is there anything else you’d like us to know? (optional)" help="Share anything else that would help us understand your household or application." value={props.draft.essays.additionalInformation} onChange={(additionalInformation) => setEssay({ additionalInformation })} />
        <TextArea label="What pets would live with your household? (optional)" help="Include the type and number of pets." value={props.draft.pets} compact onChange={(pets) => props.update((current) => ({ ...current, pets }))} />
      </div>
      <div className="photo-placeholder">
        <strong>Household photo (optional)</strong>
        <span>Private photo upload will be added in the next M21 stage.</span>
      </div>
    </FormSection>
  );
}

function EmploymentSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
  return (
    <FormSection number="4" title="Employment" description="Tell us the current employment status of each adult. Employer references are contacted only if your household is selected for an interview.">
      <Subheading title="Primary applicant employment" required />
      <EmploymentFields value={props.draft.applicantEmployment} required onChange={(applicantEmployment) => props.update((current) => ({ ...current, applicantEmployment }))} />
      {props.draft.hasCoApplicant ? (
        <>
          <Subheading title="Co-applicant employment" required />
          <EmploymentFields value={props.draft.coApplicantEmployment} required onChange={(coApplicantEmployment) => props.update((current) => ({ ...current, coApplicantEmployment }))} />
        </>
      ) : null}
    </FormSection>
  );
}

function IncomeSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
  const income = householdIncome(props.draft);
  return (
    <FormSection number="5" title="Household income" description="Enter yearly gross income before tax. Include employment, benefits, investments, support payments, rental income, pensions, and RRSP income.">
      <div className="income-grid">
        <MoneyField label="Primary applicant" value={props.draft.applicantIncome} required onChange={(applicantIncome) => props.update((current) => ({ ...current, applicantIncome }))} />
        {props.draft.hasCoApplicant ? (
          <MoneyField label="Co-applicant" value={props.draft.coApplicantIncome} required onChange={(coApplicantIncome) => props.update((current) => ({ ...current, coApplicantIncome }))} />
        ) : null}
        <div className="calculated-income">
          <span>Calculated household total</span>
          <strong>{income.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 })}</strong>
        </div>
      </div>
      <p className="field-help">If shortlisted, adult household members will be asked for proof of income and the management company will carry out a credit check.</p>
    </FormSection>
  );
}

function ApplicationReview(props: {
  draft: ApplicantDraft;
  declarationAccepted: boolean;
  persistencePhase: string;
  authenticated: boolean;
  onRetry: () => void;
  onDeclarationChange: (accepted: boolean) => void;
  onSubmit: () => void;
  onEdit: () => void;
}) {
  const d = props.draft;
  return (
    <div className="application-review">
      <div className="review-notice">
        <FileCheck2 size={22} />
        <div>
          <strong>{props.authenticated ? "Your application is ready to submit." : "This is still a private draft."}</strong>
          <span>Nothing has been sent to the membership committee.</span>
        </div>
      </div>
      <ReviewSection title="Household">
        <ReviewRow label="Primary applicant" value={`${d.applicant.firstName} ${d.applicant.lastName}`} />
        <ReviewRow label="Email" value={d.applicant.email} />
        <ReviewRow label="Co-applicant" value={d.hasCoApplicant ? `${d.coApplicant.firstName} ${d.coApplicant.lastName}` : "None"} />
        <ReviewRow label="Children" value={String(d.children.length)} />
      </ReviewSection>
      <ReviewSection title="Current housing">
        <ReviewRow label="Address" value={`${d.currentAddress.street}, ${d.currentAddress.city}, ${d.currentAddress.provinceOrState}`} />
        <ReviewRow label="Current landlord" value={d.currentLandlord.name} />
      </ReviewSection>
      <ReviewSection title="Income">
        <ReviewRow label="Yearly household income" value={householdIncome(d).toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 })} />
      </ReviewSection>
      <section className="declaration-card">
        <ShieldCheck size={24} />
        <div>
          <h2>Declaration and privacy</h2>
          <p>By submitting this application, I / we understand that:</p>
          <ul>
            <li>Personal property and liability insurance of at least $1,000,000 is required.</li>
            <li>Required shares and the first housing charge are due if membership is approved.</li>
            <li>Penta may verify housing, employment, income, references, and credit information.</li>
            <li>Accepted members must follow Penta's Rules, Occupancy Agreement, and Policies.</li>
            <li>Incomplete or false information may result in termination of membership.</li>
          </ul>
          <p>
            Penta handles this information as described in its{" "}
            <a href="https://www.pentacoop.com/privacy.html">Privacy Policy</a>.
          </p>
          <label className="declaration-acceptance">
            <input
              type="checkbox"
              checked={props.declarationAccepted}
              onChange={(event) => props.onDeclarationChange(event.target.checked)}
            />
            <span>I / We have read and agree to be bound by the conditions outlined above.</span>
          </label>
        </div>
      </section>
      <div className="applicant-action-stack">
        <PersistenceActionStatus
          phase={props.persistencePhase}
          onRetry={props.onRetry}
        />
        <div className="review-actions">
          <button className="applicant-secondary-button" type="button" onClick={props.onEdit}>
            <ChevronLeft size={17} /> Return to editing
          </button>
          <button
            className="applicant-primary-button"
            type="button"
            disabled={!props.declarationAccepted}
            onClick={props.onSubmit}
          >
            {props.authenticated ? "Submit application" : "Save and email secure link"}
            {props.authenticated ? <FileCheck2 size={18} /> : <Mail size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}

function PersistenceNotice(props: {
  phase: string;
  message: string;
}) {
  if (props.phase === "error") {
    return (
      <div className="persistence-notice error" role="alert">
        <div><strong>We couldn't continue</strong><span>{props.message}</span></div>
      </div>
    );
  }
  if (props.phase === "email_sent" || props.phase === "saved") {
    return (
      <div className="persistence-notice success" role="status">
        <CheckCircle2 size={20} />
        <div>
          <strong>{props.phase === "saved" ? "Application saved" : "Check your email"}</strong>
          {props.message ? <span>{props.message}</span> : null}
        </div>
      </div>
    );
  }
  return null;
}

function PersistenceActionStatus(props: {
  phase: string;
  onRetry: () => void;
}) {
  if (props.phase === "working") {
    return <p className="persistence-action-status" role="status">Saving securely…</p>;
  }
  if (props.phase === "email_sent") {
    return (
      <div className="persistence-action-status" role="status">
        <span className="persistence-action-confirmation">
          <Mail size={16} /> Application saved for 30 days
        </span>
        <span>Check your email for a secure return link.</span>
        <span>
          Didn’t receive it? Double-check the email address above, then{" "}
          <button type="button" onClick={props.onRetry}>try again</button>.
        </span>
      </div>
    );
  }
  return null;
}

function ApplicationComplete(props: { submitted: boolean }) {
  return (
    <section className="application-complete">
      <CheckCircle2 size={34} />
      <h2>{props.submitted ? "Application submitted" : "Application saved"}</h2>
      <p>
        {props.submitted
          ? "Your application has been sent to the membership committee. A confirmation and secure return link are on their way."
          : "Your private application draft is saved. A secure return link is on its way."}
      </p>
    </section>
  );
}

function AccessLinkReady(props: {
  email: string;
  applicationEmail: string | null;
  purpose: "applicant_access" | "email_change";
  onOpen: (rememberDevice: boolean) => void;
}) {
  const [rememberDevice, setRememberDevice] = useState(false);
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>
        {props.purpose === "email_change" ? "Change your application email to" : "You’re signing in as"}
        <span className="access-email">{props.email}</span>
      </h2>
      {props.purpose === "email_change" && props.applicationEmail ? (
        <p>The application currently uses {props.applicationEmail}.</p>
      ) : null}
      <label className="remember-device-choice">
        <input
          type="checkbox"
          checked={rememberDevice}
          onChange={(event) => setRememberDevice(event.target.checked)}
        />
        <span>Keep me signed in on this device</span>
      </label>
      <button
        className="applicant-primary-button"
        type="button"
        onClick={() => props.onOpen(rememberDevice)}
      >
        {props.purpose === "email_change" ? "Confirm email address" : "Open application"}
      </button>
    </section>
  );
}

function AccessLinkDecision(props: {
  conflict: {
    currentEmail: string;
    linkEmail: string;
    applicationEmail: string | null;
    purpose: "applicant_access" | "email_change";
    linkIsValid: boolean;
  };
  onKeepCurrent: () => void;
  onOpenLinked: (rememberDevice: boolean) => void;
  onEmailNew: () => void;
}) {
  const [rememberDevice, setRememberDevice] = useState(false);
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>{props.conflict.purpose === "email_change" ? "Choose how to continue" : "Choose which application to open"}</h2>
      <p>
        {props.conflict.purpose === "email_change"
          ? "This browser has a different application open."
          : "This browser and the email link belong to different applicants."}
      </p>
      <dl className="access-identity-list">
        <div><dt>Currently open</dt><dd>{props.conflict.currentEmail}</dd></div>
        <div><dt>{props.conflict.purpose === "email_change" ? "New email" : "Email link"}</dt><dd>{props.conflict.linkEmail}</dd></div>
        {props.conflict.purpose === "email_change" && props.conflict.applicationEmail ? (
          <div><dt>Application being changed</dt><dd>{props.conflict.applicationEmail}</dd></div>
        ) : null}
      </dl>
      {props.conflict.linkIsValid ? (
        <label className="remember-device-choice">
          <input
            type="checkbox"
            checked={rememberDevice}
            onChange={(event) => setRememberDevice(event.target.checked)}
          />
          <span>Keep me signed in on this device</span>
        </label>
      ) : null}
      <div className="review-actions">
        <button className="applicant-secondary-button" type="button" onClick={props.onKeepCurrent}>
          Keep current application
        </button>
        <button
          className="applicant-primary-button"
          type="button"
          onClick={
            props.conflict.linkIsValid
              ? () => props.onOpenLinked(rememberDevice)
              : props.onEmailNew
          }
        >
          {props.conflict.linkIsValid
            ? props.conflict.purpose === "email_change" ? "Confirm email change" : "Open linked application"
            : props.conflict.purpose === "email_change" ? "Email a new confirmation" : "Email a new link"}
        </button>
      </div>
    </section>
  );
}

function ExpiredAccessLink(props: {
  purpose: "applicant_access" | "email_change";
  onEmailNew: () => void;
}) {
  return (
    <section className="existing-application-choice">
      <Mail size={28} />
      <h2>This secure link is no longer active</h2>
      <p>
        {props.purpose === "email_change"
          ? "Your email address has not been changed. We can send a fresh confirmation to the same address."
          : "Your application has not been deleted. We can email a fresh 24-hour link to the same address."}
      </p>
      <button className="applicant-primary-button" type="button" onClick={props.onEmailNew}>
        {props.purpose === "email_change" ? "Email a new confirmation" : "Email a new link"}
      </button>
    </section>
  );
}

function InvalidAccessLink() {
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>This link cannot open an application</h2>
      <p>It may be incomplete, or its private draft may have passed the 30-day retention period.</p>
    </section>
  );
}

function FormSection(props: { number: string; title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="form-section">
      <header className="form-section-header">
        <span>{props.number}</span>
        <div><h2>{props.title}</h2><p>{props.description}</p></div>
      </header>
      <div className="form-section-body">{props.children}</div>
    </section>
  );
}

function Subheading(props: { title: string; required?: boolean }) {
  return <h3 className="form-subheading">{props.title}{props.required ? <Required /> : null}</h3>;
}

function Required() { return <span className="required-mark" aria-label="required">*</span>; }

function TextField(props: { label: string; value: string; onChange: (value: string) => void; type?: string; email?: boolean; phone?: boolean; required?: boolean; wide?: boolean; help?: string; inputMode?: "numeric"; maxLength?: number; placeholder?: string }) {
  return (
    <label className={`applicant-field${props.wide ? " wide" : ""}`}>
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <input
        type={props.email || props.phone ? "text" : props.type ?? "text"}
        value={props.value}
        required={props.required}
        inputMode={props.email ? "email" : props.phone ? "tel" : props.inputMode}
        data-email={props.email ? "true" : undefined}
        data-phone={props.phone ? "true" : undefined}
        maxLength={props.maxLength}
        placeholder={props.placeholder}
        onInput={(event) => event.currentTarget.setCustomValidity("")}
        onChange={(event) => props.onChange(event.target.value)}
      />
      {props.help ? <small>{props.help}</small> : null}
    </label>
  );
}

function DateField(props: {
  label: string;
  value: string;
  required?: boolean;
  autoComplete?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="applicant-field">
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <input
        type="text"
        inputMode="numeric"
        autoComplete={props.autoComplete}
        data-date="true"
        placeholder="YYYY-MM-DD"
        value={props.value}
        required={props.required}
        maxLength={10}
        onInput={(event) => event.currentTarget.setCustomValidity("")}
        onChange={(event) => {
          const value = formatIsoDate(event.currentTarget.value);
          props.onChange(value);
        }}
      />
    </label>
  );
}

function TextArea(props: { label: string; help?: string; value: string; required?: boolean; compact?: boolean; onChange: (value: string) => void }) {
  return (
    <label className={`applicant-field wide${props.compact ? " compact" : ""}`}>
      <span>{props.label}{props.required ? <Required /> : null}</span>
      {props.help ? <small>{props.help}</small> : null}
      <textarea rows={props.compact ? 3 : 6} value={props.value} required={props.required} onChange={(event) => props.onChange(event.target.value)} />
    </label>
  );
}

function PersonFields(props: {
  value: PersonDraft;
  required: boolean;
  leadingFields: React.ReactNode;
  onChange: (value: PersonDraft) => void;
}) {
  const set = (patch: Partial<PersonDraft>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="field-grid">
      {props.leadingFields}
      <TextField label="First name" value={props.value.firstName} required={props.required} onChange={(firstName) => set({ firstName })} />
      <TextField label="Last name" value={props.value.lastName} required={props.required} onChange={(lastName) => set({ lastName })} />
      <DateField label="Date of birth" value={props.value.birthDate} required={props.required} autoComplete="bday" onChange={(birthDate) => set({ birthDate })} />
      <TextField label="Phone" phone maxLength={12} placeholder="XXX-XXX-XXXX" value={props.value.phone} required={props.required} onChange={(phone) => set({ phone: formatPhone(phone) })} />
    </div>
  );
}

function PrimaryEmailField(props: {
  value: string;
  locked: boolean;
  wide: boolean;
  showChangeAction: boolean;
  onChange: (email: string) => void;
  onChangeEmail: () => void;
}) {
  if (!props.locked) {
    return <TextField label="Email" email value={props.value} required onChange={props.onChange} />;
  }
  return (
    <div className={`applicant-field authenticated-email-field${props.wide ? " wide" : ""}`}>
      <span>Email<Required /></span>
      <div className="verified-email-control">
        <input type="text" value={props.value} readOnly data-email="true" />
        {props.showChangeAction ? (
          <button className="text-button" type="button" onClick={props.onChangeEmail}>
            Change email address
          </button>
        ) : null}
      </div>
    </div>
  );
}

function ReturnLinkAction(props: {
  email: string;
  status: "idle" | "sending" | "sent" | "error";
  disabled: boolean;
  onSend: () => void;
}) {
  const validEmail = EMAIL_PATTERN.test(props.email.trim());
  return (
    <div className="applicant-field return-link-field">
      <span>Already started an application?</span>
      <button
        className="applicant-secondary-button"
        type="button"
        disabled={!validEmail || props.disabled || props.status === "sending"}
        onClick={props.onSend}
      >
        <Mail size={16} /> Email me a link to continue
      </button>
      {props.status === "sent" ? (
        <small className="field-success" role="status">
          A secure link is on its way. Check your inbox to continue your application.
        </small>
      ) : null}
      {props.status === "error" ? (
        <small className="field-error" role="alert">
          We couldn’t request a return link. Email{" "}
          <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">
            Penta Tech Support
          </a>.
        </small>
      ) : null}
    </div>
  );
}

function EmailChangeField(props: {
  currentEmail: string;
  pendingEmail: string | null;
  status: "idle" | "sending" | "sent" | "confirmed" | "error";
  message: string;
  needsReauthentication: boolean;
  onRequest: (email: string) => void;
  onRequestReauthentication: () => void;
  onCancelPending: () => void;
  onClose: () => void;
}) {
  const [newEmail, setNewEmail] = useState("");
  const [editing, setEditing] = useState(!props.pendingEmail);
  const [validationMessage, setValidationMessage] = useState("");

  useEffect(() => setEditing(!props.pendingEmail), [props.pendingEmail]);

  if (props.status === "confirmed") {
    return (
      <div className="email-change-field success" role="status">
        <span>Email address changed</span>
        <div className="email-change-status">
          <span>You are now signed in as {props.currentEmail}.</span>
        </div>
        <button className="applicant-secondary-button compact" type="button" onClick={props.onClose}>Done</button>
      </div>
    );
  }

  if (props.pendingEmail && !editing) {
    return (
      <div className="email-change-field" role="status">
        <span>New email address</span>
        <div className="email-change-status">
          <strong>Check {props.pendingEmail}</strong>
          <span>{props.message || "Use the confirmation link to finish changing your email address."}</span>
        </div>
        <div className="email-change-actions confirmation-actions">
          <button className="applicant-secondary-button compact" type="button" onClick={() => setEditing(true)}>Use a different email</button>
          <button className="applicant-secondary-button compact danger" type="button" onClick={props.onCancelPending}>Cancel change</button>
        </div>
      </div>
    );
  }

  function sendConfirmation(): void {
    const normalized = newEmail.trim();
    if (!EMAIL_PATTERN.test(normalized)) {
      setValidationMessage(EMAIL_INVALID_MESSAGE);
      return;
    }
    if (normalized.toLowerCase() === props.currentEmail.toLowerCase()) {
      setValidationMessage("Enter a different email address.");
      return;
    }
    setValidationMessage("");
    props.onRequest(normalized);
  }

  return (
    <div className="email-change-field">
      <label className="applicant-field">
        <span>New email address</span>
        <input
          type="text"
          inputMode="email"
          autoComplete="email"
          value={newEmail}
          onChange={(event) => { setNewEmail(event.target.value); setValidationMessage(""); }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              sendConfirmation();
            }
          }}
          autoFocus
        />
        {validationMessage ? <small className="field-error">{validationMessage}</small> : null}
        {props.status === "error" && props.message ? <small className="field-error">{props.message}</small> : null}
        {props.needsReauthentication ? (
          <button className="text-button email-reauthentication-button" type="button" onClick={props.onRequestReauthentication}>
            Email me a fresh sign-in link
          </button>
        ) : null}
      </label>
      <div className="email-change-actions">
        <button className="applicant-secondary-button compact" type="button" onClick={props.pendingEmail ? () => setEditing(false) : props.onClose}>Cancel</button>
        <button className="applicant-primary-button compact" type="button" disabled={props.status === "sending"} onClick={sendConfirmation}>
          {props.status === "sending" ? "Sending…" : "Send confirmation link"}
        </button>
      </div>
    </div>
  );
}

function ReferenceFields(props: { value: ReferenceDraft; required: boolean; onChange: (value: ReferenceDraft) => void }) {
  const set = (patch: Partial<ReferenceDraft>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="field-grid three-column">
      <TextField label="Name" value={props.value.name} required={props.required} onChange={(name) => set({ name })} />
      <TextField label="Email" email value={props.value.email} required={props.required} onChange={(email) => set({ email })} />
      <TextField label="Phone" phone maxLength={12} placeholder="XXX-XXX-XXXX" value={props.value.phone} required={props.required} onChange={(phone) => set({ phone: formatPhone(phone) })} />
    </div>
  );
}

function EmploymentFields(props: { value: EmploymentDraft; required: boolean; onChange: (value: EmploymentDraft) => void }) {
  const set = (patch: Partial<EmploymentDraft>) => props.onChange({ ...props.value, ...patch });
  const employed = props.value.status === "employed";
  const working = employed || props.value.status === "self_employed";
  return (
    <div className="employment-fields">
      <SelectField
        label="Employment status"
        value={props.value.status}
        required={props.required}
        options={[
          ["employed", "Employed"],
          ["self_employed", "Self-employed"],
          ["unemployed", "Not currently employed"],
        ]}
        onChange={(status) => set({ status: status as EmploymentDraft["status"] })}
      />
      {working ? (
        <>
          <div className="field-grid three-column employment-detail-grid">
            <TextField
              label={employed ? "Job title" : "Type of business"}
              value={props.value.jobTitle}
              required
              onChange={(jobTitle) => set({ jobTitle })}
            />
            <TextField
              label={employed ? "Company name" : "Business name"}
              value={props.value.companyName}
              required
              onChange={(companyName) => set({ companyName })}
            />
            <DateField
              label={employed ? "Start date" : "Self-employed since"}
              value={props.value.startDate}
              required
              onChange={(startDate) => set({ startDate })}
            />
          </div>
          {employed ? (
            <>
              <h4>Current manager</h4>
              <ReferenceFields
                value={props.value.manager}
                required
                onChange={(manager) => set({ manager })}
              />
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function SelectField(props: {
  label: string;
  value: string;
  required?: boolean;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="applicant-field employment-status-field">
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <select
        value={props.value}
        required={props.required}
        onChange={(event) => props.onChange(event.target.value)}
      >
        <option value="">Select one</option>
        {props.options.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
    </label>
  );
}

function MoneyField(props: { label: string; value: string; required?: boolean; onChange: (value: string) => void }) {
  return (
    <label className="applicant-field money-field">
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <div><span>$</span><input type="number" step="any" inputMode="numeric" data-money="true" value={props.value} required={props.required} onInput={(event) => event.currentTarget.setCustomValidity("")} onChange={(event) => props.onChange(event.target.value)} /></div>
    </label>
  );
}

function YesNoField(props: { label: string; value: YesNo; onChange: (value: YesNo) => void }) {
  const name = props.label.replaceAll(" ", "-");
  return (
    <fieldset className="yes-no-field">
      <legend>{props.label}<Required /></legend>
      <label><input type="radio" name={name} value="yes" checked={props.value === "yes"} required onChange={() => props.onChange("yes")} /> Yes</label>
      <label><input type="radio" name={name} value="no" checked={props.value === "no"} required onChange={() => props.onChange("no")} /> No</label>
    </fieldset>
  );
}

function ToggleCard(props: { checked: boolean; onChange: (checked: boolean) => void; title: string; description: string }) {
  return (
    <label className="toggle-card">
      <input type="checkbox" checked={props.checked} onChange={(event) => props.onChange(event.target.checked)} />
      <span><strong>{props.title}</strong><small>{props.description}</small></span>
    </label>
  );
}

function ReviewSection(props: { title: string; children: React.ReactNode }) {
  return <section className="review-section"><h2>{props.title}</h2><dl>{props.children}</dl></section>;
}

function ReviewRow(props: { label: string; value: string }) {
  return <div><dt>{props.label}</dt><dd>{props.value || "—"}</dd></div>;
}

function updateChild(update: (fn: DraftUpdater) => void, id: string, patch: Partial<ApplicantDraft["children"][number]>): void {
  update((current) => ({
    ...current,
    children: current.children.map((child) => (child.id === id ? { ...child, ...patch } : child)),
  }));
}

function formatPhone(value: string): string {
  if (
    /^[0-9]{0,3}$/.test(value) ||
    /^[0-9]{3}-[0-9]{0,3}$/.test(value) ||
    /^[0-9]{3}-[0-9]{3}-[0-9]{0,4}$/.test(value)
  ) {
    return value;
  }
  const digits = value.replace(/\D/g, "").slice(0, 10);
  if (!digits) return "";
  if (digits.length <= 3) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function formatIsoDate(value: string): string {
  if (
    /^[0-9]{0,4}$/.test(value) ||
    /^[0-9]{4}-[0-9]{0,2}$/.test(value) ||
    /^[0-9]{4}-[0-9]{2}-[0-9]{0,2}$/.test(value)
  ) {
    return value;
  }
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}

function isValidIsoDate(value: string): boolean {
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function validateFormFields(form: HTMLFormElement | null): void {
  form?.querySelectorAll<HTMLInputElement>("input[data-email]").forEach(validateEmailField);
  form?.querySelectorAll<HTMLInputElement>("input[data-date]").forEach((input) => {
    const value = input.value;
    input.setCustomValidity(
      value && !isValidIsoDate(value) ? "Enter a valid date in YYYY-MM-DD format." : "",
    );
  });
  form?.querySelectorAll<HTMLInputElement>("input[data-phone]").forEach((input) => {
    const value = input.value;
    input.setCustomValidity(
      value && !PHONE_PATTERN.test(value) ? "Enter a 10-digit phone number." : "",
    );
  });
  form?.querySelectorAll<HTMLInputElement>("input[data-money]").forEach((input) => {
    const amount = Number(input.value);
    input.setCustomValidity(
      input.value && (!Number.isInteger(amount) || amount < 0)
        ? "Enter a whole-dollar amount of zero or more."
        : "",
    );
  });
}

function validateEmailField(input: HTMLInputElement | null): void {
  if (!input) return;
  const email = input.value.trim();
  input.setCustomValidity(email && !EMAIL_PATTERN.test(email) ? EMAIL_INVALID_MESSAGE : "");
}
