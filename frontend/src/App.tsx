import { Home, LogIn, LogOut, RefreshCw, Settings } from "lucide-react";
import { useEffect, useState } from "react";

type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const dashboardStats = [
  { label: "Submitted", value: "0" },
  { label: "Eligible", value: "0" },
  { label: "Filtered Out", value: "0" },
  { label: "Needs Review", value: "0" },
];

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);

  useEffect(() => {
    fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { user: CurrentUser | null }) => setUser(payload.user))
      .finally(() => setIsLoadingUser(false));
  }, []);

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
            <button className="icon-button" aria-label="Sync applications" title="Sync applications">
              <RefreshCw size={18} />
            </button>
            <button className="icon-button" aria-label="Settings" title="Settings">
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
