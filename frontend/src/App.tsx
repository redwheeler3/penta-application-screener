import { Home, LogIn, LogOut, RefreshCw, Settings } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

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
  needsReview: number;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const defaultSettings: AppSettings = {
  google_sheet_id: "",
  unit_size: "2br",
  move_in_date: "2026-09-01",
  income_min: 70000,
  income_max: 150000,
};

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
    needsReview: 0,
  });
  const [syncMessage, setSyncMessage] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);

  const dashboardStats = [
    { label: "Submitted", value: dashboardCounts.submitted },
    { label: "Eligible", value: dashboardCounts.eligible },
    { label: "Filtered Out", value: dashboardCounts.filteredOut },
    { label: "Needs Review", value: dashboardCounts.needsReview },
  ];

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

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
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
    } else {
      const payload: { detail?: string } = await response.json();
      setSyncMessage(payload.detail ?? "Sync failed.");
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
                      Spreadsheet: {googleSheetTitle}
                    </a>
                  ) : settings.google_sheet_id ? (
                    <span className="sheet-reference">Spreadsheet title will appear after the link is saved.</span>
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

          {syncMessage ? (
            <section className="sync-message" aria-live="polite">
              {syncMessage}
            </section>
          ) : null}

          <section className="stats-grid" aria-label="Application dashboard">
            {dashboardStats.map((stat) => (
              <article className="stat-card" key={stat.label}>
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </article>
            ))}
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <span className="panel-kicker">Current opening</span>
                <h2>Applications</h2>
              </div>
              <span>Ready for Google Sheets sync</span>
            </div>
            <div className="empty-state">
              <p>No applications imported yet.</p>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
