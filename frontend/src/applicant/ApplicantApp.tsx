import { ChevronLeft, FileCheck2, Plus, Save, ShieldCheck, Trash2 } from "lucide-react";
import { type FormEvent, type InvalidEvent, useEffect, useMemo, useRef, useState } from "react";

import { HouseIcon } from "../HouseIcon";
import { clearDraft, hasDraftContent, loadDraft, saveDraft } from "./draftStorage";
import {
  type ApplicantDraft,
  type EmploymentDraft,
  householdIncome,
  newChild,
  type PersonDraft,
  type ReferenceDraft,
  type YesNo,
} from "./types";

const EMAIL_PATTERN = "[^\\s@]+@[^\\s@.]+(?:\\.[^\\s@.]+)+";

type DraftUpdater = (current: ApplicantDraft) => ApplicantDraft;

export function ApplicantApp() {
  const loaded = useMemo(loadDraft, []);
  const [draft, setDraft] = useState(loaded.draft);
  const [savedAt, setSavedAt] = useState<Date | null>(loaded.savedAt);
  const [reviewing, setReviewing] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const invalidTarget = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!hasDraftContent(draft)) return;
    const timeout = window.setTimeout(() => setSavedAt(saveDraft(draft)), 350);
    return () => window.clearTimeout(timeout);
  }, [draft]);

  useEffect(() => {
    if (!hasDraftContent(draft)) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [draft]);

  function update(updater: DraftUpdater): void {
    setReviewing(false);
    setDraft(updater);
  }

  function review(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!formRef.current?.reportValidity()) return;
    setSavedAt(saveDraft(draft));
    setReviewing(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
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
    if (!window.confirm("Clear this application draft from this browser?")) return;
    clearDraft();
    window.location.reload();
  }

  return (
    <div className="applicant-surface">
      <header className="applicant-header">
        <a className="applicant-brand" href="https://www.pentacoop.com/">
          <HouseIcon />
          <span>Penta Housing Co-Op</span>
        </a>
      </header>

      <main className="applicant-main">
        <div className="applicant-title-row">
          <div>
            <h1>{reviewing ? "Review your application" : "Application for Membership"}</h1>
            <p>
              {reviewing
                ? "Check your answers before continuing to the secure submission step."
                : "Take your time. Your progress is saved privately in this browser as you type."}
            </p>
          </div>
          <DraftStatus savedAt={savedAt} hasContent={hasDraftContent(draft)} />
        </div>

        {reviewing ? (
          <ApplicationReview draft={draft} onEdit={() => setReviewing(false)} />
        ) : (
          <form
            ref={formRef}
            className="application-form"
            onSubmit={review}
            onInvalid={revealInvalidField}
          >
            <Introduction />
            <HouseholdSection draft={draft} update={update} />
            <HousingSection draft={draft} update={update} />
            <EssaysSection draft={draft} update={update} />
            <EmploymentSection draft={draft} update={update} />
            <IncomeSection draft={draft} update={update} />

            <div className="applicant-actions">
              <button className="applicant-danger-link" type="button" onClick={discardLocalDraft}>
                <Trash2 size={16} />
                Clear this draft
              </button>
              <button className="applicant-primary-button" type="submit">
                Review application
                <FileCheck2 size={18} />
              </button>
            </div>
          </form>
        )}
      </main>

      <footer className="applicant-footer">
        <span>© Penta Co-operative Housing Association</span>
        <a href="https://www.pentacoop.com/privacy.html">Privacy</a>
        <a href="mailto:techsupport@pentacoop.com">Technical help</a>
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
          shortlisted, to verify references, income, and credit. Draft answers stay on this device
          until you choose to save them securely or submit your application.
        </p>
      </div>
    </section>
  );
}

