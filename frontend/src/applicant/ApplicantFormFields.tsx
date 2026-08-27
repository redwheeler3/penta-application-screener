import type { ReactNode } from "react";

import type {
  ApplicantDraft,
  EmploymentDraft,
  PersonDraft,
  ReferenceDraft,
  YesNo,
} from "./types";
import { EMAIL_INVALID_MESSAGE, EMAIL_PATTERN } from "./validation";

const PHONE_PATTERN = /^[0-9]{3}-[0-9]{3}-[0-9]{4}$/;

export type DraftUpdater = (current: ApplicantDraft) => ApplicantDraft;

export function FormSection(props: { number: string; title: string; description: string; children: ReactNode }) {
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

export function Subheading(props: { title: string; required?: boolean }) {
  return <h3 className="form-subheading">{props.title}{props.required ? <Required /> : null}</h3>;
}

export function Required() { return <span className="required-mark" aria-label="required">*</span>; }

export function TextField(props: { label: string; value: string; onChange: (value: string) => void; type?: string; email?: boolean; phone?: boolean; url?: boolean; required?: boolean; wide?: boolean; help?: string; inputMode?: "numeric"; maxLength?: number; placeholder?: string }) {
  return (
    <label className={`applicant-field${props.wide ? " wide" : ""}`}>
      <span>{props.label}{props.required ? <Required /> : null}</span>
      {props.help ? <small>{props.help}</small> : null}
      <input
        type={props.email || props.phone ? "text" : props.type ?? "text"}
        value={props.value}
        required={props.required}
        inputMode={props.email ? "email" : props.phone ? "tel" : props.url ? "url" : props.inputMode}
        data-email={props.email ? "true" : undefined}
        data-phone={props.phone ? "true" : undefined}
        data-url={props.url ? "true" : undefined}
        maxLength={props.maxLength}
        placeholder={props.placeholder}
        onInput={(event) => event.currentTarget.setCustomValidity("")}
        onChange={(event) => {
          event.currentTarget.setCustomValidity("");
          props.onChange(event.target.value);
        }}
      />
    </label>
  );
}

export function DateField(props: {
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

export function TextArea(props: { label: string; help?: string; value: string; required?: boolean; compact?: boolean; onChange: (value: string) => void }) {
  return (
    <label className={`applicant-field wide${props.compact ? " compact" : ""}`}>
      <span>{props.label}{props.required ? <Required /> : null}</span>
      {props.help ? <small>{props.help}</small> : null}
      <textarea rows={props.compact ? 3 : 6} value={props.value} required={props.required} onChange={(event) => props.onChange(event.target.value)} />
    </label>
  );
}

export function PersonFields(props: {
  value: PersonDraft;
  required: boolean;
  leadingFields: ReactNode;
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


export function ReferenceFields(props: { value: ReferenceDraft; required: boolean; onChange: (value: ReferenceDraft) => void }) {
  const set = (patch: Partial<ReferenceDraft>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="field-grid three-column">
      <TextField label="Name" value={props.value.name} required={props.required} onChange={(name) => set({ name })} />
      <TextField label="Email" email value={props.value.email} required={props.required} onChange={(email) => set({ email })} />
      <TextField label="Phone" phone maxLength={12} placeholder="XXX-XXX-XXXX" value={props.value.phone} required={props.required} onChange={(phone) => set({ phone: formatPhone(phone) })} />
    </div>
  );
}

export function EmploymentFields(props: { value: EmploymentDraft; required: boolean; onChange: (value: EmploymentDraft) => void }) {
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

export function MoneyField(props: { label: string; value: string; required?: boolean; onChange: (value: string) => void }) {
  return (
    <label className="applicant-field money-field">
      <span>{props.label}{props.required ? <Required /> : null}</span>
      <div><span>$</span><input type="number" step="any" inputMode="numeric" data-money="true" value={props.value} required={props.required} onInput={(event) => event.currentTarget.setCustomValidity("")} onChange={(event) => props.onChange(event.target.value)} /></div>
    </label>
  );
}

export function YesNoField(props: { label: string; value: YesNo; onChange: (value: YesNo) => void }) {
  const name = props.label.replaceAll(" ", "-");
  return (
    <fieldset className="yes-no-field">
      <legend>{props.label}<Required /></legend>
      <label><input type="radio" name={name} value="yes" checked={props.value === "yes"} required onChange={() => props.onChange("yes")} /> Yes</label>
      <label><input type="radio" name={name} value="no" checked={props.value === "no"} required onChange={() => props.onChange("no")} /> No</label>
    </fieldset>
  );
}

export function ToggleCard(props: { checked: boolean; onChange: (checked: boolean) => void; title: string; description: string }) {
  return (
    <label className="toggle-card">
      <input type="checkbox" checked={props.checked} onChange={(event) => props.onChange(event.target.checked)} />
      <span><strong>{props.title}</strong><small>{props.description}</small></span>
    </label>
  );
}


export function updateChild(update: (fn: DraftUpdater) => void, id: string, patch: Partial<ApplicantDraft["children"][number]>): void {
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

export function validateFormFields(form: HTMLFormElement | null): void {
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
  form?.querySelectorAll<HTMLInputElement>("input[data-url]").forEach((input) => {
    const value = input.value.trim();
    input.setCustomValidity(
      value && !isValidWebUrl(value) ? "Enter a valid link beginning with http:// or https://." : "",
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

function isValidWebUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname);
  } catch {
    return false;
  }
}

export function validateEmailField(input: HTMLInputElement | null): void {
  if (!input) return;
  const email = input.value.trim();
  input.setCustomValidity(email && !EMAIL_PATTERN.test(email) ? EMAIL_INVALID_MESSAGE : "");
}
