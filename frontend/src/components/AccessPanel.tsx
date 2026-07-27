import { Trash2, UserPlus } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import * as api from "../api";
import { readProblem } from "../format";
import type { AllowlistEntry, DeniedSignInAttempt } from "../types";

// Admin-only management of the access allowlist: who may sign in, and with what role.
// The mutation endpoints return the full updated list, so this holds the list in local
// state and replaces it from each response (no separate refetch).
export function AccessPanel(props: { onError: (message: string) => void }): ReactNode {
  const [entries, setEntries] = useState<AllowlistEntry[] | null>(null);
  const [deniedAttempts, setDeniedAttempts] = useState<DeniedSignInAttempt[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [deniedLoadError, setDeniedLoadError] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .fetchAllowlist()
      .then((list) => live && setEntries(list))
      .catch(() => {
        if (!live) return;
        // Record the failure so the panel shows an inline error instead of sitting on
        // "Loading…" forever (the toast is ephemeral; the panel would otherwise mislead).
        setLoadError(true);
        props.onError("Could not load the access allowlist.");
      });
    api
      .fetchDeniedSignInAttempts()
      .then((attempts) => live && setDeniedAttempts(attempts))
      .catch(() => {
        if (!live) return;
        setDeniedLoadError(true);
        props.onError("Could not load denied sign-in attempts.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function addEntry(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    const response = await api.upsertAllowlistEntry(trimmed, role);
    setBusy(false);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "Could not add that email.");
      return;
    }
    const body: { entries: AllowlistEntry[] } = await response.json();
    setEntries(body.entries);
    setEmail("");
    setRole("member");
  }

  async function removeEntry(target: string) {
    if (busy) return;
    setBusy(true);
    const response = await api.removeAllowlistEntry(target);
    setBusy(false);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "Could not remove that email.");
      return;
    }
    const body: { entries: AllowlistEntry[] } = await response.json();
    setEntries(body.entries);
  }

  return (
    <section className="access-panel no-print" aria-label="Access allowlist">
      <div className="access-panel-head">
        <h3>Access allowlist</h3>
        <p className="panel-hint">
          Only these Google accounts can sign in. An <strong>admin</strong> entry can manage this
          list; a <strong>member</strong> screens applicants. Editing takes effect at their next
          sign-in. The last admin can't be removed or demoted.
        </p>
      </div>

      <form className="access-add" onSubmit={addEntry}>
        <input
          type="email"
          required
          placeholder="name@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <select value={role} onChange={(e) => setRole(e.target.value as "admin" | "member")}>
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
        <button type="submit" className="primary-button" disabled={busy || !email.trim()}>
          <UserPlus size={16} />
          <span>Add</span>
        </button>
      </form>

      {loadError ? (
        <p className="panel-hint">Couldn't load the access allowlist.</p>
      ) : entries === null ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <div className="access-table-scroll" role="region" aria-label="Access allowlist">
          <table className="access-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>First signed in</th>
              <th>Last signed in</th>
              <th>Sign-ins</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              // The last admin can't be removed (the backend enforces this too); don't
              // offer a button that's guaranteed to fail — disable it and say why.
              const isLastAdmin =
                entry.role === "admin" &&
                entries.filter((e) => e.role === "admin").length === 1;
              return (
                <tr key={entry.email}>
                  <td>{entry.displayName ?? "—"}</td>
                  <td>{entry.email}</td>
                  <td>
                    <span className={`role-badge role-${entry.role}`}>{entry.role}</span>
                  </td>
                  <td>{formatSignInTime(entry.firstSignedInAt)}</td>
                  <td>{formatSignInTime(entry.lastSignedInAt)}</td>
                  <td>{entry.signInCount}</td>
                  <td className="access-remove-cell">
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Remove ${entry.email}`}
                      title={isLastAdmin ? "The last admin can't be removed" : "Remove"}
                      disabled={busy || isLastAdmin}
                      onClick={() => removeEntry(entry.email)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          </table>
        </div>
      )}
      <p className="panel-hint">Sign-in counts begin when this feature is deployed.</p>
      <section className="denied-sign-ins" aria-label="Denied sign-in attempts">
        <div className="access-panel-head">
          <h3>Denied sign-in attempts</h3>
          <p className="panel-hint">Accounts rejected by the allowlist in the last year.</p>
        </div>
        {deniedLoadError ? (
          <p className="panel-hint">Couldn&apos;t load denied sign-in attempts.</p>
        ) : deniedAttempts === null ? (
          <p className="panel-hint">Loading…</p>
        ) : deniedAttempts.length === 0 ? (
          <p className="panel-hint">No denied sign-in attempts in the last year.</p>
        ) : (
          <div className="access-table-scroll" role="region" aria-label="Denied sign-in attempts">
            <table className="access-table denied-sign-ins-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>First denied</th>
                  <th>Last denied</th>
                  <th>Attempts</th>
                </tr>
              </thead>
              <tbody>
                {deniedAttempts.map((attempt) => (
                  <tr key={attempt.email}>
                    <td>{attempt.displayName}</td>
                    <td>{attempt.email}</td>
                    <td>{formatSignInTime(attempt.firstDeniedAt)}</td>
                    <td>{formatSignInTime(attempt.lastDeniedAt)}</td>
                    <td>{attempt.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function formatSignInTime(value: string | null): string {
  if (!value) return "Not yet signed in";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Vancouver",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