function HouseholdSection(props: { draft: ApplicantDraft; update: (fn: DraftUpdater) => void }) {
  const { draft, update } = props;
  return (
    <FormSection number="1" title="Your household" description="Start with the people who would live in the co-op.">
      <Subheading title="Primary applicant" required />
      <PersonFields
        value={draft.applicant}
        required
        onChange={(applicant) => update((current) => ({ ...current, applicant }))}
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
            onChange={(coApplicant) =>
              update((current) => ({
                ...current,
                coApplicant: { ...current.coApplicant, ...coApplicant },
              }))
            }
          />
          <TextField
            label="Relationship to applicant"
            value={draft.coApplicant.relationship}
            required
            onChange={(relationship) =>
              update((current) => ({
                ...current,
                coApplicant: { ...current.coApplicant, relationship },
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
                <TextField label="Date of birth" type="date" value={child.birthDate} required onChange={(birthDate) => updateChild(update, child.id, { birthDate })} />
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
        <TextArea label="Introduce yourself and your family" help="Include your employment background, interests, and values." value={props.draft.essays.householdIntroduction} required onChange={(householdIntroduction) => setEssay({ householdIntroduction })} />
        <TextArea label="What skills could your household contribute?" help="Think about the running, care, and maintenance of the co-op." value={props.draft.essays.skillsToContribute} required onChange={(skillsToContribute) => setEssay({ skillsToContribute })} />
        <TextArea label="Tell us about any previous co-op experience" help="If you do not have previous co-op experience, simply say so." value={props.draft.essays.previousCoopExperience} required onChange={(previousCoopExperience) => setEssay({ previousCoopExperience })} />
        <TextArea label="Why do you want to live in a co-op?" help="Tell us how you would be a valuable member of Penta." value={props.draft.essays.whyCoop} required onChange={(whyCoop) => setEssay({ whyCoop })} />
        <TextArea label="Pets (optional)" help="Tell us about any pets that would live with your household." value={props.draft.pets} compact onChange={(pets) => props.update((current) => ({ ...current, pets }))} />
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
        <div className="conditional-fields">
          <Subheading title="Co-applicant employment" required />
          <EmploymentFields value={props.draft.coApplicantEmployment} required onChange={(coApplicantEmployment) => props.update((current) => ({ ...current, coApplicantEmployment }))} />
        </div>
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

function ApplicationReview(props: { draft: ApplicantDraft; onEdit: () => void }) {
  const d = props.draft;
  return (
    <div className="application-review">
      <div className="review-notice">
        <FileCheck2 size={22} />
        <div>
          <strong>This is still a private browser draft.</strong>
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
      <section className="review-next-step">
        <ShieldCheck size={24} />
        <div>
          <h2>Secure submission comes next</h2>
          <p>The next implementation step will verify your email, present the declaration and privacy notice, and submit this application. This development screen cannot send your answers yet.</p>
        </div>
      </section>
      <button className="applicant-secondary-button" type="button" onClick={props.onEdit}>
        <ChevronLeft size={17} /> Return to editing
      </button>
    </div>
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

function TextField(props: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; wide?: boolean; help?: string; inputMode?: "numeric"; minLength?: number; maxLength?: number; pattern?: string; invalidMessage?: string }) {
  return (
    <label className={`applicant-field${props.wide ? " wide" : ""}`}>
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <input
        type={props.type ?? "text"}
        value={props.value}
        required={props.required}
        inputMode={props.inputMode}
        minLength={props.minLength}
        maxLength={props.maxLength}
        pattern={props.pattern}
        onInvalid={(event) => {
          if (event.currentTarget.value && props.invalidMessage) {
            event.currentTarget.setCustomValidity(props.invalidMessage);
          }
        }}
        onInput={(event) => event.currentTarget.setCustomValidity("")}
        onChange={(event) => {
          const completedBlankDate = props.type === "date" && !props.value && event.target.value;
          props.onChange(event.target.value);
          if (completedBlankDate) focusNextFormControl(event.currentTarget);
        }}
      />
      {props.help ? <small>{props.help}</small> : null}
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

function PersonFields(props: { value: PersonDraft; required: boolean; onChange: (value: PersonDraft) => void }) {
  const set = (patch: Partial<PersonDraft>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="field-grid">
      <TextField label="First name" value={props.value.firstName} required={props.required} onChange={(firstName) => set({ firstName })} />
      <TextField label="Last name" value={props.value.lastName} required={props.required} onChange={(lastName) => set({ lastName })} />
      <TextField label="Date of birth" type="date" value={props.value.birthDate} required={props.required} onChange={(birthDate) => set({ birthDate })} />
      <TextField label="Phone" type="tel" inputMode="numeric" minLength={14} maxLength={14} value={props.value.phone} required={props.required} onChange={(phone) => set({ phone: formatPhone(phone) })} />
      <TextField label="Email" type="email" pattern={EMAIL_PATTERN} invalidMessage="This is not a valid email address." value={props.value.email} required={props.required} onChange={(email) => set({ email })} />
    </div>
  );
}

function ReferenceFields(props: { value: ReferenceDraft; required: boolean; onChange: (value: ReferenceDraft) => void }) {
  const set = (patch: Partial<ReferenceDraft>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="field-grid three-column">
      <TextField label="Name" value={props.value.name} required={props.required} onChange={(name) => set({ name })} />
      <TextField label="Email" type="email" pattern={EMAIL_PATTERN} invalidMessage="This is not a valid email address." value={props.value.email} required={props.required} onChange={(email) => set({ email })} />
      <TextField label="Phone" type="tel" inputMode="numeric" minLength={14} maxLength={14} value={props.value.phone} required={props.required} onChange={(phone) => set({ phone: formatPhone(phone) })} />
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
            <TextField
              label={employed ? "Start date" : "Self-employed since"}
              type="date"
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
      <div><span>$</span><input type="number" min="0" step="1" inputMode="numeric" value={props.value} required={props.required} onChange={(event) => props.onChange(event.target.value)} /></div>
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
  const digits = value.replace(/\D/g, "").slice(0, 10);
  if (!digits) return "";
  if (digits.length < 4) return `(${digits}`;
  if (digits.length < 7) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function focusNextFormControl(current: HTMLInputElement): void {
  const controls = Array.from(
    current.form?.querySelectorAll<HTMLElement>("input, select, textarea, button") ?? [],
  ).filter((control) => !control.hasAttribute("disabled") && control.tabIndex !== -1);
  const next = controls[controls.indexOf(current) + 1];
  next?.focus();
}
