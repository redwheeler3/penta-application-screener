import { Trash2, UserPlus } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import * as api from "../api";
import { readProblem } from "../format";
import type { AllowlistEntry } from "../types";

// Admin-only management of the access allowlist: who may sign in, and with what role.
// The mutation endpoints return the full updated list, so this holds the list in local
// state and replaces it from each response (no separate refetch).
export function AccessPanel(props: { onError: (message: string) => void }): ReactNode {
  const [entries, setEntries] = useState<AllowlistEntry[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .fetchAllowlist()
      .then((list) => live && setEntries(list))
      .catch(() => live && props.onError("Could not load the access allowlist."));
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

      {entries === null ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <table className="access-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
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
                  <td>{entry.email}</td>
                  <td>
                    <span className={`role-badge role-${entry.role}`}>{entry.role}</span>
                  </td>
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
      )}
    </section>
  );
}
