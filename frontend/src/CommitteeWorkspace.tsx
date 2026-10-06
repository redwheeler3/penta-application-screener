import { Filter, Settings } from "lucide-react";
import {
  lazy,
  type ReactNode,
  Suspense,
  type SyntheticEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { BrandLockup } from "./components/shared/BrandLockup";
import { HeaderAccount } from "./components/shared/HeaderAccount";
import type {
  CurrentUser, ViewTab,
} from "./types";
import { AdminSettingsPanel, type AdminSubtab } from "./components/admin/AdminSettingsPanel";
import { AdminActionBanner } from "./components/admin/AdminActionBanner";
import { EligibilitySettingsView } from "./components/admin/EligibilitySettingsView";
import { ApplicationsList } from "./components/applications/ApplicationsList";
import { CandidateDetail } from "./components/applications/CandidateDetail";
import { RankingView } from "./components/ranking/RankingView";
import { FeedbackButton } from "./components/shared/FeedbackButton";
import { Toasts } from "./components/shared/Toasts";
import { WorkflowBar } from "./components/workflow/WorkflowBar";
import { useApplications } from "./hooks/useApplications";
import { useCandidateActions } from "./hooks/useCandidateActions";
import { usePrivateNotes } from "./hooks/usePrivateNotes";
import { useRanking } from "./hooks/useRanking";
import { useToasts } from "./hooks/useToasts";
import { useSharedSettings } from "./hooks/useSharedSettings";
import { useDashboard } from "./hooks/useDashboard";
import { useNavigation } from "./hooks/useNavigation";
import { useAiRuns } from "./hooks/useAiRuns";
import { useCachedResults } from "./hooks/useCachedResults";

const AIWorkspaceView = lazy(() =>
  import("./components/ai/AIWorkspaceView").then((module) => ({ default: module.AIWorkspaceView })),
);

const aiQualityLoading = (
  <div className="observability-view">
    <p className="panel-hint">Loading…</p>
  </div>
);

/** Own all committee data and pending work for one authenticated account. */
export function CommitteeWorkspace({ user, logout, sessionChanged = false, onContinueSession }: {
  user: CurrentUser;
  logout: () => Promise<string | null>;
  sessionChanged?: boolean;
  onContinueSession?: () => Promise<boolean>;
}) {
  const isAdmin = user.role === "admin";
  const [noteCopyMessage, setNoteCopyMessage] = useState("");
  const { toasts, showToast, showError, showWarning, dismissToast } = useToasts();

  async function signOut(): Promise<void> {
    if (privateNotes.hasUnconfirmed() && !window.confirm("Some private notes have not been saved. Sign out and discard those drafts?")) return;
    privateNotes.suspendWrites();
    const error = await logout();
    if (error) {
      privateNotes.resumeWrites();
      showError(error);
    }
  }

  // The applications-list view state (full pool + client-derived filter/sort/facets).
  // See useApplications; the selected candidate detail stays here (cross-cutting).
  const {
    applications,
    openings,
    selectedOpeningId,
    applicationsLoadState,
    appFilter,
    appFacets,
    appSearch,
    appSort,
    reloadApplications,
    loadInitialApplications,
    toggleSort,
    applyFilter,
    selectOpening,
    search: searchApplications,
  } = useApplications();
  // The ranking cluster: the current run's dimensions, the ranked shortlist, the
  // committee's tiers, and the pure-persistence handlers that keep them in lockstep.
  // See useRanking. useAiRuns separately coordinates the model-run lifecycle.
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
    invalidateReads,
    staleAnalysis,
    refreshRankingView,
    reloadStaleRanking,
    observeCurrentAnalysis,
  } = useRanking(selectedOpeningId, showError);
  const {
    workflow,
    coverage,
    adminActions,
    loadState: dashboardLoadState,
    refresh: refreshDashboard,
    loadInitial: loadInitialDashboard,
  } = useDashboard(selectedOpeningId, (analysisId) => {
    if (!intakeViews.current.running) observeCurrentAnalysis(analysisId);
  });


  const {
    activeTab,
    selectedApplication: selectedApp,
    selectedApplicationReadOnly,
    clearSelectedApplication,
    updateSelectedApplication,
    viewApplication,
    viewRetainedApplication,
    changeOpening,
    onOpeningRankingLoaded,
    backToList,
    navigateToView,
  } = useNavigation({ openingId: selectedOpeningId, selectOpening, loadRanking, onError: showError });
  const [adminSubtab, setAdminSubtab] = useState<AdminSubtab>("configuration");
  const {
    draft,
    setDraft,
    saved,
    isSaving: isSavingSettings,
    loadFailed: settingsLoadFailed,
    load: loadSettings,
    retry: retrySettings,
    save: saveSettingsDraft,
  } = useSharedSettings({
    dashboardReady: dashboardLoadState === "ready",
  });

  const {
    screeningEstimate,
    screeningEstimateLoading,
    screeningRunning,
    screeningProgress,
    rankEstimate,
    rankEstimateLoading,
    scoreCurrentEstimate,
    rankRunning,
    rankProgress,
    rankThinking,
    rankRefreshing,
    requestScreeningEstimate,
    runScreening,
    cancelScreeningEstimate,
    requestRankEstimate,
    runRank,
    cancelRankEstimate,
    resetEstimates,
  } = useAiRuns({
    openingId: selectedOpeningId,
    ranking: {
      currentRun: rankingRun,
      load: loadRanking,
      setDisplayedProposals,
      invalidateReads,
    },
    notifications: { success: showToast, error: showError, warning: showWarning },
    refreshDashboard,
    reloadApplications,
    clearSelectedApplication,
    refreshDisplayedRanking: () => {
      const views = intakeViews.current;
      if (views.displayed) void views.refreshRankingView();
    },
  });

  const {
    overrideStatus,
    clearStatusOverride,
    addCommitteeNote,
    updateCommitteeNote,
    deleteCommitteeNote,
    toggleStar,
    toggleShortlist,
    refreshEligibilityViews,
  } = useCandidateActions({
    openingId: selectedOpeningId,
    rankingLoaded: ranking !== null,
    onApplicationUpdated: updateSelectedApplication,
    onError: showError,
    refreshDashboard,
    reloadApplications,
    loadRanking,
  });

  const refreshCachedResults = useCachedResults(selectedOpeningId,
    sessionChanged || rankRunning || rankRefreshing || screeningRunning, refreshEligibilityViews);

  const privateNotes = usePrivateNotes({
    onSaved: (id, privateNote) => updateSelectedApplication({ id, privateNote }),
    onError: showError,
  });
  const suspendPrivateWrites = privateNotes.suspendWrites;
  useEffect(() => { if (sessionChanged) suspendPrivateWrites(); }, [sessionChanged, suspendPrivateWrites]);
  async function continueSession() {
    if (privateNotes.hasUnconfirmed() && !window.confirm("Continue with the current session and discard unsaved private notes from this account?")) return;
    if (!(await onContinueSession?.())) {
      setNoteCopyMessage("Couldn't refresh your session. Your drafts are still here. Please try again.");
    }
  }
  async function copyUnsavedNotes() {
    try {
      await navigator.clipboard.writeText(privateNotes.unsavedText());
      setNoteCopyMessage("Copied. Paste your notes somewhere safe before continuing.");
    } catch { setNoteCopyMessage("Could not copy notes. Your drafts are still available in this session."); }
  }


  useEffect(() => {
    void loadSettings();
    void loadInitialApplications();
    // The account-keyed workspace owns these initial reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedOpeningId === null) return;
    let active = true;
    resetEstimates();
    void loadInitialDashboard();
    void (async () => {
      const run = await refreshRankingRun();
      if (active && run.status === "loaded") {
        onOpeningRankingLoaded(selectedOpeningId, run.run !== null);
      }
    })();
    return () => { active = false; };
    // Navigation owns detail disposal/restoration. Other member surfaces are opening-scoped.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOpeningId]);

  // One owner refreshes intake and the displayed board. Refs keep the interval steady
  // while renders update callbacks, navigation and live-run ownership.
  const intakeViews = useRef({ refreshDashboard, reloadApplications, refreshCachedResults, refreshRankingView,
    displayed: activeTab === "ranking" && selectedApp === null,
    running: rankRunning || rankRefreshing || screeningRunning });
  intakeViews.current = { refreshDashboard, reloadApplications, refreshCachedResults, refreshRankingView,
    displayed: activeTab === "ranking" && selectedApp === null,
    running: rankRunning || rankRefreshing || screeningRunning };
  useEffect(() => {
    if (sessionChanged) return;
    let refreshInFlight = false;
    const refreshIntake = () => {
      if (document.visibilityState !== "visible" || refreshInFlight) return;
      const views = intakeViews.current;
      refreshInFlight = true;
      const reads = [views.refreshDashboard(), views.reloadApplications(), views.refreshCachedResults()];
      if (!views.running && views.displayed) {
        reads.push(views.refreshRankingView());
      }
      void Promise.all(reads).finally(() => { refreshInFlight = false; });
    };
    const onFocus = refreshIntake;
    const interval = window.setInterval(() => refreshIntake(), 60_000);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [sessionChanged, selectedOpeningId]);

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

  async function saveSettings(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await saveSettingsDraft()) {
      // Cost estimates are a snapshot of the saved AI settings. Invalidate them so
      // a cap increase (or any model/cost setting change) cannot leave a stale
      // over-cap warning and disabled confirmation button on screen.
      resetEstimates();
      clearSelectedApplication();
      void refreshDashboard();
      void reloadApplications();
      void refreshCachedResults();
      requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    } else {
      showError("Settings could not be saved.");
    }
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
        className={`tab-button${icon ? " tab-button-icon" : ""}${extraClass ? ` ${extraClass}` : ""}${active ? " active" : ""}`}
        onClick={() => navigateToView(tab)}
      >
        {icon}
        {icon ? <span>{label}</span> : label}
      </button>
    );
  }

  const selectedOpening = openings.find((opening) => opening.id === selectedOpeningId) ?? null;
  const aiActionsDisabled = Boolean(
    selectedOpening?.phase === "archived",
  );

  return (
    <>
    {sessionChanged ? <section className="app-shell" role="alert">
      <div className="email-delay-notice"><div>
        <strong>Your session changed.</strong>
        <p>This page belongs to {user.email}. Actions are paused. Copy any unsaved private notes before continuing.</p>
        {privateNotes.hasUnconfirmed() ? <button type="button" onClick={() => void copyUnsavedNotes()}>Copy unsaved private notes</button> : null}
        <button type="button" onClick={() => void continueSession()}>Continue with current session</button>
        {noteCopyMessage ? <p role="status">{noteCopyMessage}</p> : null}
      </div></div>
    </section> : null}
    <main className="app-shell" inert={sessionChanged}>
      <header className="topnav">
        <div className="topnav-inner penta-header-inner">
          <BrandLockup />
          <HeaderAccount email={user.email} role={user.role} onSignOut={() => void signOut()} />
        </div>
      </header>

      <div className="page-heading">
        <h1>Penta Application Screener</h1>
      </div>

      {isAdmin ? (
        <AdminActionBanner
          actions={adminActions}
            onReviewOpenings={() => {
              setAdminSubtab("openings");
              navigateToView("adminSettings");
            }}
            onReviewEmailDelivery={() => {
              setAdminSubtab("emailDelivery");
              navigateToView("adminSettings");
            }}
        />
      ) : null}
      {/* Global actions first (workflow acts on the whole dataset regardless of
          tab), then the tab row, then the active tab's content. */}
      <WorkflowBar
        workflow={workflow}
        coverage={coverage}
        loadState={dashboardLoadState}
        onRetryLoad={() => void loadInitialDashboard()}
        screeningRunning={screeningRunning}
        screeningEstimate={screeningEstimate}
        screeningEstimateLoading={screeningEstimateLoading}
        screeningProgress={screeningProgress}
        onRequestScreening={requestScreeningEstimate}
        onRunScreening={runScreening}
        onCancelScreening={cancelScreeningEstimate}
        rankRunning={rankRunning}
        rankEstimate={rankEstimate}
        rankEstimateLoading={rankEstimateLoading}
        scoreCurrentEstimate={scoreCurrentEstimate}
        hasCurrentCriteria={rankingRun !== null}
        rankProgress={rankProgress}
        rankThinking={rankThinking}
        pendingProposals={rankingRun?.proposedDimensions ?? []}
        onRequestRank={requestRankEstimate}
        onRunRank={runRank}
        onCancelRank={cancelRankEstimate}
        openings={openings}
        selectedOpeningId={selectedOpeningId}
        onOpeningChange={(openingId) => void changeOpening(openingId)}
        aiActionsDisabled={aiActionsDisabled}
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
            tunes their own screening rules) and Admin Settings (global configuration,
            openings, notifications, delivery, feedback, and committee access). */}
        {tabButton("eligibilitySettings", "Eligibility Settings", <Filter size={14} />, "tab-button-settings")}
        {isAdmin ? tabButton("adminSettings", "Admin Settings", <Settings size={14} />) : null}
      </div>

      <section className="panel">
        {selectedApp ? (
          <CandidateDetail
            app={selectedApp}
            openings={openings}
            onBack={backToList}
            onOverrideStatus={overrideStatus}
            onClearOverride={clearStatusOverride}
            privateNoteEditor={selectedApplicationReadOnly || selectedOpeningId === null
              ? null : privateNotes.editor(selectedApp.id, selectedOpeningId, selectedApp.privateNote)}
            onAddCommitteeNote={addCommitteeNote}
            onUpdateCommitteeNote={updateCommitteeNote}
            onDeleteCommitteeNote={deleteCommitteeNote}
            onToggleStar={toggleStar}
            onToggleShortlist={toggleShortlist}
            readOnly={selectedApplicationReadOnly}
          />
        ) : activeTab === "eligibilitySettings" ? (
          selectedOpeningId === null ? (
            <p className="panel-hint">No retained opening is available.</p>
          ) : (
            <EligibilitySettingsView
              openingId={selectedOpeningId}
              isAdmin={isAdmin}
              onError={showError}
              onRulesUpdated={refreshEligibilityViews}
            />
          )
        ) : activeTab === "adminSettings" && isAdmin ? (
          <AdminSettingsPanel
            draft={draft}
            setDraft={setDraft}
            saved={saved}
            isSaving={isSavingSettings}
            onSubmit={saveSettings}
            configurationLoadFailed={settingsLoadFailed}
            onRetryConfiguration={retrySettings}
            onError={showError}
            onOpenApplicant={viewApplication}
            onOpenOpeningApplicant={viewApplication}
            onOpenView={navigateToView}
            currentUser={user}
            subtab={adminSubtab}
            onSubtabChange={setAdminSubtab}
            onPoolChanged={refreshEligibilityViews}
            onOpenRetainedApplicant={viewRetainedApplication}
          />
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
            onToggleShortlist={toggleShortlist}
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
        ) : activeTab === "observability" || activeTab === "evals" ? (
          <Suspense fallback={aiQualityLoading}>
            <AIWorkspaceView
              family={activeTab === "observability" ? "obs" : "eval"}
              refreshKey={workflow}
              run={rankingRun}
              openingId={selectedOpeningId}
              onToast={showToast}
              onError={showError}
            />
          </Suspense>
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
            onToggleShortlist={toggleShortlist}
            onRetryLoad={() => void loadInitialApplications()}
          />
        )}
      </section>
      {/* Feedback carries the visible view and applicant context and is hidden in print. */}
      <FeedbackButton
        activeTab={selectedApp ? "applicant-detail" : activeTab}
        analysisId={rankingRun?.analysisId ?? null}
        applicantId={selectedApp?.id ?? null}
        onToast={showToast}
        onError={showError}
      />
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </main>
    </>
  );
}
