import { type ReactNode, useRef } from "react";
import * as openingsApi from "../../api/openings";
import { useCommitteeApi } from "../../api/identity";
import { formatDateOnly, formatHousingCharge } from "../../format";
import { readProblem } from "../../api/problems";
import { useFetchResource } from "../../hooks/useFetchResource";
import { useRequestScope } from "../../hooks/useRequestScope";
import type { Opening, OpeningCommit, OpeningWrite, OpeningPreview } from "../../types";

export function OpeningLaunchPanel(props: {
  opening: Opening;
  onSaved: (openings: Opening[], message: string) => void;
  onCancel: () => void;
  onError: (message: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
}) {
  const api = useCommitteeApi(openingsApi);
  const facts: OpeningWrite = {
    minChildren: props.opening.minChildren, maxChildren: props.opening.maxChildren,
    unitSizeBedrooms: props.opening.unitSizeBedrooms, housingChargeCents: props.opening.housingChargeCents,
    applicationOpenDate: props.opening.applicationOpenDate,
    applicationCloseDate: props.opening.applicationCloseDate!, moveInDate: props.opening.moveInDate,
  };
  const preview = useFetchResource(() => api.previewOpening(facts));
  const { busy, setBusy } = props;
  const pending = useRef(false);
  const requests = useRequestScope();
  async function launch() {
    if (!preview.data || pending.current) return;
    pending.current = true;
    setBusy(true);
    const isCurrent = requests.capture();
    try {
      const response = await api.openApplications(props.opening.id, facts, preview.data.variants);
      if (!isCurrent()) return;
      if (!response.ok) {
        const problem = await readProblem(response);
        if (!isCurrent()) return;
        props.onError(problem ?? "Could not open applications.");
        await preview.reload();
        return;
      }
      const result = await response.json() as OpeningCommit;
      if (isCurrent()) props.onSaved(result.openings, "Applications are open. Opening announcements are queued.");
    } catch {
      if (isCurrent()) props.onError("Could not confirm whether applications opened. Retry safely or review the opening list.");
    } finally {
      pending.current = false;
      if (isCurrent()) setBusy(false);
    }
  }
  return <section className="opening-form opening-launch-panel">
    <h4>{props.opening.unitSizeBedrooms}-bedroom home</h4>
    <dl className="opening-preview-variants">
      <div><dt>Monthly housing charge</dt><dd>{formatHousingCharge(props.opening.housingChargeCents)}</dd></div>
      <div><dt>Household</dt><dd>{props.opening.householdSummary}</dd></div>
      <div><dt>Applications close</dt><dd>{formatDateOnly(facts.applicationCloseDate)}</dd></div>
      <div><dt>Move-in date</dt><dd>{formatDateOnly(facts.moveInDate)}</dd></div>
    </dl>
    {preview.data ? <OpeningLaunchPreview preview={preview.data} /> : <p>Loading the notification audience…</p>}
    {preview.state === "error" ? <button type="button" onClick={() => void preview.reload()}>Retry preview</button> : null}
    <p>Applicants must review and submit their application for this opening before its deadline.</p>
    <div className="opening-form-actions">
      <button className="secondary-button" disabled={busy} onClick={props.onCancel}>Back</button>
      <button className="primary-button" disabled={busy || !preview.data} onClick={() => void launch()}>
        {busy ? "Opening…" : "Open applications and notify applicants"}
      </button>
    </div>
  </section>;
}

export function OpeningLaunchPreview({ preview }: { preview: OpeningPreview }): ReactNode {
  const api = useCommitteeApi(openingsApi);

  const usageResource = useFetchResource(() => api.fetchOpeningEmailUsage(preview.audienceCount), {
    reloadKey: preview.audienceCount,
  });
  const usage = usageResource.data;
  const variantLabels: Record<string, string> = {
    notification_list: "Notification list email",
    current_application: "Current application email",
    application_and_notification_list: "Combined application and notification-list email",
  };
  return (
    <section className="opening-launch-preview" aria-label="Opening and email confirmation">
      <h5>Ready to open applications</h5>
      <p>
        <strong>{preview.audienceCount}</strong> {preview.audienceCount === 1 ? "person" : "people"}
        {" "}will receive an email.
      </p>
      <dl className="opening-preview-variants">
        {preview.variants.map((variant) => (
          <div key={variant.kind}>
            <dt>{variantLabels[variant.kind] ?? variant.kind}</dt>
            <dd>{variant.recipientCount}</dd>
          </div>
        ))}
      </dl>
      {usageResource.state === "loading" ? (
        <p className="opening-quota-summary">Checking current email usage… You can confirm the opening while this loads.</p>
      ) : usage?.available ? (
        <p className="opening-quota-summary">
          SocketLabs usage will move from <strong>{usage.messagesUsed?.toLocaleString()}</strong> to{" "}
          <strong>{usage.projectedMessagesUsed?.toLocaleString()}</strong> of{" "}
          <strong>{usage.messageAllowance?.toLocaleString()}</strong> messages this billing period.
          {usage.allowOverages === false && usage.projectedMessagesUsed !== null && usage.messageAllowance !== null
            && usage.projectedMessagesUsed > usage.messageAllowance
            ? " Messages beyond the allowance will remain queued until SocketLabs accepts them."
            : ""}
        </p>
      ) : (
        <p className="opening-quota-summary">
          Current SocketLabs usage is unavailable. Emails will be queued and retried automatically
          if needed.
        </p>
      )}
    </section>
  );
}
