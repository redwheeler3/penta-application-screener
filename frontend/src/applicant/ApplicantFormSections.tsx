import { CalendarDays, Plus, ShieldCheck } from "lucide-react";
import type { RefObject } from "react";

import { formatOpeningDate, openingLabel } from "./ApplicantAccessScreens";
import { EmailChangeField, PrimaryEmailField } from "./ApplicantEmailFields";
import {
    DateField,
  EmploymentFields,
  FormSection,
  MoneyField,
  PersonFields,
  ReferenceFields,
  Subheading,
  TextArea,
  TextField,
  ToggleCard,
  type DraftUpdater,
  updateChild,
  YesNoField,
} from "./ApplicantFormFields";
import {
  type ApplicantDraft,
  type ApplicantOpening,
  householdIncome,
  newChild,
} from "./types";

export function Introduction() {
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
          We collect and use the information in this form to contact you, assess eligibility for
          housing, membership, the Home Owner Grant, or an internal move, and, if you are
          shortlisted, verify housing references, employment, income, and credit.
        </p>
        <p>
          Where necessary, your information may be available to Penta&apos;s authorized committee
          members, directors, treasurer, auditor, lawyer, management company, municipal employees
          processing a Home Owner Grant, and service providers acting for Penta, including hosting,
          email, and AI-processing providers. It is available to the general membership only when
          relevant to an appeal you make about a Board decision.
        </p>
        <p>
          Non-member applications are retained until one year after the latest relevant move-in
          date; accepted-member records are retained for seven years. Read our{" "}
          <a href="https://www.pentacoop.com/privacy.html" target="_blank" rel="noopener noreferrer">
            Privacy Policy
          </a>.
        </p>
      </div>
    </section>
  );
}

export function OpeningSelection(props: {
  sectionRef: RefObject<HTMLElement | null>;
  openings: ApplicantOpening[];
  selectedIds: number[];
  showError: boolean;
  onChange: (openingId: number, selected: boolean) => void;
}) {
  const currentOpenings = props.openings.filter(
    (opening) => opening.phase === "open" || opening.phase === "closed",
  );
  return (
    <section
      ref={props.sectionRef}
      className={`applicant-opening-section${props.showError ? " has-error" : ""}`}
    >
      <div className="applicant-opening-heading">
        <CalendarDays size={22} />
        <div>
          <h2>Which opening are you applying for?</h2>
          <p>Select every home you would like the membership committee to consider you for.</p>
        </div>
      </div>
      {props.showError ? (
        <p className="applicant-opening-error" role="alert">
          Choose at least one opening before reviewing your application.
        </p>
      ) : null}
      <div className="applicant-opening-options">
        {currentOpenings.map((opening) => {
          const selected = props.selectedIds.includes(opening.id);
          const enabled = opening.canSelect || opening.canWithdraw;
          return (
            <label
              key={opening.id}
              className={`applicant-opening-option${selected ? " is-selected" : ""}${enabled ? "" : " is-disabled"}`}
            >
              <input
                type="checkbox"
                checked={selected}
                disabled={!enabled}
                onChange={(event) => props.onChange(opening.id, event.target.checked)}
              />
              <span className="applicant-opening-copy">
                <strong>{openingLabel(opening)}</strong>
                <span className="applicant-opening-phase">{openingPhaseLabel(opening, selected)}</span>
                <span className="applicant-opening-dates">
                  <span><b>Opens</b>{formatOpeningDate(opening.applicationOpenDate)}</span>
                  <span><b>Closes</b>{formatOpeningDate(opening.applicationCloseDate)}</span>
                  <span><b>Move-in</b>{formatOpeningDate(opening.moveInDate)}</span>
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </section>
  );
}

function openingPhaseLabel(opening: ApplicantOpening, selected: boolean): string {
  if (opening.phase === "open") return "Applications are open.";
  if (opening.phase === "closed") {
    if (selected) return "Applications are closed. Unchecking withdraws your application.";
    if (opening.participating) return "Applications are closed. Recheck to remain applied.";
    return "Applications are closed. You can’t apply for this opening.";
  }
  return "Opening status unavailable";
}

export function HouseholdSection(props: {
  draft: ApplicantDraft;
  update: (fn: DraftUpdater) => void;
  authenticated: boolean;
  emailChangeOpen: boolean;
  primaryEmail: string | null;
  pendingEmailChange: string | null;
  emailChangeStatus: "idle" | "sending" | "sent" | "confirmed" | "error";
  emailChangeMessage: string;
  googleDisconnectedByEmailChange: boolean;
  onOpenEmailChange: () => void;
  onCloseEmailChange: () => void;
  onRequestEmailChange: (email: string) => void;
  onCancelEmailChange: () => void;
}) {
  const { draft, update } = props;

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
            {props.authenticated && props.emailChangeOpen && props.primaryEmail ? (
              <EmailChangeField
                currentEmail={props.primaryEmail}
                pendingEmail={props.pendingEmailChange}
                status={props.emailChangeStatus}
                message={props.emailChangeMessage}
                googleDisconnected={props.googleDisconnectedByEmailChange}
                onRequest={props.onRequestEmailChange}
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
        description="Uncheck this if no other adult will be part of your household."
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

export function HousingSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
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

export function EssaysSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
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
        <TextField
          label="Would you like to share a household photo? (optional)"
          help="Paste a link to a photo of yourself and your household. Make sure the committee can open it."
          placeholder="https://"
          url
          value={props.draft.householdPhotoLink}
          onChange={(householdPhotoLink) => props.update((current) => ({ ...current, householdPhotoLink }))}
        />
      </div>
    </FormSection>
  );
}

export function EmploymentSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
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

export function IncomeSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
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
