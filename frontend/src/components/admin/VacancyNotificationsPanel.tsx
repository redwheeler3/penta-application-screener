import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";

import * as api from "../../api/vacancySubscriptions";
import { readProblem } from "../../api/problems";
import { formatPacificDateTime } from "../../format";
import type { VacancySubscription, VacancySubscriptionReport } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

export function VacancyNotificationsPanel(props: {
  onError: (message: string) => void;
}): ReactNode {
  const [report, setReport] = useState<VacancySubscriptionReport | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const [loadError, setLoadError] = useState(false);
  const [email, setEmail] = useState("");
  const [unitSizes, setUnitSizes] = useState<number[]>([]);
  const [source, setSource] = useState("Tech support request");
  const [subscription, setSubscription] = useState<VacancySubscription | null>(null);
  const [lookedUp, setLookedUp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let live = true;
    setLoadError(false);
    api.fetchVacancySubscriptionReport().then((next) => {
      if (live) setReport(next);
    }).catch(() => {
      if (!live) return;
      setLoadError(true);
      props.onError("Could not load the vacancy notification report.");
    });
    return () => { live = false; };
  }, [loadVersion, props.onError]);

  async function lookup(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await api.lookupVacancySubscription(email);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not look up that address.");
        return;
      }
      const result = (await response.json()) as api.VacancySubscriptionLookup;
      setSubscription(result.subscription);
      setUnitSizes(result.subscription?.unitSizes ?? []);
      setLookedUp(true);
      setMessage(result.subscription ? "Active subscription found." : "No active subscription found.");
    } catch {
      props.onError("Could not look up that address.");
    } finally {
      setBusy(false);
    }
  }

  async function save(): Promise<void> {
    if (!email.trim() || unitSizes.length === 0 || !source.trim() || busy) return;
    setBusy(true);
    try {
      const response = await api.saveVacancySubscription(email, unitSizes, source.trim());
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not save that subscription.");
        return;
      }
      const result = (await response.json()) as api.VacancySubscriptionLookup;
      setSubscription(result.subscription);
      setMessage("Subscription saved.");
      setLoadVersion((version) => version + 1);
    } catch {
      props.onError("Could not save that subscription.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(): Promise<void> {
    if (!subscription || !source.trim() || busy) return;
    setBusy(true);
    try {
      const response = await api.deleteVacancySubscription(email, source.trim());
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not delete that subscription.");
        return;
      }
      setSubscription(null);
      setUnitSizes([]);
      setMessage("Subscription deleted.");
      setLoadVersion((version) => version + 1);
    } catch {
      props.onError("Could not delete that subscription.");
    } finally {
      setBusy(false);
    }
  }

  function toggleSize(size: number): void {
    setUnitSizes((current) => current.includes(size)
      ? current.filter((value) => value !== size)
      : [...current, size].sort());
  }

  return (
    <div className="settings-panel-body vacancy-notifications-panel">
      <div className="settings-subtab-head">
        <h3>Vacancy notifications</h3>
        <p className="panel-hint">
          Active one-time requests. Bedroom counts overlap when someone chose more than one size.
        </p>
      </div>
      {loadError ? (
        <RetryLoadError
          message="Couldn't load vacancy notifications."
          onRetry={() => setLoadVersion((version) => version + 1)}
        />
      ) : report === null ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <>
          <VacancySummary report={report} />
          <VacancyMonthlyChart report={report} />
        </>
      )}
      <section className="vacancy-support-panel">
        <div>
          <h4>Exact-email support</h4>
          <p className="panel-hint">
            Look up one address to add or replace preferences after a support request, or delete
            it after a privacy request.
          </p>
        </div>
        <form className="vacancy-lookup" onSubmit={lookup}>
          <input
            type="email"
            required
            value={email}
            placeholder="person@example.com"
            onChange={(event) => {
              setEmail(event.target.value);
              setLookedUp(false);
              setSubscription(null);
              setUnitSizes([]);
              setMessage("");
            }}
          />
          <button className="secondary-button" type="submit" disabled={busy}>Look up</button>
        </form>
        {message ? <p className="opening-message vacancy-lookup-message" role="status">{message}</p> : null}
        {subscription ? (
          <dl className="vacancy-subscription-facts">
            <div>
              <dt>First subscribed</dt>
              <dd>{formatPacificDateTime(subscription.firstConsentedAt)}</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>{formatPacificDateTime(subscription.consentedAt)}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{subscription.source}</dd>
            </div>
          </dl>
        ) : null}
        {lookedUp ? (
          <div className="vacancy-support-editor">
            <fieldset>
              <legend>Notify for</legend>
              {[1, 2, 3].map((size) => (
                <label key={size}>
                  <input
                    type="checkbox"
                    checked={unitSizes.includes(size)}
                    onChange={() => toggleSize(size)}
                  />
                  {size} bedroom{size === 1 ? "" : "s"}
                </label>
              ))}
            </fieldset>
            <label>
              <span>Request source</span>
              <input value={source} maxLength={120} onChange={(event) => setSource(event.target.value)} />
            </label>
            <div className="opening-form-actions">
              {subscription ? (
                <button className="danger-button" type="button" onClick={() => void remove()} disabled={busy || !source.trim()}>
                  Delete subscription
                </button>
              ) : null}
              <button className="primary-button" type="button" onClick={() => void save()} disabled={busy || unitSizes.length === 0 || !source.trim()}>
                {subscription ? "Replace preferences" : "Add subscription"}
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function VacancySummary({ report }: { report: VacancySubscriptionReport }): ReactNode {
  return (
    <>
      <div className="vacancy-summary-grid">
        <SummaryCard label="Active total" value={report.total} />
        <SummaryCard label="1 bedroom" value={report.oneBedroom} />
        <SummaryCard label="2 bedrooms" value={report.twoBedroom} />
        <SummaryCard label="3 bedrooms" value={report.threeBedroom} />
      </div>
      <p className="panel-hint">
        Latest website sign-up: {report.latestSignupAt
          ? formatPacificDateTime(report.latestSignupAt)
          : "No website sign-ups yet"}
      </p>
    </>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }): ReactNode {
  return (
    <div className="vacancy-summary-card">
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}

function VacancyMonthlyChart({ report }: { report: VacancySubscriptionReport }): ReactNode {
  const maximum = useMemo(
    () => Math.max(1, ...report.months.map((month) => month.count)),
    [report.months],
  );
  return (
    <section className="vacancy-chart-panel">
      <h4>Active subscriptions by consent month</h4>
      {report.months.length === 0 ? <p className="panel-hint">No active subscriptions yet.</p> : (
        <div className="vacancy-chart-scroll">
          <div className="vacancy-chart" role="img" aria-label="Active subscriptions by consent month">
            {report.months.map((month) => (
              <div className="vacancy-chart-column" key={month.month}>
                <span className="vacancy-chart-value">{month.count}</span>
                <div className="vacancy-chart-bar" style={{ height: `${Math.max(4, month.count / maximum * 100)}%` }} />
                <span className="vacancy-chart-label">{formatMonth(month.month)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function formatMonth(value: string): string {
  const [year, month] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-CA", { month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, 1)));
}
