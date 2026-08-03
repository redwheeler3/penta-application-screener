import { Filter, LogIn, LogOut, Settings } from "lucide-react";
import { type ReactNode, type SyntheticEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
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
  ViewTab,
  WorkflowState,
} from "./types";
import { AdminSettingsPanel } from "./components/AdminSettingsPanel";
import { ApplicationsList } from "./components/ApplicationsList";
import { CandidateDetail } from "./components/CandidateDetail";
import { EligibilitySettingsPanel } from "./components/EligibilitySettingsPanel";
import { AIQualityView } from "./components/AIQualityView";
import { FeedbackButton } from "./components/FeedbackButton";
import { RankingView } from "./components/RankingView";
import { Toasts } from "./components/Toasts";
import { WorkflowBar } from "./components/WorkflowBar";
import { useApplications } from "./hooks/useApplications";
import { retryWithBackoff } from "./retry";
import { useRanking } from "./hooks/useRanking";
import { useToasts } from "./hooks/useToasts";

type BrowserLocation = {
  screenerLocation: true;
  tab: ViewTab;
  applicantId?: number;
};

function isBrowserLocation(value: unknown): value is BrowserLocation {
  return (
    typeof value === "object" &&
    value !== null &&
    "screenerLocation" in value &&
    (value as BrowserLocation).screenerLocation === true &&
    "tab" in value
  );
}

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [userLoadFailed, setUserLoadFailed] = useState(false);
  // Set when the OAuth callback bounced a non-allowlisted account back here
  // (?access=denied). Read once from the URL; the flag is stripped so a reload clears it.
  const [accessDenied, setAccessDenied] = useState(false);

  // The form draft the user edits. Separate from `saved` so typing never affects
  // affordances that gate on persisted state until the change is saved. Null until
  // GET /settings resolves (there's no client-side default — the backend schema is the
  // sole source of the settings shape); the Settings tab gates on `saved` before reading it.
  const [draft, setDraft] = useState<AppSettings | null>(null);
  // The last settings persisted on the server. `draft` resets to this on load/save.
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  // True once the initial settings load has definitively failed (after retries). Drives the
  // Admin Settings panel's error+retry state so it never silently falls through to the
  // Applications view when `draft` never loaded (the cold-start dropped-request bug).
  const [settingsLoadFailed, setSettingsLoadFailed] = useState(false);

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
  // The workflow's default values are deliberately never shown as a settled state: a
  // dropped first dashboard request must not make a completed workflow look brand new.
  const [dashboardLoadState, setDashboardLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [isSyncing, setIsSyncing] = useState(false);
  // Whether the Import confirmation card is open. Import has no cost (a Sheet pull,
  // no model calls), so it's a plain confirm — just friction so a click doesn't
  // immediately re-import, matching the Screen/Rank cards.
  const [importConfirm, setImportConfirm] = useState(false);

  // Workflow notifications surface as bottom-right toasts (success auto-dismisses;
  // errors/warnings persist until dismissed). See useToasts.
  const { toasts, showToast, showError, showWarning, dismissToast } = useToasts();

  // The applications-list view state (full pool + client-derived filter/sort/facets).
  // See useApplications; the selected candidate detail stays here (cross-cutting).
  const {
    applications,
    applicationsLoadState,
    appFilter,
    appFacets,
    appSearch,
    appSort,
    reloadApplications,
    loadInitialApplications,
    toggleSort,
    applyFilter,
    search: searchApplications,
  } = useApplications();
  const [selectedApp, setSelectedApp] = useState<ApplicationDetail | null>(null);

  // The applicant id we last scrolled the detail to the top for. Opening a DIFFERENT
  // applicant should scroll; re-setting `selectedApp` for the SAME applicant (a note /
  // status / star save refreshes it) must NOT yank the scroll back up mid-edit.
  const scrolledDetailId = useRef<number | null>(null);

  // Scroll the detail panel's top (the Back/Print bar) into view on a NEW selection.
  // A layout effect, not the click handler: scrolling in the handler races React's
  // commit, so on a first open `.app-detail` isn't mounted yet and the scroll no-ops
  // (the intermittent "lands halfway down the page" bug). Post-commit the element is
  // guaranteed present. Runs before paint, so there's no visible jump.
  useLayoutEffect(() => {
    if (!selectedApp) {
      scrolledDetailId.current = null;
      return;
    }
    if (scrolledDetailId.current === selectedApp.id) return; // same applicant refresh
    scrolledDetailId.current = selectedApp.id;
    document.querySelector(".app-detail")?.scrollIntoView({ block: "start" });
  }, [selectedApp]);

  // Return from the detail through browser history so the list or ranking view preserves
  // the member's actual reading position.
  function backToList() {
    if (isBrowserLocation(window.history.state) && window.history.state.applicantId) {
      window.history.back();
      return;
    }
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
    rankingLoadState,
    tiers,
    refreshRankingRun,
    loadRanking,
    saveTiers,
    acknowledgeNewDimensions,
    dismissRequested,
    addProposal,
    removeProposal,
    setDisplayedProposals,
    staleAnalysis,
    checkForStaleRanking,
    reloadStaleRanking,
  } = useRanking(showError);

  // The full Rank discovers a new criteria set; the safe alternative fills missing
  // scores against the current set. Both begin with their own capped estimate.
  const [rankEstimate, setRankEstimate] = useState<RankEstimateResponse | null>(null);
  const [scoreCurrentEstimate, setScoreCurrentEstimate] = useState<ScoreCurrentEstimateResponse | null>(null);
  // A score-current estimate is optional enrichment for the Rank confirmation card. Keep a
  // generation so a slower response cannot update a card the member dismissed or replaced.
  const rankEstimateRequestRef = useRef(0);
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
  const [activeTab, setActiveTab] = useState<ViewTab>("applications");
  const isAdmin = user?.role === "admin";

  function replaceBrowserLocation(location: BrowserLocation) {
    window.history.replaceState(location, "", window.location.pathname);
  }

  function pushBrowserLocation(location: BrowserLocation) {
    window.history.pushState(location, "", window.location.pathname);
  }

  function dismissRankEstimate() {
    rankEstimateRequestRef.current += 1;
    setRankEstimate(null);
    setScoreCurrentEstimate(null);
  }

  useEffect(() => {
    void loadCurrentUser();
    // The OAuth callback redirects here with ?access=denied for a non-allowlisted
    // account. Read it once, then strip it from the URL so a later reload is clean.
    const params = new URLSearchParams(window.location.search);
    if (params.get("access") === "denied") {
      setAccessDenied(true);
    }
    // This is a client-side app rather than a URL-routed one, so seed the initial
    // browser-history entry with the default view. Later tab/detail transitions add
    // entries of the same shape for the browser Back button and mobile back swipe.
    replaceBrowserLocation({ screenerLocation: true, tab: "applications" });
  }, []);

  async function loadCurrentUser(): Promise<void> {
    setIsLoadingUser(true);
    setUserLoadFailed(false);
    try {
      setUser(await retryWithBackoff(api.fetchCurrentUser, 3));
    } catch {
      // Do not turn an unavailable service into a false signed-out state: the member needs a
      // retry for the session check, not an unnecessary OAuth round trip.
      setUserLoadFailed(true);
    } finally {
      setIsLoadingUser(false);
    }
  }

  useEffect(() => {
    if (!user) return;
    void loadSettings();
    void loadInitialDashboard();
    refreshRankingRun();
    void loadInitialApplications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // A ranking became stale (another member re-ranked) — surface it as a global toast with a
  // Reload action, so it reaches the member wherever they are on the page (not only on the
  // Ranking tab). Fired once per stale transition; the ref de-dupes re-renders while stale.
  const staleToastShown = useRef(false);
  useEffect(() => {
    if (staleAnalysis && !staleToastShown.current) {
      staleToastShown.current = true;
      showWarning(
        "This ranking was refreshed by another member. Reload to see the current criteria.",
        { label: "Reload", onClick: () => void reloadStaleRanking() },
      );
    } else if (!staleAnalysis) {
      staleToastShown.current = false; // reset once reloaded, so a later drift toasts again
    }
  }, [staleAnalysis, showWarning, reloadStaleRanking]);

  // Detect staleness passively: when the member returns to the tab/window, cheaply re-check
  // whether the loaded ranking is still current. There's no server push, so this catches the
  // "switched away, another member re-ranked, came back" case without a manual refresh (and
  // without a standing background poll). A save onto a stale board is already caught by the
  // 409 path; this covers passive viewing.
  //
  // Suppressed while THIS member's own rank is in flight: their run creates the new analysis,
  // so mid-completion the loaded id (old) differs from the server's (new) — a focus event then
  // would misread that as "another member re-ranked" and fire the stale toast alongside their
  // own green "complete" toast. runRank updates the loaded id (refreshRankingRun/openRanking)
  // before it clears rankRunning, so gating here closes that window. A ref so toggling
  // rankRunning doesn't re-subscribe the listener.
  const rankRunningRef = useRef(false);
  rankRunningRef.current = rankRunning;
  useEffect(() => {
    if (!user) return;
    const onFocus = () => {
      if (document.visibilityState === "visible" && !rankRunningRef.current) {
        void checkForStaleRanking();
      }
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [user, checkForStaleRanking]);

  function applySettingsResponse(payload: SettingsResponse) {
    const sheetId = resolveSheetId(payload);
    setSaved(payload);
    setDraft({ ...payload.settings, googleSheetId: sheetId });
    setSettingsLoadFailed(false);
    // First-run setup: land on Admin Settings when there's no sheet configured yet, so
    // setup is front-and-centre. Only admins can set the sheet, so only redirect them —
    // a member stays on Applications.
    if (!sheetId && isAdmin) {
      setActiveTab("adminSettings");
      replaceBrowserLocation({ screenerLocation: true, tab: "adminSettings" });
    }
  }

  // A Sheets title is a convenience label, not part of the editable settings. If Google was
  // unavailable during the initial load, retry only that label when the member returns to the
  // tab. Updating `saved` alone leaves any in-progress `draft` edits untouched.
  const linkedSheetId = saved?.settings.googleSheetId ?? "";
  const linkedSheetTitle = saved?.googleSheetTitle ?? null;
  useEffect(() => {
    if (!user || !linkedSheetId || linkedSheetTitle) return;

    const retrySheetTitle = () => {
      if (document.visibilityState !== "visible") return;
      void api
        .fetchSettings()
        .then((payload) => {
          if (!payload.googleSheetTitle) return;
          setSaved((current) =>
            current && current.settings.googleSheetId === payload.settings.googleSheetId
              ? { ...current, googleSheetTitle: payload.googleSheetTitle }
              : current,
          );
        })
        // The title remains optional: another transient Google failure should be silent and
        // is retried the next time the member returns to the tab.
        .catch(() => {});
    };

    document.addEventListener("visibilitychange", retrySheetTitle);
    return () => document.removeEventListener("visibilitychange", retrySheetTitle);
  }, [user, linkedSheetId, linkedSheetTitle]);

  // Load the shared settings, retrying a few times with backoff. `draft` is set ONLY here, and
  // nothing re-fetches it on tab switches — so a single dropped request (a cold Fly machine
  // resuming from suspend, or a deploy restart, cuts the first request) would otherwise leave
  // `draft` null forever and the Admin Settings tab silently rendering the Applications view.
  // On definitive failure we flag it so the Admin panel shows an error+retry instead.
  async function loadSettings(): Promise<void> {
    try {
      applySettingsResponse(await retryWithBackoff(api.fetchSettings, 3));
    } catch {
      setSettingsLoadFailed(true);
    }
  }

  // Linking/changing the applications sheet changes the source pool, so the synced data is now
  // stale relative to it — the workflow bar should go amber (re-sync needed). Apply the new
  // settings AND refresh the dashboard + applications so that shows immediately, rather than
  // only after a manual page refresh.
  function applyLinkedSheet(payload: SettingsResponse) {
    applySettingsResponse(payload);
    refreshDashboard();
    reloadApplications();
  }

  function applyDashboard(payload: { counts: DashboardCounts; workflow: WorkflowState; coverage?: Coverage }) {
    setDashboardCounts(payload.counts);
    setWorkflow(payload.workflow);
    setCoverage(payload.coverage ?? {});
    setDashboardLoadState("ready");
  }

  function refreshDashboard() {
    api
      .fetchDashboard()
      .then(applyDashboard)
      // A dropped request (cold machine) shouldn't nag or throw an unhandled rejection — the
      // counts stay at their last values and the next interaction refreshes them. `getJson`
      // now rejects on non-2xx, so this catch is required.
      .catch(() => {});
  }

  // Eligibility is computed from the current member's rules and overrides whenever a view is
  // read. Every mutation therefore needs to refresh each surface that presents that derived
  // status: the workflow bar, application rows/facets, and an already-open ranked shortlist.
  function refreshEligibilityViews() {
    refreshDashboard();
    reloadApplications();
    if (ranking) void loadRanking();
  }

  // A Fly wake or deploy restart can drop the first request from a newly signed-in page.
  // Dashboard data controls every workflow badge and gate, so retry before showing any
  // placeholder state; a later retry button remains available if recovery never succeeds.
  async function loadInitialDashboard(): Promise<void> {
    setDashboardLoadState("loading");
    try {
      applyDashboard(await retryWithBackoff(api.fetchDashboard, 5));
    } catch {
      setDashboardLoadState("error");
    }
  }

  async function viewApplication(id: number) {
    let application: ApplicationDetail;
    try {
      application = await api.fetchApplication(id);
    } catch {
      showError("Couldn't load that applicant. Please try again.");
      return;
    }
    pushBrowserLocation({ screenerLocation: true, tab: activeTab, applicantId: id });
    setSelectedApp(application);
    // The scroll to the detail's top happens in a layout effect keyed on the selected
    // applicant id (see below) — NOT here: scrolling in this handler races React's commit,
    // so on a first open `.app-detail` isn't in the DOM yet and the scroll no-ops (the
    // "lands halfway down the page" bug). Running it post-commit guarantees the element exists.
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
      dismissRankEstimate();
      setSelectedApp(null);
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
    dismissRankEstimate();
    setImportConfirm(true); // open first; the badge refresh below shouldn't gate the card
    refreshDashboard(); // freshen the badge against current shared state (see requestScreeningEstimate)
  }

  async function syncApplications() {
    setImportConfirm(false);
    setIsSyncing(true);
    try {
      const response = await api.syncApplications();
      if (response.ok) {
        const payload: {
          rowCount: number;
          duplicateCount: number;
          importedCount: number;
          updatedCount: number;
          unchangedCount: number;
          deletedCount: number;
        } = await response.json();
        const { rowCount, duplicateCount, importedCount, updatedCount, unchangedCount, deletedCount } = payload;
        // rowCount is every raw sheet row; imported/updated/unchanged count only the
        // deduplicated applications. Surface the duplicates that account for the gap (a
        // repeat submission keeps the latest), so the numbers reconcile — but only mention
        // them when there are any, to keep the common clean-sync message short.
        const dupeNote = duplicateCount > 0 ? `, ${duplicateCount} duplicate` : "";
        const deletedNote = deletedCount > 0 ? `, ${deletedCount} deleted` : "";
        showToast(
          `Synced ${rowCount} rows: ${importedCount} imported, ${updatedCount} updated, ${unchangedCount} unchanged${deletedNote}${dupeNote}.`,
        );
        refreshDashboard();
        reloadApplications();
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
    dismissRankEstimate(); // only one card shows at a time
    setImportConfirm(false);
    const response = await api.fetchScreeningEstimate();
    if (response.ok) {
      // Always open the card — even a $0 no-op states there's nothing to do and
      // disables Confirm, rather than firing a transient toast.
      setScreeningEstimate(await response.json());
    } else {
      showError("Could not load the AI cost estimate for screening.");
    }
    // Re-pull the dashboard so the badge reflects current shared state (another member may
    // have run since our last fetch — M16). AFTER the estimate, not before: the dashboard is
    // the heaviest call (~120ms) and fired first it competes with the estimate fetch the card
    // waits on, adding a visible pause before the card appears.
    refreshDashboard();
  }

  async function runScreening() {
    setScreeningRunning(true);
    setScreeningEstimate(null);
    setScreeningProgress(null);
    try {
      const response = await api.runScreening();
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        showError(problem ? `Screening failed: ${problem}` : "Screening failed.");
      } else {
        await api.streamNdjson(response.body, (event) => {
          if (event.type === "progress") {
            setScreeningProgress({ processed: event.processed, total: event.total });
          } else if (event.type === "summary") {
            const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
            showToast(
              `Screening complete: ${event.flagged} flagged of ${event.analyzed + event.cached} analyzed ` +
                `(${money(event.totalCostUsd)}).` +
                failedNote,
            );
          }
        });
        // Refresh dashboard counts, the list + facet counts, and the open candidate
        // so new flags/status show immediately after the run.
        refreshDashboard();
        reloadApplications();
        setSelectedApp(null);
      }
    } catch (error) {
      showError(error instanceof Error ? `Screening error: ${error.message}` : "Screening error.");
    }
    setScreeningProgress(null);
    setScreeningRunning(false);
  }

  async function requestRankEstimate() {
    setScreeningEstimate(null); // only one card shows at a time
    setImportConfirm(false);
    const requestId = rankEstimateRequestRef.current + 1;
    rankEstimateRequestRef.current = requestId;
    setRankEstimate(null);
    setScoreCurrentEstimate(null);
    // The full-Rank estimate alone is the confirmation gate. Start the exact
    // score-current calculation at the same time, but don't make the card wait for its
    // cache-grid read; it only adds the optional "Score missing applicants" path.
    const rankPromise = api.fetchRankEstimate();
    const scoreCurrentPromise = rankingRun ? api.fetchScoreCurrentEstimate() : null;
    // Attach a rejection handler now: the optional read can fail before the full-Rank
    // estimate arrives and before we attach its result handler below.
    if (scoreCurrentPromise) void scoreCurrentPromise.catch(() => undefined);
    const rankResponse = await rankPromise;
    if (requestId !== rankEstimateRequestRef.current) return;
    if (rankResponse.ok) {
      // Always open the card, even when unchanged: it explains there's nothing to
      // re-rank and disables Confirm, instead of a transient toast.
      const estimate = await rankResponse.json();
      if (requestId !== rankEstimateRequestRef.current) return;
      setRankEstimate(estimate);
      if (scoreCurrentPromise) {
        void scoreCurrentPromise
          .then(async (response) => {
            if (!response.ok || requestId !== rankEstimateRequestRef.current) return;
            const estimate = await response.json();
            if (requestId === rankEstimateRequestRef.current) setScoreCurrentEstimate(estimate);
          })
          // This optional path previously failed silently for non-OK responses. A rejected
          // request should likewise leave the full-Rank confirmation usable.
          .catch(() => undefined);
      }
    } else {
      showError("Could not load the AI cost estimate for ranking.");
    }
    // Refresh the badge AFTER the estimate (see requestScreeningEstimate): the heavy dashboard
    // call fired first would compete with the estimate fetches and delay the card.
    refreshDashboard();
  }

  async function runRank(mode: "discover" | "score-current") {
    setRankRunning(true);
    dismissRankEstimate();
    setRankProgress(null);
    setCriteriaThinking("");
    // A discover run consumes the pending proposals (they become real dimensions). Clear
    // them from the UI as soon as the run STARTS — they're in use now — rather than leaving
    // them visible until the run finishes and the refresh lands. Remember them so a failed
    // run (nothing consumed) can restore them.
    const priorProposals = rankingRun?.proposedDimensions ?? [];
    if (mode === "discover" && priorProposals.length > 0) {
      setDisplayedProposals([]);
    }
    try {
      const response = mode === "discover" ? await api.runRank() : await api.scoreCurrent();
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        showError(problem ? `Ranking failed: ${problem}` : "Ranking failed.");
        // The run never consumed the proposals — restore them so the member doesn't lose
        // what they typed.
        if (mode === "discover" && priorProposals.length > 0) {
          setDisplayedProposals(priorProposals);
        }
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
        // The chain replaced the dimensions and scores. Refresh the run and shortlist
        // so the Ranking tab is current when the member chooses to open it.
        await refreshRankingRun();
        refreshDashboard();
        void loadRanking();
      }
    } catch (error) {
      showError(error instanceof Error ? `Ranking error: ${error.message}` : "Ranking error.");
      // A mid-stream throw may land either before or after the run consumed the proposals
      // (create_analysis commits at end of phase 1). Reconcile to server truth rather than
      // guess — refresh restores them if untouched, or confirms them gone if consumed.
      if (mode === "discover") refreshRankingRun();
    }
    setRankProgress(null);
    setRankRunning(false);
    setCriteriaThinking("");
  }

  // Restore a state recorded in browser history. This path deliberately never writes history:
  // a Back/Forward gesture must move through the entries the member already created.
  async function restoreBrowserLocation(location: BrowserLocation) {
    setSelectedApp(null);
    setActiveTab(location.tab);
    if (location.tab === "ranking") void loadRanking();
    if (!location.applicantId) return;

    try {
      const application = await api.fetchApplication(location.applicantId);
      setSelectedApp(application);
    } catch {
      showError("Couldn't load that applicant. Please try again.");
    }
  }

  useEffect(() => {
    const onPopState = (event: PopStateEvent) => {
      if (isBrowserLocation(event.state)) void restoreBrowserLocation(event.state);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  });

  // Jump to a top-level view (e.g. from a feedback item's context link). Ranking switches
  // immediately; its loader replaces the empty panel with the shortlist when ready. Each
  // deliberate navigation records its destination before changing the visible view.
  function navigateToView(tab: ViewTab) {
    if (activeTab === tab && !selectedApp) return;
    if (tab === "ranking") {
      pushBrowserLocation({ screenerLocation: true, tab });
      setSelectedApp(null);
      setActiveTab(tab);
      void loadRanking();
      return;
    }
    pushBrowserLocation({ screenerLocation: true, tab });
    setSelectedApp(null);
    setActiveTab(tab);
  }

  // One tab in the view-tab row. A tab is "active" only when it's selected AND no
  // applicant detail is open (opening a detail deselects every tab). `extraClass`
  // carries the right-aligned settings-tab modifier; `icon` the optional leading glyph.
  function tabButton(tab: ViewTab, label: string, icon?: ReactNode, extraClass = "") {
    const active = activeTab === tab && !selectedApp;
    return (
      <button
        type="button"
        role="tab"
        aria-selected={active}
        className={`tab-button${extraClass ? ` ${extraClass}` : ""}${active ? " active" : ""}`}
        onClick={() => navigateToView(tab)}
      >
        {icon}
        {icon ? <span>{label}</span> : label}
      </button>
    );
  }

  // Apply a status-mutation response: show the updated applicant and refresh the
  // derived eligibility surfaces. No-op on a failed response.
  async function applyStatusResponse(response: Response) {
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      refreshEligibilityViews();
    }
  }

  // Human override of an application's status. The backend marks it human-owned and
  // sticky against future machine runs.
  async function overrideStatus(id: number, status: AppStatus) {
    await applyStatusResponse(await api.overrideStatus(id, status));
  }

  // Remove a human override, handing the decision back to the machine. The backend
  // recomputes status from the current findings (see DELETE handler).
  async function clearStatusOverride(id: number) {
    await applyStatusResponse(await api.clearStatusOverride(id));
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

  // Toggle the current member's private star on an applicant. Invokable from the
  // list, the ranking, or the detail header, so refresh whichever surfaces are live:
  // the detail from the response, and the list/ranking if they hold star state.
  async function toggleStar(id: number, starred: boolean) {
    const response = await api.setStar(id, starred);
    if (!response.ok) {
      showError(starred ? "Could not add to favourites." : "Could not remove from favourites.");
      return;
    }
    const payload: { application: ApplicationDetail } = await response.json();
    if (selectedApp?.id === id) setSelectedApp(payload.application);
    if (applications.some((a) => a.id === id)) reloadApplications();
    if (ranking) loadRanking();
  }

  const hasGoogleSheetLink = Boolean(saved && resolveSheetId(saved));
  const settingsLoadState = saved ? "ready" : settingsLoadFailed ? "error" : "loading";

  return (
    <main className="app-shell">
      <header className="topnav">
        <div className="topnav-inner">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">
              <HouseIcon size={30} />
            </span>
            <span className="brand-name">Penta Housing Co-Op</span>
          </div>
          {user ? (
            <div className="toolbar">
              <div className="user-chip">
                <span>{user.displayName}</span>
                <strong>{user.role}</strong>
              </div>
              <button className="icon-button" aria-label="Log out" title="Log out" onClick={logout}>
                <LogOut size={16} />
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <div className="page-heading">
        <h1>Penta Application Screener</h1>
      </div>

      {!user ? (
        <section className="login-panel">
          <span className="panel-kicker">Member access</span>
          <h2>{isLoadingUser ? "Checking session" : userLoadFailed ? "Couldn't verify your session" : "Sign in to continue"}</h2>
          {accessDenied && !isLoadingUser ? (
            <p className="login-denied" role="alert">
              That Google account isn't approved for this screener. Ask an admin to add your email,
              then sign in again.
            </p>
          ) : userLoadFailed ? (
            <p className="login-denied" role="alert">The server may have been starting up. Try checking your session again.</p>
          ) : null}
          <button className="primary-button" onClick={login} disabled={isLoadingUser}>
            <LogIn size={16} />
            <span>Sign in with Google</span>
          </button>
          {userLoadFailed ? (
            <button className="secondary-button" type="button" onClick={() => void loadCurrentUser()}>
              Retry
            </button>
          ) : null}
          <p className="login-legal">
            By signing in you agree to our{" "}
            <a href="https://www.pentacoop.com/terms.html" target="_blank" rel="noopener noreferrer">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="https://www.pentacoop.com/privacy.html" target="_blank" rel="noopener noreferrer">
              Privacy Policy
            </a>
            .
          </p>
        </section>
      ) : (
        <>
          {/* Global actions first (workflow acts on the whole dataset regardless of
              tab), then the tab row, then the active tab's content. */}
          <WorkflowBar
            workflow={workflow}
            coverage={coverage}
            dashboardCounts={dashboardCounts}
            loadState={dashboardLoadState}
            onRetryLoad={() => void loadInitialDashboard()}
            settingsLoadState={settingsLoadState}
            onRetrySettings={() => {
              setSettingsLoadFailed(false);
              void loadSettings();
            }}
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
            pendingProposals={rankingRun?.proposedDimensions ?? []}
            onRequestRank={requestRankEstimate}
            onRunRank={runRank}
            onCancelRank={dismissRankEstimate}
          />

          {/* Tab row: the data views on the left, the config tabs (Eligibility Settings
              and, for admins, Admin Settings) set apart on the right. */}
          <div className="view-tabs no-print" role="tablist" aria-label="Views">
            {tabButton("applications", "Applications")}
            {/* The Ranking tab only appears once a run exists. Clicking it loads/
                reconciles the ranking + tiers from the server (pure math, no cost). */}
            {rankingRun ? tabButton("ranking", "Ranking") : null}
            {/* The AI developer/operator surface, split by purpose: Observability (what the
                AI did + cost, per-run traces once a run exists) and Evals (invariants / live
                per-pass / judge — need no run, work before any Rank). Admin-only: a member
                sees only Applications, Ranking, and Eligibility Settings. */}
            {isAdmin ? tabButton("observability", "Observability") : null}
            {isAdmin ? tabButton("evals", "Evals") : null}
            {/* Config tabs, set apart on the right: Eligibility Settings (every member
                tunes their own screening rules) and Admin Settings (admin-only: data
                source, pets, AI knobs, and the access allowlist). */}
            {tabButton("eligibilitySettings", "Eligibility Settings", <Filter size={14} />, "tab-button-settings")}
            {isAdmin ? tabButton("adminSettings", "Admin Settings", <Settings size={14} />) : null}
          </div>

          <section className="panel">
            {selectedApp ? (
              <CandidateDetail
                app={selectedApp}
                onBack={backToList}
                onOverrideStatus={overrideStatus}
                onClearOverride={clearStatusOverride}
                onSavePrivateNote={savePrivateNote}
                onToggleStar={toggleStar}
              />
            ) : activeTab === "eligibilitySettings" ? (
              <EligibilitySettingsPanel onError={showError} onRulesUpdated={refreshEligibilityViews} />
            ) : activeTab === "adminSettings" && isAdmin ? (
              // Never fall through to the Applications view when the admin tab is selected but
              // settings haven't loaded — that silent mismatch (selected tab, wrong body) was a
              // real cold-start bug. Show the panel once `draft` is ready, else a loading/error
              // state that can retry the settings load in place.
              draft ? (
                <AdminSettingsPanel
                  draft={draft}
                  setDraft={setDraft}
                  saved={saved}
                  isSaving={isSavingSettings}
                  onSubmit={saveSettings}
                  onError={showError}
                  onSettingsUpdated={applyLinkedSheet}
                  onEligibilityChanged={refreshEligibilityViews}
                  onOpenApplicant={viewApplication}
                  onOpenView={navigateToView}
                />
              ) : (
                <div className="settings-load-state" role={settingsLoadFailed ? "alert" : "status"}>
                  {settingsLoadFailed ? (
                    <>
                      <p>Couldn't load settings. The server may have been starting up.</p>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setSettingsLoadFailed(false);
                          void loadSettings();
                        }}
                      >
                        Retry
                      </button>
                    </>
                  ) : (
                    <p>Loading settings…</p>
                  )}
                </div>
              )
            ) : activeTab === "ranking" && ranking ? (
              <RankingView
                ranking={ranking}
                rankingRun={rankingRun}
                tiers={tiers}
                proposedDimensions={rankingRun?.proposedDimensions ?? []}
                onSaveTiers={(next) => saveTiers(next)}
                onAcknowledgeNew={acknowledgeNewDimensions}
                onDismissRequested={dismissRequested}
                onAddProposal={addProposal}
                onRemoveProposal={removeProposal}
                onSelectApplication={viewApplication}
                onToggleStar={toggleStar}
              />
            ) : activeTab === "ranking" ? (
              <div className="list-load-state" role={rankingLoadState === "error" ? "alert" : "status"}>
                {rankingLoadState === "error" ? (
                  <>
                    <p>Couldn&apos;t load the ranking.</p>
                    <button type="button" className="secondary-button" onClick={() => void loadRanking()}>
                      Retry
                    </button>
                  </>
                ) : (
                  <p>Loading ranking…</p>
                )}
              </div>
            ) : activeTab === "observability" ? (
              <AIQualityView family="obs" run={rankingRun} onToast={showToast} onError={showError} />
            ) : activeTab === "evals" ? (
              <AIQualityView family="eval" run={rankingRun} onToast={showToast} onError={showError} />
            ) : (
              <ApplicationsList
                applications={applications}
                applicationsLoadState={applicationsLoadState}
                appFilter={appFilter}
                appFacets={appFacets}
                appSearch={appSearch}
                appSort={appSort}
                onApplyFilter={applyFilter}
                onSearch={searchApplications}
                onToggleSort={toggleSort}
                onSelectApplication={viewApplication}
                onToggleStar={toggleStar}
                onRetryLoad={() => void loadInitialApplications()}
              />
            )}
          </section>
        </>
      )}
      {/* The from-any-page feedback channel: only for a signed-in member, and never in
          print. Context rides along invisibly — the accurate view (an open candidate
          detail names itself, not the tab behind it) and, in that detail, which applicant. */}
      {user ? (
        <FeedbackButton
          activeTab={selectedApp ? "applicant-detail" : activeTab}
          analysisId={rankingRun?.analysisId ?? null}
          applicantId={selectedApp?.id ?? null}
          onToast={showToast}
          onError={showError}
        />
      ) : null}
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </main>
  );
}
