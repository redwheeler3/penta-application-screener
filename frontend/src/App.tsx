import { LogIn, LogOut, Settings } from "lucide-react";
import { type SyntheticEvent, useEffect, useLayoutEffect, useState } from "react";
import { HouseIcon } from "./HouseIcon";
import * as api from "./api";
import { money, readProblem, resolveSheetId } from "./format";
import type {
  ApplicationDetail,
  AppSettings,
  AppStatus,
  Coverage,
  CurrentUser,
  DashboardCounts,
  ScreeningEstimateResponse,
  RankEstimateResponse,
  ScoreCurrentEstimateResponse,
  RankProgress,
  SettingsResponse,
  WorkflowState,
} from "./types";
import { ApplicationsList } from "./components/ApplicationsList";
import { CandidateDetail } from "./components/CandidateDetail";
import { InsightsView } from "./components/InsightsView";
import { RankingView } from "./components/RankingView";
import { SettingsPanel } from "./components/SettingsPanel";
import { Toasts } from "./components/Toasts";
import { WorkflowBar } from "./components/WorkflowBar";
import { useApplications } from "./hooks/useApplications";
import { useRanking } from "./hooks/useRanking";
import { useToasts } from "./hooks/useToasts";

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);

  // The form draft the user edits. Separate from `saved` so typing never affects
  // affordances that gate on persisted state until the change is saved. Null until
  // GET /settings resolves (there's no client-side default — the backend schema is the
  // sole source of the settings shape); the Settings tab gates on `saved` before reading it.
  const [draft, setDraft] = useState<AppSettings | null>(null);
  // The last settings persisted on the server. `draft` resets to this on load/save.
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);

  const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>({
    submitted: 0,
    status: { eligible: 0, ineligible: 0 },
    source: { untouched: 0, rules: 0, ai: 0, human: 0 },
  });
  const [workflow, setWorkflow] = useState<WorkflowState>({
    synced: false,
    importCurrent: true,
    screened: false,
    patternsDiscovered: false,
    candidatesScored: false,
    rankingCurrent: false,
  });
  const [coverage, setCoverage] = useState<Coverage>({});
  const [isSyncing, setIsSyncing] = useState(false);
  // Whether the Import confirmation card is open. Import has no cost (a Sheet pull,
  // no model calls), so it's a plain confirm — just friction so a click doesn't
  // immediately re-import, matching the Screen/Rank cards.
  const [importConfirm, setImportConfirm] = useState(false);

  // Workflow notifications surface as bottom-right toasts (success auto-dismisses;
  // errors/warnings persist until dismissed). See useToasts.
  const { toasts, showToast, showError, showWarning, dismissToast } = useToasts();

  // The applications-list view state (fetched page + facets + filter/search/sort/paging).
  // See useApplications; the selected candidate detail stays here (cross-cutting).
  const {
    applications,
    appTotal,
    appPage,
    appPageSize,
    appFilter,
    appFacets,
    appSearch,
    appSort,
    loadApplications,
    toggleSort,
    applyFilter,
    search: searchApplications,
  } = useApplications();
  const [selectedApp, setSelectedApp] = useState<ApplicationDetail | null>(null);
  // The row we drilled in from, so pressing Back in the detail can return the list
  // to that person instead of the top. Only the detail's Back button arms the scroll
  // (via `pendingScrollId`); other paths that clear the detail (tab switches, post-run
  // resets, brand click) leave it null and land at the top as before.
  const [pendingScrollId, setPendingScrollId] = useState<number | null>(null);

  // After the list re-renders following Back, bring the previously-clicked row into
  // view. useLayoutEffect so it runs before paint — no flash of the top of the list.
  useLayoutEffect(() => {
    if (pendingScrollId == null || selectedApp) return;
    const row = document.querySelector<HTMLElement>(`[data-app-id="${pendingScrollId}"]`);
    if (row) {
      // Align the row near the top of the viewport (not centered). scrollMarginTop
      // leaves a little breathing room so it sits just below the top edge.
      row.style.scrollMarginTop = "80px";
      row.scrollIntoView({ block: "start" });
    }
    setPendingScrollId(null);
  }, [pendingScrollId, selectedApp]);

  // Return from the detail to the list, remembering which row to scroll back to.
  function backToList() {
    if (selectedApp) setPendingScrollId(selectedApp.id);
    setSelectedApp(null);
  }

  // AI run flows share a shape: estimate (confirmation) -> running -> result.
  // Outcomes surface as toasts, so no per-step message state is kept here.
  const [screeningEstimate, setScreeningEstimate] = useState<ScreeningEstimateResponse | null>(null);
  const [screeningRunning, setScreeningRunning] = useState(false);
  const [screeningProgress, setScreeningProgress] = useState<{ processed: number; total: number } | null>(null);

  // The ranking cluster: the current run's dimensions, the ranked shortlist, the
  // committee's tiers, and the pure-persistence handlers that keep them in lockstep.
  // See useRanking. The AI run flow (discover/score) stays here — it orchestrates
  // dashboard/list/tab refreshes across clusters.
  const {
    rankingRun,
    ranking,
    tiers,
    refreshRankingRun,
    loadRanking,
    saveTiers,
    acknowledgeNewDimensions,
    addProposal,
    removeProposal,
  } = useRanking(showError);

  // The full Rank discovers a new criteria set; the safe alternative fills missing
  // scores against the current set. Both begin with their own capped estimate.
  const [rankEstimate, setRankEstimate] = useState<RankEstimateResponse | null>(null);
  const [scoreCurrentEstimate, setScoreCurrentEstimate] = useState<ScoreCurrentEstimateResponse | null>(null);
  const [rankRunning, setRankRunning] = useState(false);
  const [rankProgress, setRankProgress] = useState<RankProgress | null>(null);
  // The model's live reasoning during the run's opaque calls (criteria discovery +
  // match, and post-score consolidation) — multi-minute calls with no per-item
  // progress, so we show the streamed "thinking" text instead of a bare spinner.
  // Both phases append here, so the box carries through the whole run.
  const [criteriaThinking, setCriteriaThinking] = useState("");

  // The results area is split into two peer tabs — the applications list and the
  // ranking — with `activeTab` choosing which is shown (a candidate detail drills in
  // over either). The Ranking tab only appears once a run exists (see the tab strip).
  const [activeTab, setActiveTab] = useState<"applications" | "ranking" | "insights" | "evals" | "settings">("applications");

  useEffect(() => {
    api
      .fetchCurrentUser()
      .then(setUser)
      .finally(() => setIsLoadingUser(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    api.fetchSettings().then(applySettingsResponse);
    refreshDashboard();
    refreshRankingRun();
    loadApplications({ filter: {}, page: 1, search: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  function applySettingsResponse(payload: SettingsResponse) {
    const sheetId = resolveSheetId(payload);
    setSaved(payload);
    setDraft({ ...payload.settings, googleSheetId: sheetId });
    // First-run setup: land on the Settings tab when there's no sheet configured
    // yet, so setup is front-and-centre.
    if (!sheetId) setActiveTab("settings");
  }

  function refreshDashboard() {
    api.fetchDashboard().then((payload) => {
      setDashboardCounts(payload.counts);
      setWorkflow(payload.workflow);
      setCoverage(payload.coverage ?? {});
    });
  }

  async function viewApplication(id: number) {
    const application = await api.fetchApplication(id);
    setSelectedApp(application);
    // The clicked row can be far below the detail heading (especially in Ranking),
    // so reveal the new view rather than preserving the old scroll position.
    requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  }

  function login() {
    window.location.href = api.authLoginUrl();
  }

  async function logout() {
    await api.logout();
    setUser(null);
  }

  async function saveSettings(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return; // form only renders once draft is loaded, so this can't fire
    setIsSavingSettings(true);
    const response = await api.saveSettings(draft);
    if (response.ok) {
      const payload: SettingsResponse = await response.json();
      applySettingsResponse(payload);
      // Cost estimates are a snapshot of the saved AI settings. Invalidate them so
      // a cap increase (or any model/cost setting change) cannot leave a stale
      // over-cap warning and disabled confirmation button on screen.
      setScreeningEstimate(null);
      setRankEstimate(null);
      setSelectedApp(null);
      setActiveTab("applications");
      refreshDashboard();
      requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    } else {
      showError("Settings could not be saved.");
    }
    setIsSavingSettings(false);
  }

  // Open the Import confirmation. Close the other cards so only one shows at a time.
  function requestImport() {
    setScreeningEstimate(null);
    setRankEstimate(null);
    setImportConfirm(true);
  }

  async function syncApplications() {
    setImportConfirm(false);
    setIsSyncing(true);
    try {
      const response = await api.syncApplications();
      if (response.ok) {
        const payload: {
          rowCount: number;
          importedCount: number;
          updatedCount: number;
          unchangedCount: number;
        } = await response.json();
        const { rowCount, importedCount, updatedCount, unchangedCount } = payload;
        showToast(
          `Synced ${rowCount} rows: ${importedCount} imported, ${updatedCount} updated, ${unchangedCount} unchanged.`,
        );
        refreshDashboard();
        loadApplications({ page: 1 });
      } else {
        const problem = await readProblem(response);
        showError(problem ? `Sync failed: ${problem}` : `Sync failed (HTTP ${response.status}).`);
      }
    } catch (error) {
      showError(
        `Sync error: ${
          error instanceof Error ? error.message : "Network request failed. Check that the backend is running."
        }`,
      );
    }
    setIsSyncing(false);
  }

  // Fetch the cost estimate and show the confirmation prompt. AI never runs without
  // the user first seeing the estimate and confirming (SPEC cost control).
  async function requestScreeningEstimate() {
    setRankEstimate(null); // only one card shows at a time
    setImportConfirm(false);
    const response = await api.fetchScreeningEstimate();
    if (response.ok) {
      // Always open the card — even a $0 no-op states there's nothing to do and
      // disables Confirm, rather than firing a transient toast.
      setScreeningEstimate(await response.json());
    } else {
      showError("Could not load the AI cost estimate for flagging submissions.");
    }
  }

  async function runScreening() {
    setScreeningRunning(true);
    setScreeningEstimate(null);
    setScreeningProgress(null);
    try {
      const response = await api.runScreening();
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        showError(problem ? `Flagging failed: ${problem}` : "Flagging failed.");
      } else {
        await api.streamNdjson(response.body, (event) => {
          if (event.type === "progress") {
            setScreeningProgress({ processed: event.processed, total: event.total });
          } else if (event.type === "summary") {
            const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
            showToast(
              `Flagging complete: ${event.flagged} flagged of ${event.analyzed + event.cached} analyzed ` +
                `(${money(event.totalCostUsd)}).` +
                failedNote,
            );
          }
        });
        // Refresh dashboard counts, the list + facet counts, and the open candidate
        // so new flags/status show immediately after the run.
        refreshDashboard();
        loadApplications({ page: appPage });
        setSelectedApp(null);
        setActiveTab("applications");
      }
    } catch (error) {
      showError(error instanceof Error ? `Flagging error: ${error.message}` : "Flagging error.");
    }
    setScreeningProgress(null);
    setScreeningRunning(false);
  }

  async function requestRankEstimate() {
    setScreeningEstimate(null); // only one card shows at a time
    setImportConfirm(false);
    setScoreCurrentEstimate(null);
    const [rankResponse, currentScoreResponse] = await Promise.all([
      api.fetchRankEstimate(),
      rankingRun ? api.fetchScoreCurrentEstimate() : Promise.resolve(null),
    ]);
    if (rankResponse.ok) {
      // Always open the card, even when unchanged: it explains there's nothing to
      // re-rank and disables Confirm, instead of a transient toast.
      setRankEstimate(await rankResponse.json());
      if (currentScoreResponse?.ok) setScoreCurrentEstimate(await currentScoreResponse.json());
    } else {
      showError("Could not load the AI cost estimate for ranking.");
    }
  }

  async function runRank(mode: "discover" | "score-current") {
    setRankRunning(true);
    setRankEstimate(null);
    setScoreCurrentEstimate(null);
    setRankProgress(null);
    setCriteriaThinking("");
    try {
      const response = mode === "discover" ? await api.runRank() : await api.scoreCurrent();
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        showError(problem ? `Ranking failed: ${problem}` : "Ranking failed.");
      } else {
        await api.streamNdjson(response.body, (event) => {
          if (event.type === "phase") {
            // New pass: reset the bar to its total (criteria is one call → no total).
            setRankProgress({ phase: event.phase, processed: 0, total: event.total ?? 0 });
          } else if (event.type === "progress") {
            setRankProgress({ phase: event.phase, processed: event.processed, total: event.total });
          } else if (event.type === "stage") {
            // A sub-step transition within the criteria phase — update the stage label
            // in place, keeping the current phase/counts.
            setRankProgress((prior) =>
              prior ? { ...prior, stage: event.stage } : { phase: "criteria", processed: 0, total: 0, stage: event.stage },
            );
          } else if (event.type === "thinking") {
            // Live model reasoning from the opaque calls (discovery + match, and
            // consolidation); append as it streams so the box carries the whole run.
            setCriteriaThinking((prior) => prior + event.text);
          } else if (event.type === "warning") {
            // Run-level but non-fatal (e.g. some discovery workers timed out); the run
            // continued on the survivors. Amber toast — informational, not a failure.
            showWarning(event.message || "The run completed with a warning.");
          } else if (event.type === "error") {
            // Fatal phase failure (e.g. the criteria thread crashed); ends the stream.
            showError(event.message || "Ranking failed.");
          } else if (event.type === "summary") {
            const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
            showToast(
              `${mode === "discover" ? "Ranking complete" : "Current criteria updated"}: ` +
                `${event.dimensions} criteria, ${event.scored} candidates scored ` +
                `(${money(event.totalCostUsd)}).` +
                failedNote,
            );
          }
        });
        // The chain replaced the dimensions and scores. Await the run refresh before
        // opening the ranking, so the tier list's labelFor has the new run's names
        // before its chips render (else they briefly show raw keys).
        await refreshRankingRun();
        refreshDashboard();
        // Land the user directly in the ranked view — the ranking is the whole point
        // of the run, and the "View ranking" button was easy to miss. openRanking
        // clears any open candidate and loads the ranking + tiers.
        await openRanking();
      }
    } catch (error) {
      showError(error instanceof Error ? `Ranking error: ${error.message}` : "Ranking error.");
    }
    setRankProgress(null);
    setRankRunning(false);
    setCriteriaThinking("");
  }

  // Open the ranked view: clear any open candidate, load the shortlist + tiers (via
  // useRanking), and switch to the tab only if the load succeeded. The detail clear +
  // tab switch are App-level (view routing), so they stay here around the hook's load.
  async function openRanking() {
    setSelectedApp(null);
    if (await loadRanking()) setActiveTab("ranking");
  }

  // Human override of an application's status. The backend marks it human-owned and
  // sticky against future machine runs.
  async function overrideStatus(id: number, status: AppStatus) {
    const response = await api.overrideStatus(id, status);
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      // Refresh dashboard + list/facet counts so the change shows on "Back to list".
      refreshDashboard();
      loadApplications({ page: appPage });
    }
  }

  // Remove a human override, handing the decision back to the machine. The backend
  // recomputes status from the current findings (see DELETE handler).
  async function clearStatusOverride(id: number) {
    const response = await api.clearStatusOverride(id);
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      refreshDashboard();
      loadApplications({ page: appPage });
    }
  }

  async function savePrivateNote(id: number, note: string): Promise<boolean> {
    const response = await api.savePrivateNote(id, note);
    if (!response.ok) {
      showError("Could not save your private note.");
      return false;
    }
    const payload: { application: ApplicationDetail } = await response.json();
    setSelectedApp(payload.application);
    return true;
  }

  const hasGoogleSheetLink = Boolean(saved && resolveSheetId(saved));

  return (
    <main className="app-shell">
      <header className="topnav">
        <div className="topnav-inner">
          {user ? (
            <button
              className="brand-lockup brand-button"
              type="button"
              onClick={() => setSelectedApp(null)}
              title="Back to applications"
            >
              <span className="brand-mark" aria-hidden="true">
                <HouseIcon size={30} />
              </span>
              <span className="brand-name">Penta Housing Co-Op</span>
            </button>
          ) : (
            <div className="brand-lockup">
              <span className="brand-mark" aria-hidden="true">
                <HouseIcon size={30} />
              </span>
              <span className="brand-name">Penta Housing Co-Op</span>
            </div>
          )}
          {user ? (
            <div className="toolbar">
              <div className="user-chip">
                <span>{user.displayName}</span>
                <strong>{user.role}</strong>
              </div>
              <button className="icon-button" aria-label="Log out" title="Log out" onClick={logout}>
                <LogOut size={18} />
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <div className="page-heading">
        <h1>Application Screener</h1>
      </div>

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
          {/* Global actions first (workflow acts on the whole dataset regardless of
              tab), then the tab row, then the active tab's content. */}
          <WorkflowBar
            workflow={workflow}
            coverage={coverage}
            dashboardCounts={dashboardCounts}
            hasGoogleSheetLink={hasGoogleSheetLink}
            isSyncing={isSyncing}
            importConfirm={importConfirm}
            onRequestImport={requestImport}
            onConfirmImport={syncApplications}
            onCancelImport={() => setImportConfirm(false)}
            screeningRunning={screeningRunning}
            screeningEstimate={screeningEstimate}
            screeningProgress={screeningProgress}
            onRequestScreening={requestScreeningEstimate}
            onRunScreening={runScreening}
            onCancelScreening={() => setScreeningEstimate(null)}
            rankRunning={rankRunning}
            rankEstimate={rankEstimate}
            scoreCurrentEstimate={scoreCurrentEstimate}
            hasCurrentCriteria={rankingRun !== null}
            rankProgress={rankProgress}
            criteriaThinking={criteriaThinking}
            onRequestRank={requestRankEstimate}
            onRunRank={runRank}
            onCancelRank={() => {
              setRankEstimate(null);
              setScoreCurrentEstimate(null);
            }}
          />

          {/* Tab row: the two data views on the left, Settings set apart on the
              right (config, not a third data view). */}
          <div className="view-tabs no-print" role="tablist" aria-label="Views">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "applications" && !selectedApp}
              className={`tab-button${activeTab === "applications" && !selectedApp ? " active" : ""}`}
              onClick={() => {
                setSelectedApp(null);
                setActiveTab("applications");
              }}
            >
              Applications
            </button>
            {/* The Ranking tab only appears once a run exists. Clicking it loads/
                reconciles the ranking + tiers from the server (pure math, no cost). */}
            {rankingRun ? (
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "ranking" && !selectedApp}
                className={`tab-button${activeTab === "ranking" && !selectedApp ? " active" : ""}`}
                onClick={openRanking}
              >
                Ranking
              </button>
            ) : null}
            {/* The AI developer/operator surface, split by purpose: Observability (what the
                AI did + cost, per-run traces once a run exists) and Evals (invariants / live
                per-pass / judge — need no run, work before any Rank). */}
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "insights" && !selectedApp}
              className={`tab-button${activeTab === "insights" && !selectedApp ? " active" : ""}`}
              onClick={() => {
                setSelectedApp(null);
                setActiveTab("insights");
              }}
            >
              Observability
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "evals" && !selectedApp}
              className={`tab-button${activeTab === "evals" && !selectedApp ? " active" : ""}`}
              onClick={() => {
                setSelectedApp(null);
                setActiveTab("evals");
              }}
            >
              Evals
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "settings" && !selectedApp}
              className={`tab-button tab-button-settings${activeTab === "settings" && !selectedApp ? " active" : ""}`}
              onClick={() => {
                setSelectedApp(null);
                setActiveTab("settings");
              }}
            >
              <Settings size={14} />
              <span>Settings</span>
            </button>
          </div>

          <section className="panel">
            {selectedApp ? (
              <CandidateDetail
                app={selectedApp}
                onBack={backToList}
                onOverrideStatus={overrideStatus}
                onClearOverride={clearStatusOverride}
                onSavePrivateNote={savePrivateNote}
              />
            ) : activeTab === "settings" && draft ? (
              <SettingsPanel
                draft={draft}
                setDraft={setDraft}
                saved={saved}
                isSaving={isSavingSettings}
                onSubmit={saveSettings}
              />
            ) : activeTab === "ranking" && ranking ? (
              <RankingView
                ranking={ranking}
                rankingRun={rankingRun}
                tiers={tiers}
                proposedDimensions={rankingRun?.proposedDimensions ?? []}
                onSaveTiers={(next) => saveTiers(next)}
                onAcknowledgeNew={acknowledgeNewDimensions}
                onAddProposal={addProposal}
                onRemoveProposal={removeProposal}
                onSelectApplication={viewApplication}
              />
            ) : activeTab === "insights" ? (
              <InsightsView family="obs" run={rankingRun} onToast={showToast} onError={showError} />
            ) : activeTab === "evals" ? (
              <InsightsView family="eval" run={rankingRun} onToast={showToast} onError={showError} />
            ) : (
              <ApplicationsList
                applications={applications}
                appFilter={appFilter}
                appFacets={appFacets}
                dashboardCounts={dashboardCounts}
                appSearch={appSearch}
                appSort={appSort}
                appPage={appPage}
                appPageSize={appPageSize}
                appTotal={appTotal}
                onApplyFilter={applyFilter}
                onSearch={searchApplications}
                onToggleSort={toggleSort}
                onSelectApplication={viewApplication}
                onChangePageSize={(size) => loadApplications({ page: 1, pageSize: size })}
                onGoToPage={(page) => loadApplications({ page })}
              />
            )}
          </section>
        </>
      )}
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </main>
  );
}
