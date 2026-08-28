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
import * as api from "./api/applications";
import type { AuthRedirect } from "./authRedirect";
import type {
  ApplicationDetail,
  AppStatus,
  ViewTab,
} from "./types";
import { AdminSettingsPanel, type AdminSubtab } from "./components/admin/AdminSettingsPanel";
import { AdminActionBanner } from "./components/admin/AdminActionBanner";
import { EligibilitySettingsPanel } from "./components/admin/EligibilitySettingsPanel";
import { ApplicationsList } from "./components/applications/ApplicationsList";
import { CandidateDetail } from "./components/applications/CandidateDetail";
import { CommitteeSignIn } from "./components/auth/CommitteeSignIn";
import { RankingView } from "./components/ranking/RankingView";
import { FeedbackButton } from "./components/shared/FeedbackButton";
import { Toasts } from "./components/shared/Toasts";
import { WorkflowBar } from "./components/workflow/WorkflowBar";
import { useApplications } from "./hooks/useApplications";
import { useRanking } from "./hooks/useRanking";
import { useToasts } from "./hooks/useToasts";
import { useSession } from "./hooks/useSession";
import { useSharedSettings } from "./hooks/useSharedSettings";
import { useDashboard } from "./hooks/useDashboard";
import { useNavigation } from "./hooks/useNavigation";
import { useAiRuns } from "./hooks/useAiRuns";

const AIQualityView = lazy(() =>
  import("./components/observability/AIQualityView").then((module) => ({ default: module.AIQualityView })),
);

const aiQualityLoading = (
  <div className="observability-view">
    <p className="panel-hint">Loading…</p>
  </div>
);

