import {
  CheckCircle2,
  ChevronLeft,
  FileCheck2,
  Mail,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { ApplicantErrorMessage, openingLabel } from "./ApplicantAccessScreens";
import {
  type ApplicantDraft,
  type ApplicantOpening,
  householdIncome,
} from "./types";

export type DraftConfirmation = "clear" | "revert";

export function ReviewSection(props: { title: string; children: ReactNode }) {
  return <section className="review-section"><h2>{props.title}</h2><dl>{props.children}</dl></section>;
}

export function ReviewRow(props: { label: string; value: string; link?: boolean }) {
  return (
    <div>
      <dt>{props.label}</dt>
      <dd>
        {props.link && props.value ? (
          <a href={props.value} target="_blank" rel="noopener noreferrer">{props.value}</a>
        ) : props.value || "—"}
      </dd>
    </div>
  );
}

export function ApplicationReview(props: {
  draft: ApplicantDraft;
  openings: ApplicantOpening[];
  selectedOpeningIds: number[];
  declarationAccepted: boolean;
  persistencePhase: string;
  persistenceMessage: string;
  authenticated: boolean;
  onRetry: () => void;
  onReload: () => void;
  onDeclarationChange: (accepted: boolean) => void;
  onSubmit: () => void;
  onEdit: () => void;
}) {
  const d = props.draft;
  const selectedOpenings = props.openings.filter((opening) => (
    opening.phase !== "archived" && props.selectedOpeningIds.includes(opening.id)
  ));
  const withdrawnOpenings = props.openings.filter((opening) => (
    opening.phase !== "archived" &&
    opening.participating &&
    !props.selectedOpeningIds.includes(opening.id)
  ));
  return (
    <div className="application-review">
      <div className="review-notice">
        <FileCheck2 size={22} />
        <div>
          <strong>{props.authenticated ? "Your application is ready to submit." : "This is still a private draft."}</strong>
          <span>Nothing has been sent to the membership committee.</span>
          <span>Review your answers before submitting.</span>
        </div>
      </div>
      <ReviewSection title="Openings">
        <ReviewRow
          label="Applying for"
          value={selectedOpenings.length > 0
            ? selectedOpenings.map(openingLabel).join(", ")
            : "None"}
        />
        {withdrawnOpenings.length > 0 ? (
          <ReviewRow
            label="Withdrawing from"
            value={withdrawnOpenings.map(openingLabel).join(", ")}
          />
        ) : null}
      </ReviewSection>
      <ReviewSection title="Household">
        <ReviewRow label="Primary applicant" value={`${d.applicant.firstName} ${d.applicant.lastName}`} />
        <ReviewRow label="Email" value={d.applicant.email} />
        <ReviewRow label="Co-applicant" value={d.hasCoApplicant ? `${d.coApplicant.firstName} ${d.coApplicant.lastName}` : "None"} />
        <ReviewRow label="Children" value={String(d.children.length)} />
        {d.householdPhotoLink ? (
          <ReviewRow label="Household photo" value={d.householdPhotoLink} link />
        ) : null}
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
            <a
              href="https://www.pentacoop.com/privacy.html"
              target="_blank"
              rel="noopener noreferrer"
            >
              Privacy Policy
            </a>.
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
          message={props.persistenceMessage}
          onRetry={props.onRetry}
          onReload={props.onReload}
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
            Submit application
            <FileCheck2 size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}

export function PersistenceActionStatus(props: {
  phase: string;
  message: string;
  onRetry: () => void;
  onReload: () => void;
}) {
  if (props.phase === "authentication_required") {
    return (
      <div className="persistence-action-status" role="status">
        <span>{props.message}</span>
      </div>
    );
  }
  if (props.phase === "error") {
    return (
      <div className="persistence-action-status error" role="alert">
        <strong>We couldn't continue</strong>
        <ApplicantErrorMessage message={props.message} />
      </div>
    );
  }
  if (props.phase === "stale_copy") {
    return (
      <div className="persistence-action-status error" role="alert">
        <strong>This application changed in another tab</strong>
        <span>Your answers here have not been overwritten.</span>
        <button type="button" onClick={props.onReload}>Reload the latest saved copy</button>
      </div>
    );
  }
  if (props.phase === "working") {
    return <p className="persistence-action-status" role="status">Saving…</p>;
  }
  if (props.phase === "saved") {
    return (
      <p className="persistence-action-status success" role="status">
        <span className="persistence-action-confirmation">
          <CheckCircle2 size={16} /> Application saved
        </span>
      </p>
    );
  }
  if (props.phase === "email_sent") {
    return (
      <div className="persistence-action-status" role="status">
        <span className="persistence-action-confirmation">
          <Mail size={16} /> Application saved
        </span>
        <span>Check your email for a link to open your application.</span>
        <span>
          Didn’t receive it? Double-check the email address above, then{" "}
          <button type="button" onClick={props.onRetry}>try again</button>.
        </span>
      </div>
    );
  }
  if (props.phase === "email_failed") {
    return (
      <div className="persistence-action-status error" role="alert">
        <strong>Application saved</strong>
        <span>We couldn’t email a link to open your application.</span>
        <ApplicantErrorMessage message={TECH_SUPPORT_ERROR_MESSAGE} />
      </div>
    );
  }
  return null;
}

export function PrivateChangesNotice() {
  return (
    <div className="private-changes-notice" role="status">
      <strong>Your changes are private</strong>
      <span>Submit the application when you are ready for the membership committee to see them.</span>
    </div>
  );
}

export function ApplicationComplete(props: { submitted: boolean; emailSent: boolean }) {
  return (
    <section className="application-complete">
      <CheckCircle2 size={34} />
      <h2>{props.submitted ? "Application submitted" : "Application saved"}</h2>
      <p>
        {props.submitted && props.emailSent
          ? "Check your email for confirmation and a link to edit your application later."
          : props.submitted
            ? <>Your application was submitted, but we couldn’t email a link to edit it later. <ApplicantErrorMessage message={TECH_SUPPORT_ERROR_MESSAGE} /></>
            : "Your private application draft is saved. Check your email for a link to continue editing."}
      </p>
    </section>
  );
}

export function ApplicationDeleted(props: { emailSent: boolean }) {
  return (
    <section className="application-complete">
      <CheckCircle2 size={34} />
      <h2>Application deleted</h2>
      <p>Your application has been deleted.</p>
      {!props.emailSent ? (
        <p>We couldn’t email a confirmation, but the deletion is complete.</p>
      ) : null}
    </section>
  );
}

export function ApplicationDeletion(props: {
  open: boolean;
  status: "idle" | "working" | "error";
  message: string;
  onOpen: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  if (!props.open) {
    return (
      <div className="application-delete-entry">
        <button className="applicant-danger-link" type="button" onClick={props.onOpen}>
          <Trash2 size={16} /> Delete application
        </button>
      </div>
    );
  }
  return (
    <section className="application-action-confirm application-delete-confirm" aria-labelledby="delete-application-title">
      <h2 id="delete-application-title">Delete your application?</h2>
      <p>
        Your application will be deleted, and you will be signed out. This cannot be undone.
      </p>
      {props.message ? (
        <p className={props.status === "error" ? "field-error" : undefined} role="status">
          <ApplicantErrorMessage message={props.message} />
        </p>
      ) : null}
      <div className="applicant-action-group">
        <button className="applicant-secondary-button" type="button" onClick={props.onCancel}>
          Keep application
        </button>
        <button
          className="applicant-danger-button"
          type="button"
          disabled={props.status === "working"}
          onClick={props.onDelete}
        >
          {props.status === "working" ? "Deleting…" : "Delete application"}
        </button>
      </div>
    </section>
  );
}

export function DraftActionConfirmation(props: {
  action: DraftConfirmation;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const reverting = props.action === "revert";
  const titleId = `${props.action}-draft-title`;
  return (
    <section className="application-action-confirm application-draft-confirm" aria-labelledby={titleId}>
      <h2 id={titleId}>{reverting ? "Revert your changes?" : "Clear this draft?"}</h2>
      <p>
        {reverting
          ? "Your private changes will be replaced by your last submitted application. This cannot be undone."
          : "The answers in this draft will be removed. This cannot be undone."}
      </p>
      <div className="applicant-action-group">
        <button className="applicant-secondary-button compact" type="button" autoFocus onClick={props.onCancel}>
          Keep editing
        </button>
        <button className="applicant-danger-button compact" type="button" onClick={props.onConfirm}>
          {reverting ? "Revert changes" : "Clear draft"}
        </button>
      </div>
    </section>
  );
}
