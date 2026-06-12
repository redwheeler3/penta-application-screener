import { ChevronLeft, Home, LogIn, LogOut, RefreshCw, Settings } from "lucide-react";
import { type SyntheticEvent, useEffect, useState } from "react";

type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

type AppSettings = {
  google_sheet_id: string;
  unit_size: "1br" | "2br" | "3br";
  move_in_date: string;
  income_min: number;
  income_max: number;
  max_adults: number;
  min_adult_age: number;
  income_mismatch_tolerance: number;
  max_dogs: number;
  max_cats: number;
  allow_other_pets: boolean;
  disabled_rules: string[];
};

type SettingsResponse = {
  settings: AppSettings;
  google_sheet_url: string;
  google_sheet_title: string | null;
};

type DashboardCounts = {
  submitted: number;
  eligible: number;
  filteredOut: number;
};

type ApplicationSummary = {
  id: number;
  primaryEmail: string;
  applicantName: string | null;
  coApplicantName: string | null;
  hardFilterStatus: "eligible" | "filtered_out";
  hardFilterReasons: Array<{ code: string; message: string; details: Record<string, unknown> }>;
  childCount: number | null;
  householdIncome: number | null;
  createdAt: string | null;
};

type ApplicationDetail = ApplicationSummary & {
  normalized: Record<string, unknown>;
  rawRow?: Record<string, unknown>;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const defaultSettings: AppSettings = {
  google_sheet_id: "",
  unit_size: "2br",
  move_in_date: "2026-09-01",
  income_min: 70000,
  income_max: 150000,
  max_adults: 2,
  min_adult_age: 19,
  income_mismatch_tolerance: 1000,
  max_dogs: 1,
  max_cats: 1,
  allow_other_pets: false,
  disabled_rules: [],
};

const ALL_RULES = [
  { id: "applicant_under_19", label: "Applicant under 19", outcome: "filtered_out" },
  { id: "child_age_over_18", label: "Child age 18+", outcome: "filtered_out" },
  { id: "child_count_mismatch", label: "Child count mismatch", outcome: "filtered_out" },
  { id: "co_applicant_incomplete", label: "Co-applicant incomplete", outcome: "filtered_out" },
  { id: "co_applicant_under_19", label: "Co-applicant under 19", outcome: "filtered_out" },
  { id: "future_employment_start", label: "Future employment start", outcome: "filtered_out" },
  { id: "income_above_range", label: "Income above range", outcome: "filtered_out" },
  { id: "income_arithmetic_mismatch", label: "Income arithmetic mismatch", outcome: "filtered_out" },
  { id: "income_below_range", label: "Income below range", outcome: "filtered_out" },
  { id: "negative_number", label: "Negative number", outcome: "filtered_out" },
  { id: "owns_real_estate", label: "Real estate ownership", outcome: "filtered_out" },
  { id: "child_age_exceeds_parent", label: "Child age exceeds parent", outcome: "filtered_out" },
] as const;

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [googleSheetUrl, setGoogleSheetUrl] = useState("");
  const [googleSheetTitle, setGoogleSheetTitle] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>({
    submitted: 0,
    eligible: 0,
    filteredOut: 0,
  });
  const [syncMessage, setSyncMessage] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    if (syncMessage && syncMessage.startsWith("Synced")) {
      const timer = setTimeout(() => setSyncMessage(""), 4000);
      return () => clearTimeout(timer);
    }
  }, [syncMessage]);
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [appTotal, setAppTotal] = useState(0);
  const [appPage, setAppPage] = useState(1);
  const [appPageSize, setAppPageSize] = useState(25);
  const [appFilter, setAppFilter] = useState<string | null>(null);
  const [appSearch, setAppSearch] = useState("");
  const [selectedApp, setSelectedApp] = useState<ApplicationDetail | null>(null);


  useEffect(() => {
    fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { user: CurrentUser | null }) => setUser(payload.user))
      .finally(() => setIsLoadingUser(false));
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    fetch(`${apiBaseUrl}/settings`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: SettingsResponse) => applySettingsResponse(payload));
    refreshDashboard();
    fetchApplications(null, 1, "");
  }, [user]);

  function applySettingsResponse(payload: SettingsResponse) {
    setSettings({
      ...payload.settings,
      google_sheet_id: payload.google_sheet_url || payload.settings.google_sheet_id,
    });
    setGoogleSheetUrl(payload.google_sheet_url);
    setGoogleSheetTitle(payload.google_sheet_title);
  }

  function refreshDashboard() {
    fetch(`${apiBaseUrl}/dashboard`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { counts: DashboardCounts }) => setDashboardCounts(payload.counts));
  }

  function fetchApplications(
    filter: string | null = appFilter,
    page: number = 1,
    search: string = appSearch,
    pageSize: number = appPageSize,
  ) {
    const params = new URLSearchParams();
    if (filter) params.set("status", filter);
    if (search) params.set("search", search);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    fetch(`${apiBaseUrl}/applications?${params}`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { applications: ApplicationSummary[]; total: number; page: number; pageSize: number }) => {
        setApplications(payload.applications);
        setAppTotal(payload.total);
        setAppPage(payload.page);
        setAppPageSize(payload.pageSize);
      });
  }

  function viewApplication(id: number) {
    fetch(`${apiBaseUrl}/applications/${id}`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { application: ApplicationDetail }) => setSelectedApp(payload.application));
  }

  function formatFieldValue(value: unknown): React.ReactNode {
    if (value == null) return "—";
    if (Array.isArray(value)) {
      if (value.length === 0) return "—";
      return (
        <ul className="field-list">
          {value.map((item, i) => (
            <li key={i}>{formatArrayItem(item)}</li>
          ))}
        </ul>
      );
    }
    if (typeof value === "object") {
      return Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v != null && v !== "")
        .map(([, v]) => String(v))
        .join(", ");
    }
    return String(value);
  }

  function formatArrayItem(item: unknown): string {
    if (typeof item !== "object" || item === null) return String(item);
    const obj = item as Record<string, unknown>;
    if ("first_name" in obj || "last_name" in obj) {
      const name = [obj.first_name, obj.last_name].filter(Boolean).join(" ");
      return obj.age != null ? `${name} (${obj.age})` : name || "—";
    }
    return Object.values(obj).filter((v) => v != null && v !== "").join(", ");
  }

  function login() {
    window.location.href = `${apiBaseUrl}/auth/google/login`;
  }

  async function logout() {
    await fetch(`${apiBaseUrl}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    setUser(null);
  }

  async function saveSettings(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSavingSettings(true);
    setSettingsMessage("");

    const response = await fetch(`${apiBaseUrl}/settings`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });

    if (response.ok) {
      const payload: SettingsResponse = await response.json();
      applySettingsResponse(payload);
      setSettingsMessage("Settings saved.");
      refreshDashboard();
    } else {
      setSettingsMessage("Settings could not be saved.");
    }

    setIsSavingSettings(false);
  }

  async function syncApplications() {
    setIsSyncing(true);
    setSyncMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/sync/applications`, {
        method: "POST",
        credentials: "include",
      });

      if (response.ok) {
        const payload: { syncRun: { rowCount: number; importedCount: number; updatedCount: number } } =
          await response.json();
        setSyncMessage(
          `Synced ${payload.syncRun.rowCount} rows: ${payload.syncRun.importedCount} imported, ${payload.syncRun.updatedCount} updated.`,
        );
        refreshDashboard();
        fetchApplications(appFilter, 1, appSearch);
      } else {
        let detail = `Sync failed (HTTP ${response.status}).`;
        try {
          const payload = await response.json();
          if (payload.detail) detail = `Sync failed: ${payload.detail}`;
        } catch {
          // response body wasn't JSON
        }
        setSyncMessage(detail);
      }
    } catch (error) {
      setSyncMessage(`Sync error: ${error instanceof Error ? error.message : "Network request failed. Check that the backend is running."}`);
    }

    setIsSyncing(false);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <Home size={24} />
          </div>
          <div>
            <p className="eyebrow">Penta Housing Coop</p>
            <h1>Application Screener</h1>
          </div>
        </div>
        {user ? (
          <div className="toolbar">
            <div className="user-chip">
              <span>{user.displayName}</span>
              <strong>{user.role}</strong>
            </div>
            <button
              className="icon-button"
              aria-label="Sync applications"
              title="Sync applications"
              onClick={syncApplications}
              disabled={isSyncing || !settings.google_sheet_id}
            >
              <RefreshCw size={18} />
            </button>
            <button
              className="icon-button"
              aria-label="Settings"
              title="Settings"
              onClick={() => setIsSettingsOpen((isOpen) => !isOpen)}
            >
              <Settings size={18} />
            </button>
            <button className="icon-button" aria-label="Log out" title="Log out" onClick={logout}>
              <LogOut size={18} />
            </button>
          </div>
        ) : null}
      </header>

      {!user ? (
        <section className="login-panel">
          <span className="panel-kicker">Member access</span>
          <h2>{isLoadingUser ? "Checking session" : "Sign in to continue"}</h2>
          <p>Use your approved Google account.</p>
          <button className="primary-button" onClick={login} disabled={isLoadingUser}>
            <LogIn size={18} />
            <span>Sign in with Google</span>
          </button>
        </section>
      ) : (
        <>
          {isSettingsOpen ? (
            <section className="settings-panel" aria-label="Admin settings">
              <div>
                <span className="panel-kicker">Admin setup</span>
                <h2>Settings</h2>
              </div>
              <form className="settings-form" onSubmit={saveSettings}>
                <label>
                  <span>Google Sheet link</span>
                  <input
                    value={settings.google_sheet_id}
                    onChange={(event) => setSettings({ ...settings, google_sheet_id: event.target.value })}
                    placeholder="Paste the response spreadsheet link"
                  />
                  {googleSheetTitle && googleSheetUrl ? (
                    <a className="sheet-reference" href={googleSheetUrl} target="_blank" rel="noreferrer">
                      {googleSheetTitle}
                    </a>
                  ) : null}
                </label>
                <label>
                  <span>Unit size</span>
                  <select
                    value={settings.unit_size}
                    onChange={(event) =>
                      setSettings({ ...settings, unit_size: event.target.value as AppSettings["unit_size"] })
                    }
                  >
                    <option value="1br">1 bedroom</option>
                    <option value="2br">2 bedroom</option>
                    <option value="3br">3 bedroom</option>
                  </select>
                </label>
                <label>
                  <span>Move-in date</span>
                  <input
                    type="date"
                    value={settings.move_in_date}
                    onChange={(event) => setSettings({ ...settings, move_in_date: event.target.value })}
                  />
                </label>
                <label>
                  <span>Income minimum</span>
                  <input
                    type="number"
                    min="0"
                    value={settings.income_min}
                    onChange={(event) => setSettings({ ...settings, income_min: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Income maximum</span>
                  <input
                    type="number"
                    min="0"
                    value={settings.income_max}
                    onChange={(event) => setSettings({ ...settings, income_max: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Income mismatch tolerance</span>
                  <input
                    type="number"
                    min="0"
                    value={settings.income_mismatch_tolerance}
                    onChange={(event) =>
                      setSettings({ ...settings, income_mismatch_tolerance: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  <span>Max adults per unit</span>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={settings.max_adults}
                    onChange={(event) => setSettings({ ...settings, max_adults: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Min adult age</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={settings.min_adult_age}
                    onChange={(event) => setSettings({ ...settings, min_adult_age: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max dogs</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={settings.max_dogs}
                    onChange={(event) => setSettings({ ...settings, max_dogs: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max cats</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={settings.max_cats}
                    onChange={(event) => setSettings({ ...settings, max_cats: Number(event.target.value) })}
                  />
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={settings.allow_other_pets}
                    onChange={(event) => setSettings({ ...settings, allow_other_pets: event.target.checked })}
                  />
                  <span>Allow other pets</span>
                </label>
                <div className="rules-section">
                  <h3>Screening Rules</h3>
                  <p className="rules-hint">Uncheck a rule to disable it. Disabled rules will not run during screening.</p>
                  <div className="rules-grid">
                    {ALL_RULES.map((rule) => (
                      <label key={rule.id} className="checkbox-label rule-toggle">
                        <input
                          type="checkbox"
                          checked={!settings.disabled_rules.includes(rule.id)}
                          onChange={(event) => {
                            const disabled = event.target.checked
                              ? settings.disabled_rules.filter((r) => r !== rule.id)
                              : [...settings.disabled_rules, rule.id];
                            setSettings({ ...settings, disabled_rules: disabled });
                          }}
                        />
                        <span>{rule.label}</span>
                        <span className={`rule-outcome rule-outcome-${rule.outcome}`}>
                          {rule.outcome.replace("_", " ")}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="settings-actions">
                  <button className="primary-button" type="submit" disabled={isSavingSettings}>
                    {isSavingSettings ? "Saving" : "Save settings"}
                  </button>
                  {settingsMessage ? <span>{settingsMessage}</span> : null}
                </div>
              </form>
            </section>
          ) : null}

          {!settings.google_sheet_id ? (
            <section className="setup-callout">
              <strong>Setup needed</strong>
              <span>Add the Google Sheet link in settings before syncing applications.</span>
            </section>
          ) : null}


          <section className="panel">
            <div className="panel-header">
              <div>
                <span className="panel-kicker">Current opening</span>
                <h2>Applications</h2>
              </div>
            </div>

            {selectedApp ? (
              <div className="app-detail">
                <button className="back-button" onClick={() => setSelectedApp(null)}>
                  <ChevronLeft size={16} />
                  <span>Back to list</span>
                </button>
                <div className="app-detail-header">
                  <h3>{selectedApp.applicantName || selectedApp.primaryEmail}</h3>
                  <span className={`status-badge status-${selectedApp.hardFilterStatus}`}>
                    {selectedApp.hardFilterStatus.replace("_", " ")}
                  </span>
                </div>
                {selectedApp.coApplicantName ? (
                  <p className="co-applicant-line">Co-applicant: {selectedApp.coApplicantName}</p>
                ) : null}
                {selectedApp.hardFilterReasons.length > 0 ? (
                  <div className="filter-reasons">
                    <strong>Filter reasons:</strong>
                    <ul>
                      {selectedApp.hardFilterReasons.map((reason, i) => (
                        <li key={i}>{reason.message}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="app-detail-fields">
                  <h4>Normalized data</h4>
                  <dl>
                    {Object.entries(selectedApp.normalized).map(([key, value]) => (
                      <div key={key}>
                        <dt>{key}</dt>
                        <dd>{formatFieldValue(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
                {selectedApp.rawRow ? (
                  <details className="raw-row-section">
                    <summary>Raw source row (admin)</summary>
                    <pre>{JSON.stringify(selectedApp.rawRow, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
            ) : (
              <>
                <div className="app-controls">
                  <div className="app-tabs">
                    {[
                      { label: "All", value: null, count: dashboardCounts.submitted },
                      { label: "Eligible", value: "eligible", count: dashboardCounts.eligible },
                      { label: "Filtered Out", value: "filtered_out", count: dashboardCounts.filteredOut },
                    ].map((tab) => (
                      <button
                        key={tab.label}
                        className={`tab-button ${appFilter === tab.value ? "active" : ""}`}
                        onClick={() => {
                          setAppFilter(tab.value);
                          fetchApplications(tab.value, 1, appSearch);
                        }}
                      >
                        {tab.label} ({tab.count})
                      </button>
                    ))}
                  </div>
                  <input
                    className="app-search"
                    type="search"
                    placeholder="Search by name or email"
                    value={appSearch}
                    onChange={(event) => {
                      setAppSearch(event.target.value);
                      fetchApplications(appFilter, 1, event.target.value);
                    }}
                  />
                </div>

                {applications.length === 0 ? (
                  <div className="empty-state">
                    <p>No applications {appFilter ? `with status "${appFilter.replace("_", " ")}"` : "imported yet"}.</p>
                  </div>
                ) : (
                  <>
                    <table className="app-table">
                      <thead>
                        <tr>
                          <th>Applicant</th>
                          <th>Co-applicant</th>
                          <th>Children</th>
                          <th>Income</th>
                          <th>Status</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {applications.map((app) => (
                          <tr key={app.id} onClick={() => viewApplication(app.id)} className="clickable-row">
                            <td>{app.applicantName || app.primaryEmail}</td>
                            <td>{app.coApplicantName || "—"}</td>
                            <td>{app.childCount ?? "?"}</td>
                            <td>{app.householdIncome != null ? `$${app.householdIncome.toLocaleString()}` : "?"}</td>
                            <td>
                              <span className={`status-badge status-${app.hardFilterStatus}`}>
                                {app.hardFilterStatus.replace("_", " ")}
                              </span>
                            </td>
                            <td className="reason-cell">
                              {app.hardFilterReasons.length > 0
                                ? app.hardFilterReasons.map((r) => r.message).join("; ")
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="pagination">
                      <div className="pagination-size">
                        <span>Rows:</span>
                        <select
                          value={appPageSize}
                          onChange={(event) => {
                            const newSize = Number(event.target.value);
                            fetchApplications(appFilter, 1, appSearch, newSize);
                          }}
                        >
                          <option value="10">10</option>
                          <option value="25">25</option>
                          <option value="50">50</option>
                          <option value="100">100</option>
                        </select>
                      </div>
                      <div className="pagination-pages">
                        <button disabled={appPage <= 1} onClick={() => fetchApplications(appFilter, 1, appSearch)}>
                          «
                        </button>
                        <button disabled={appPage <= 1} onClick={() => fetchApplications(appFilter, appPage - 1, appSearch)}>
                          ‹
                        </button>
                        <span>
                          Page {appPage} of {Math.ceil(appTotal / appPageSize) || 1}
                        </span>
                        <button
                          disabled={appPage >= Math.ceil(appTotal / appPageSize)}
                          onClick={() => fetchApplications(appFilter, appPage + 1, appSearch)}
                        >
                          ›
                        </button>
                        <button
                          disabled={appPage >= Math.ceil(appTotal / appPageSize)}
                          onClick={() => fetchApplications(appFilter, Math.ceil(appTotal / appPageSize), appSearch)}
                        >
                          »
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </section>
        </>
      )}
      {syncMessage ? (
        <div
          className={`toast ${syncMessage.startsWith("Sync") && !syncMessage.startsWith("Synced") ? "toast-error" : "toast-success"}`}
          aria-live="polite"
          onClick={() => setSyncMessage("")}
        >
          {syncMessage}
        </div>
      ) : null}
    </main>
  );
}