export function App(props: { authRedirect: AuthRedirect }) {
  const {
    user,
    emailSignInEnabled,
    linkConflict,
    linkedEmail,
    isAdmin,
    isLoadingUser,
    userLoadRecovery,
    signInState,
    requestMagicLink,
    keepCurrentSession,
    openLinkedSession,
    emailNewLinkedSession,
    resetSignIn,
    logout,
  } = useSession(props.authRedirect);

  const {
    workflow,
    coverage,
    adminActions,
    loadState: dashboardLoadState,
    refresh: refreshDashboard,
    loadInitial: loadInitialDashboard,
  } = useDashboard();

  // Workflow notifications surface as bottom-right toasts (success auto-dismisses;
  // errors/warnings persist until dismissed). See useToasts.
  const { toasts, showToast, showError, showWarning, dismissToast } = useToasts();

  // The applications-list view state (full pool + client-derived filter/sort/facets).
  // See useApplications; the selected candidate detail stays here (cross-cutting).
  const {
    applications,
    openings,
    selectedOpeningIds,
    applicationIdsInOpeningScope,
    applicationsLoadState,
    appFilter,
    appFacets,
    appSearch,
    appSort,
    reloadApplications,
    loadInitialApplications,
    toggleSort,
    applyFilter,
    setSelectedOpeningIds,
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
    staleAnalysis,
    checkForStaleRanking,
    reloadStaleRanking,
  } = useRanking(showError);

  const {
    activeTab,
    selectedApplication: selectedApp,
    selectedApplicationReadOnly,
    setSelectedApplication: setSelectedApp,
    viewApplication,
    viewRetainedApplication,
    backToList,
    navigateToView,
  } = useNavigation({ loadRanking, onError: showError });
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
    criteriaThinking,
    requestScreeningEstimate,
    runScreening,
    cancelScreeningEstimate,
    requestRankEstimate,
    runRank,
    cancelRankEstimate,
    resetEstimates,
  } = useAiRuns({
    ranking: {
      currentRun: rankingRun,
      refreshCurrentRun: refreshRankingRun,
      load: loadRanking,
      setDisplayedProposals,
    },
    notifications: { success: showToast, error: showError, warning: showWarning },
    refreshDashboard,
    reloadApplications,
    clearSelectedApplication: () => setSelectedApp(null),
  });

  useEffect(() => {
    if (!user) return;
    void loadSettings();
    void loadInitialDashboard();
    refreshRankingRun();
    void loadInitialApplications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // Refresh the lightweight list/dashboard reads while this page is visible and whenever
  // the member returns to it, so new or edited applications appear without a reload.
  useEffect(() => {
    if (!user) return;
    let refreshInFlight = false;
    const refreshIntake = () => {
      if (document.visibilityState !== "visible" || refreshInFlight) return;
      refreshInFlight = true;
      void Promise.all([refreshDashboard(), reloadApplications()]).finally(() => {
        refreshInFlight = false;
      });
    };
    const interval = window.setInterval(refreshIntake, 60_000);
    window.addEventListener("focus", refreshIntake);
    document.addEventListener("visibilitychange", refreshIntake);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshIntake);
      document.removeEventListener("visibilitychange", refreshIntake);
    };
  }, [user, refreshDashboard, reloadApplications]);

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

  // Eligibility is computed from the current member's rules and overrides whenever a view is
  // read. Every mutation therefore needs to refresh each surface that presents that derived
  // status: the workflow bar, application rows/facets, and an already-open ranked shortlist.
  function refreshEligibilityViews() {
    refreshDashboard();
    reloadApplications();
    if (ranking) void loadRanking();
  }

  async function saveSettings(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await saveSettingsDraft()) {
      // Cost estimates are a snapshot of the saved AI settings. Invalidate them so
      // a cap increase (or any model/cost setting change) cannot leave a stale
      // over-cap warning and disabled confirmation button on screen.
      resetEstimates();
      setSelectedApp(null);
      refreshDashboard();
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


  return (
    <main className="app-shell">
      <header className="topnav">
        <div className="topnav-inner penta-header-inner">
          <BrandLockup />
          {user ? (
            <HeaderAccount email={user.email} role={user.role} onSignOut={logout} />
          ) : null}
        </div>
      </header>

      <div className="page-heading">
        <h1>Penta Application Screener</h1>
      </div>

      {!user || linkConflict ? (
        <CommitteeSignIn
          emailSignInEnabled={emailSignInEnabled}
          isLoadingUser={isLoadingUser}
          userLoadRecovery={userLoadRecovery}
          signInState={signInState}
          linkConflict={linkConflict}
          linkedEmail={linkedEmail}
          onRequestLink={requestMagicLink}
          onKeepCurrent={keepCurrentSession}
          onOpenLinked={openLinkedSession}
          onEmailNew={emailNewLinkedSession}
          onReset={resetSignIn}
        />
      ) : (
        <>
          {isAdmin ? (
            <AdminActionBanner
              actions={adminActions}
              onReviewOpenings={() => {
                setAdminSubtab("openings");
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
            criteriaThinking={criteriaThinking}
            pendingProposals={rankingRun?.proposedDimensions ?? []}
            onRequestRank={requestRankEstimate}
            onRunRank={runRank}
            onCancelRank={cancelRankEstimate}
            openings={openings}
            selectedOpeningIds={selectedOpeningIds}
            onOpeningScopeChange={setSelectedOpeningIds}
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
                openings={openings}
                onBack={backToList}
                onOverrideStatus={overrideStatus}
                onClearOverride={clearStatusOverride}
                onSavePrivateNote={savePrivateNote}
                onToggleStar={toggleStar}
                readOnly={selectedApplicationReadOnly}
              />
            ) : activeTab === "eligibilitySettings" ? (
              <EligibilitySettingsPanel onError={showError} onRulesUpdated={refreshEligibilityViews} />
            ) : activeTab === "adminSettings" && isAdmin ? (
              // Keep the selected admin tab visible while settings load or fail.
              draft ? (
                <AdminSettingsPanel
                  draft={draft}
                  setDraft={setDraft}
                  saved={saved}
                  isSaving={isSavingSettings}
                  onSubmit={saveSettings}
                  onError={showError}
                  onEligibilityChanged={refreshEligibilityViews}
                  onOpenApplicant={viewApplication}
                  onOpenView={navigateToView}
                  currentUser={user}
                  subtab={adminSubtab}
                  onSubtabChange={setAdminSubtab}
                  onPoolChanged={refreshEligibilityViews}
                  onOpenRetainedApplicant={viewRetainedApplication}
                />
              ) : (
                <div className="settings-load-state" role={settingsLoadFailed ? "alert" : "status"}>
                  {settingsLoadFailed ? (
                    <>
                      <p>Couldn't load settings. The server may have been starting up.</p>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={retrySettings}
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
                applicationIdsInOpeningScope={
                  selectedOpeningIds.length > 0 ? applicationIdsInOpeningScope : null
                }
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
                <AIQualityView
                  family={activeTab === "observability" ? "obs" : "eval"}
                  run={rankingRun}
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
