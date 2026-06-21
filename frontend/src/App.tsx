import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clipboard, LogIn, LogOut, RefreshCw, Sparkles, X } from "lucide-react";
import { type ReactNode, type SyntheticEvent, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { HouseIcon } from "./HouseIcon";

type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

// Mirrors the backend AISettings. The UI only edits spending_cap_usd; the other
// fields are infra/tuning config that we still round-trip so a save never resets
// them to defaults.
type AISettings = {
  region: string;
  first_pass_model: string;
  synthesis_model: string;
  spending_cap_usd: number;
  max_workers: number;
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
  ai: AISettings;
};

type SettingsResponse = {
  settings: AppSettings;
  google_sheet_url: string;
  google_sheet_title: string | null;
};

type AppStatus = "eligible" | "ineligible";
type StatusSource = "untouched" | "rules" | "ai" | "human";

// Counts keyed by the real columns; named views (e.g. "Needs review" = source
// "ai") are composed here in the client, not by the backend.
type DashboardCounts = {
  submitted: number;
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

// Which screening steps have run, from the backend (persisted), so the ordered
// workflow gating survives a page reload.
type WorkflowState = {
  synced: boolean;
  qualityChecksRun: boolean;
  essaysAnalyzed: boolean;
};

// Faceted counts from the list response: each facet reflects the other group's
// active filter, so option counts stay consistent across the two filter groups.
type AppFacets = {
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

type ApplicationSummary = {
  id: number;
  primaryEmail: string;
  applicantName: string | null;
  coApplicantName: string | null;
  status: AppStatus;
  statusSource: StatusSource;
  // True when machine findings changed since a human last reviewed.
  stale: boolean;
  hardFilterReasons: Array<{ code: string; message: string; details: Record<string, unknown> }>;
  childCount: number | null;
  householdIncome: number | null;
  // null = AI quality-flag pass not run; int = flag count (0 = ran clean).
  flagCount: number | null;
  // Distinct flag categories from the latest pass (null if not run).
  flagCategories: string[] | null;
  createdAt: string | null;
};

type Essay = {
  label: string;
  question: string;
  answer: string;
};

type QualityFlag = {
  category: string;
  severity: "info" | "notable";
  summary: string;
  evidence: string;
};

// Neutral factual extraction across the four essays (milestone 6). Mirrors the
// backend EssayAnalysisReport. Informational only — never affects status.
type EssayAnalysis = {
  summary: string;
  household_context: string | null;
  employment_background: string | null;
  interests: string[];
  values: string[];
  skills_offered: string[];
  prior_co_op_experience: string | null;
  stated_motivations: string[];
  stated_contributions: string[];
  evidence: string[];
};

type ApplicationDetail = ApplicationSummary & {
  normalized: Record<string, unknown>;
  essays: Essay[];
  // null = quality-flag pass not yet run for this application; [] = ran, clean.
  qualityFlags: QualityFlag[] | null;
  rawRow?: Record<string, unknown>;
  // The model's free-text reasoning from the latest quality-flag pass.
  aiNarrative?: string | null;
  // null = essay-analysis pass not yet run for this application.
  essayAnalysis?: EssayAnalysis | null;
  // The model's free-text reasoning from the latest essay-analysis pass.
  essayAnalysisNarrative?: string | null;
};

type QualityFlagEstimate = {
  total: number;
  to_analyze: number;
  cached: number;
  estimated_usd: number;
  cap_usd: number;
  within_cap: boolean;
};

type SortKey = "applicant" | "co_applicant" | "children" | "income" | "status";
type SortState = { key: SortKey; direction: "asc" | "desc" } | null;

// Committee-facing labels for the normalized field keys. Keys not listed here
// fall back to a title-cased version of the raw key.
const FIELD_LABELS: Record<string, string> = {
  applicant_name: "Applicant name",
  co_applicant_name: "Co-applicant name",
  applicant_age: "Applicant age",
  co_applicant_age: "Co-applicant age",
  adult_count: "Adults",
  child_count: "Number of children",
  child_details: "Children",
  household_income: "Household income",
  applicant_income: "Applicant income",
  co_applicant_income: "Co-applicant income",
  has_real_estate: "Owns real estate",
  pets_text: "Pets",
  co_applicant_phone: "Co-applicant phone",
  co_applicant_email: "Co-applicant email",
  applicant_email: "Applicant email",
  form_submission_email: "Form submission email",
  applicant_employment_start: "Applicant employment start",
  co_applicant_employment_start: "Co-applicant employment start",
};

// Normalized fields that should render as currency.
const MONEY_FIELDS = new Set(["household_income", "applicant_income", "co_applicant_income"]);

// Human-readable labels for AI quality-flag categories.
const FLAG_CATEGORY_LABELS: Record<string, string> = {
  placeholder_name: "Placeholder name",
  suspicious_name: "Suspicious name",
  minimal_essay: "Minimal essay",
  spam_essay: "Spam essay",
  ai_generated_essay: "AI-generated essay",
  duplicated_answers: "Duplicated answers",
  internal_inconsistency: "Internal inconsistency",
  fake_contact: "Suspicious contact info",
  pet_policy: "Pet policy",
  other: "Other",
};

// Maps a filter reason code to the normalized field(s) that caused it, so the
// detail view can highlight the offending value next to the reason.
const REASON_FIELDS: Record<string, string[]> = {
  income_below_range: ["household_income"],
  income_above_range: ["household_income"],
  income_arithmetic_mismatch: ["household_income", "applicant_income", "co_applicant_income"],
  owns_real_estate: ["has_real_estate"],
  applicant_under_19: ["applicant_age"],
  co_applicant_under_19: ["co_applicant_age"],
  child_count_mismatch: ["child_count", "child_details"],
  child_age_over_18: ["child_details"],
  child_age_exceeds_parent: ["child_details", "applicant_age", "co_applicant_age"],
  co_applicant_incomplete: ["co_applicant_name", "co_applicant_age", "co_applicant_phone", "co_applicant_email"],
  future_employment_start: ["applicant_employment_start", "co_applicant_employment_start"],
};

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Status and "who set it" are independent axes, shown as separate columns.
const STATUS_LABELS: Record<AppStatus, string> = {
  eligible: "Eligible",
  ineligible: "Ineligible",
};

// Short label for the "Decided by" column. "untouched" means no actor changed
// the status, so it shows nothing.
const SOURCE_LABELS: Record<StatusSource, string> = {
  untouched: "—",
  rules: "Rules",
  ai: "AI",
  human: "Reviewer",
};

// Longer, non-prescriptive sentence for the candidate detail page.
const SOURCE_DESCRIPTIONS: Record<StatusSource, string> = {
  untouched: "Passed the deterministic rules; the AI pass raised no flags.",
  rules: "Set ineligible by the deterministic screening rules.",
  ai: "Flagged by the AI quality pass.",
  human: "Set by a reviewer.",
};

function flagCategoryLabel(category: string): string {
  return FLAG_CATEGORY_LABELS[category] ?? category;
}

// Percent complete (0–100) for a quality-flag run, used for both the label text
// and the progress-bar width so the two never drift apart.
function qfPercent(progress: { processed: number; total: number }): number {
  return (progress.processed / progress.total) * 100;
}

// Render one essay-analysis prose field as a dt/dd row, omitted when the model
// captured nothing for it (null = "applicant did not address this").
function renderEssayText(label: string, value: string | null): ReactNode {
  if (!value) return null;
  return (
    <div className="essay-analysis-field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// Render one essay-analysis list field as chips, omitted when empty.
function renderEssayChips(label: string, values: string[]): ReactNode {
  if (!values || values.length === 0) return null;
  return (
    <div className="essay-analysis-field">
      <dt>{label}</dt>
      <dd className="essay-analysis-chips">
        {values.map((value, i) => (
          <span key={i} className="essay-analysis-chip">
            {value}
          </span>
        ))}
      </dd>
    </div>
  );
}

// One numbered step in the ordered screening workflow strip. Renders the step
// button plus a chevron connector to the next step (omitted on the last).
function WorkflowStep(props: {
  n: number;
  title: string;
  icon: ReactNode;
  done: boolean;
  busy: boolean;
  busyLabel: string;
  disabled: boolean;
  onClick: () => void;
  last?: boolean;
}): ReactNode {
  const { n, title, icon, done, busy, busyLabel, disabled, onClick, last } = props;
  return (
    <li className="workflow-step">
      <button
        type="button"
        className={`workflow-step-button${done ? " is-done" : ""}${busy ? " is-busy" : ""}`}
        onClick={onClick}
        disabled={disabled}
      >
        <span className="workflow-step-badge">
          {done ? <Check size={14} /> : n}
        </span>
        {icon}
        <span>{busy ? busyLabel : title}</span>
      </button>
      {!last ? <ChevronRight className="workflow-step-arrow" size={18} /> : null}
    </li>
  );
}

// The configured sheet id from a server response: prefer the resolved URL, falling
// back to the bare id. Returns "" when no sheet is configured.
function resolveSheetId(payload: SettingsResponse): string {
  return payload.google_sheet_url || payload.settings.google_sheet_id;
}

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
  ai: {
    region: "us-west-2",
    first_pass_model: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    synthesis_model: "us.anthropic.claude-sonnet-4-6",
    spending_cap_usd: 0.5,
    max_workers: 50,
  },
};

const ALL_RULES = [
  { id: "applicant_under_19", label: "Applicant under 19" },
  { id: "child_age_over_18", label: "Child age 18+" },
  { id: "child_count_mismatch", label: "Child count mismatch" },
  { id: "co_applicant_incomplete", label: "Co-applicant incomplete" },
  { id: "co_applicant_under_19", label: "Co-applicant under 19" },
  { id: "future_employment_start", label: "Future employment start" },
  { id: "income_above_range", label: "Income above range" },
  { id: "income_arithmetic_mismatch", label: "Income arithmetic mismatch" },
  { id: "income_below_range", label: "Income below range" },
  { id: "negative_number", label: "Negative number" },
  { id: "owns_real_estate", label: "Real estate ownership" },
  { id: "child_age_exceeds_parent", label: "Child age exceeds parent" },
] as const;

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  // The form draft the user edits. Kept separate from `saved` so typing never
  // affects affordances that must gate on persisted state (Sync button, the setup
  // callout, panel collapse) until the change is actually saved to the server.
  const [draft, setDraft] = useState<AppSettings>(defaultSettings);
  // The last settings persisted on the server — the single source of truth for what
  // is actually configured. `draft` is reset to this on load and after each save.
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSettingsExpanded, setIsSettingsExpanded] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>({
    submitted: 0,
    status: { eligible: 0, ineligible: 0 },
    source: { untouched: 0, rules: 0, ai: 0, human: 0 },
  });
  const [workflow, setWorkflow] = useState<WorkflowState>({
    synced: false,
    qualityChecksRun: false,
    essaysAnalyzed: false,
  });
  const [syncMessage, setSyncMessage] = useState("");
  const [syncError, setSyncError] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    if (syncMessage) {
      const timer = setTimeout(() => setSyncMessage(""), 4000);
      return () => clearTimeout(timer);
    }
  }, [syncMessage]);
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [appTotal, setAppTotal] = useState(0);
  const [appPage, setAppPage] = useState(1);
  const [appPageSize, setAppPageSize] = useState(25);
  // Filter mirrors the real columns. A tab sets one of these (or neither for All).
  const [appFilter, setAppFilter] = useState<{ status?: AppStatus; status_source?: StatusSource }>({});
  // Faceted option counts from the latest list response (reflect the cross-group filter).
  const [appFacets, setAppFacets] = useState<AppFacets | null>(null);
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);
  const [selectedApp, setSelectedApp] = useState<ApplicationDetail | null>(null);

  // AI quality-flag run flow: estimate (shown for confirmation) -> running -> message.
  const [qfEstimate, setQfEstimate] = useState<QualityFlagEstimate | null>(null);
  const [qfRunning, setQfRunning] = useState(false);
  const [qfMessage, setQfMessage] = useState("");
  // Live progress while the run streams: processed/total applications.
  const [qfProgress, setQfProgress] = useState<{ processed: number; total: number } | null>(null);

  // Essay-analysis run flow, mirroring the quality-flag flow above. Same
  // estimate-confirm-stream shape; informational pass (no flagged count).
  const [eaEstimate, setEaEstimate] = useState<QualityFlagEstimate | null>(null);
  const [eaRunning, setEaRunning] = useState(false);
  const [eaMessage, setEaMessage] = useState("");
  const [eaProgress, setEaProgress] = useState<{ processed: number; total: number } | null>(null);


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
    fetchApplications({}, 1, "");
  }, [user]);

  function applySettingsResponse(payload: SettingsResponse) {
    const sheetId = resolveSheetId(payload);
    setSaved(payload);
    setDraft({
      ...payload.settings,
      google_sheet_id: sheetId,
    });
    // First-run setup: open the form when there's no sheet configured yet.
    if (!sheetId) {
      setIsSettingsExpanded(true);
    }
  }

  function refreshDashboard() {
    fetch(`${apiBaseUrl}/dashboard`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { counts: DashboardCounts; workflow: WorkflowState }) => {
        setDashboardCounts(payload.counts);
        setWorkflow(payload.workflow);
      });
  }

  function fetchApplications(
    filter: { status?: AppStatus; status_source?: StatusSource } = appFilter,
    page: number = 1,
    search: string = appSearch,
    pageSize: number = appPageSize,
    sort: SortState = appSort,
  ) {
    const params = new URLSearchParams();
    if (filter.status) params.set("status", filter.status);
    if (filter.status_source) params.set("status_source", filter.status_source);
    if (search) params.set("search", search);
    if (sort) {
      params.set("sort", sort.key);
      params.set("direction", sort.direction);
    }
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    fetch(`${apiBaseUrl}/applications?${params}`, { credentials: "include" })
      .then((response) => response.json())
      .then(
        (payload: {
          applications: ApplicationSummary[];
          total: number;
          page: number;
          pageSize: number;
          facets: AppFacets;
        }) => {
          setApplications(payload.applications);
          setAppTotal(payload.total);
          setAppPage(payload.page);
          setAppPageSize(payload.pageSize);
          setAppFacets(payload.facets);
        },
      );
  }

  function viewApplication(id: number) {
    fetch(`${apiBaseUrl}/applications/${id}`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { application: ApplicationDetail }) => setSelectedApp(payload.application));
  }

  function toggleSort(key: SortKey) {
    // First click sorts ascending; clicking the active column flips direction.
    const next: SortState =
      appSort?.key === key
        ? { key, direction: appSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" };
    setAppSort(next);
    fetchApplications(appFilter, 1, appSearch, appPageSize, next);
  }

  function formatFieldValue(value: unknown, key?: string): React.ReactNode {
    if (value == null || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (key && MONEY_FIELDS.has(key) && typeof value === "number") {
      return `$${value.toLocaleString()}`;
    }
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

  function formatErrorDetail(detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (detail == null) return "";
    return JSON.stringify(detail, null, 2);
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
      body: JSON.stringify(draft),
    });

    if (response.ok) {
      const payload: SettingsResponse = await response.json();
      applySettingsResponse(payload);
      // Collapse the form after a successful save (applySettingsResponse keeps it
      // open only when no sheet is configured yet).
      if (resolveSheetId(payload)) {
        setIsSettingsExpanded(false);
      }
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
    setSyncError("");

    try {
      const response = await fetch(`${apiBaseUrl}/sync/applications`, {
        method: "POST",
        credentials: "include",
      });

      if (response.ok) {
        const payload: {
          syncRun: {
            rowCount: number;
            importedCount: number;
            updatedCount: number;
            unchangedCount: number;
          };
        } = await response.json();
        const { rowCount, importedCount, updatedCount, unchangedCount } = payload.syncRun;
        setSyncMessage(
          `Synced ${rowCount} rows: ${importedCount} imported, ${updatedCount} updated, ` +
            `${unchangedCount} unchanged.`,
        );
        refreshDashboard();
        fetchApplications(appFilter, 1, appSearch);
      } else {
        let detail = `Sync failed (HTTP ${response.status}).`;
        try {
          const payload = await response.json();
          if (payload.detail) detail = `Sync failed: ${formatErrorDetail(payload.detail)}`;
        } catch {
          // response body wasn't JSON
        }
        setSyncError(detail);
      }
    } catch (error) {
      setSyncError(
        `Sync error: ${
          error instanceof Error ? error.message : "Network request failed. Check that the backend is running."
        }`,
      );
    }

    setIsSyncing(false);
  }

  // Fetch the cost estimate and show the confirmation prompt. AI never runs
  // without the user first seeing the estimate and confirming (SPEC cost control).
  async function requestQualityFlagsEstimate() {
    setQfMessage("");
    const response = await fetch(`${apiBaseUrl}/quality-flags/estimate`, { credentials: "include" });
    if (response.ok) {
      setQfEstimate(await response.json());
    } else {
      setQfMessage("Could not load the AI cost estimate.");
    }
  }

  async function runQualityFlags() {
    setQfRunning(true);
    setQfMessage("");
    setQfEstimate(null);
    setQfProgress(null);
    try {
      const response = await fetch(`${apiBaseUrl}/quality-flags/run`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        setQfMessage(payload?.detail ? `Run failed: ${formatErrorDetail(payload.detail)}` : "Run failed.");
      } else {
        // Read the NDJSON stream: a progress line per application, then a summary.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? ""; // keep any partial line for the next chunk
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "progress") {
              setQfProgress({ processed: event.processed, total: event.total });
            } else if (event.type === "summary") {
              const failedNote = event.failed
                ? ` ${event.failed} failed and were skipped.`
                : "";
              setQfMessage(
                `Quality checks complete: ${event.flagged} flagged of ` +
                  `${event.analyzed + event.cached} analyzed ($${event.totalCostUsd.toFixed(4)}).` +
                  failedNote,
              );
            }
          }
        }
        // Refresh dashboard counts, the application list + facet counts, and the
        // open candidate so new flags/status show immediately after the run.
        refreshDashboard();
        fetchApplications(appFilter, appPage, appSearch);
        if (selectedApp) viewApplication(selectedApp.id);
      }
    } catch (error) {
      setQfMessage(error instanceof Error ? `Run error: ${error.message}` : "Run error.");
    }
    setQfProgress(null);
    setQfRunning(false);
  }

  // Essay-analysis run flow, mirroring quality flags. Same estimate-then-confirm
  // cost control; this pass is informational and never changes status.
  async function requestEssayAnalysisEstimate() {
    setEaMessage("");
    const response = await fetch(`${apiBaseUrl}/essay-analysis/estimate`, { credentials: "include" });
    if (response.ok) {
      setEaEstimate(await response.json());
    } else {
      setEaMessage("Could not load the AI cost estimate.");
    }
  }

  async function runEssayAnalysis() {
    setEaRunning(true);
    setEaMessage("");
    setEaEstimate(null);
    setEaProgress(null);
    try {
      const response = await fetch(`${apiBaseUrl}/essay-analysis/run`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        setEaMessage(payload?.detail ? `Run failed: ${formatErrorDetail(payload.detail)}` : "Run failed.");
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "progress") {
              setEaProgress({ processed: event.processed, total: event.total });
            } else if (event.type === "summary") {
              const failedNote = event.failed
                ? ` ${event.failed} failed and were skipped.`
                : "";
              setEaMessage(
                `Essay analysis complete: ${event.analyzed + event.cached} analyzed ` +
                  `($${event.totalCostUsd.toFixed(4)}).` +
                  failedNote,
              );
            }
          }
        }
        // Refresh the open candidate so the new analysis shows immediately, and
        // the dashboard so the workflow marks essay analysis done (gating).
        // Status/counts are unaffected by this pass.
        refreshDashboard();
        if (selectedApp) viewApplication(selectedApp.id);
      }
    } catch (error) {
      setEaMessage(error instanceof Error ? `Run error: ${error.message}` : "Run error.");
    }
    setEaProgress(null);
    setEaRunning(false);
  }

  // Human override of an application's status (any committee member). The backend
  // marks it human-owned and sticky against future machine runs.
  async function overrideStatus(id: number, status: AppStatus) {
    const response = await fetch(`${apiBaseUrl}/applications/${id}/status`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      // Refresh dashboard + list/facet counts so the change shows on "Back to list".
      refreshDashboard();
      fetchApplications(appFilter, appPage, appSearch);
    }
  }

  const hasGoogleSheetLink = Boolean(saved && resolveSheetId(saved));
  // Form visibility is an explicit open/closed state, not derived from the field
  // value — otherwise typing a link would collapse the form before saving.
  const showSettingsForm = isSettingsExpanded;

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
          <section className={`settings-panel ${showSettingsForm ? "" : "settings-panel-collapsed"}`} aria-label="Admin settings">
            <div className="settings-panel-header">
              <div>
                <span className="panel-kicker">Admin setup</span>
                <h2>Settings</h2>
              </div>
              {hasGoogleSheetLink ? (
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setIsSettingsExpanded((isExpanded) => !isExpanded)}
                >
                  {isSettingsExpanded ? "Hide settings" : "Edit settings"}
                </button>
              ) : null}
            </div>

            {hasGoogleSheetLink && saved && !showSettingsForm ? (
              <div className="settings-summary">
                <div>
                  <span>Google Sheet</span>
                  {saved.google_sheet_title && saved.google_sheet_url ? (
                    <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                      {saved.google_sheet_title}
                    </a>
                  ) : (
                    <strong>{saved.settings.google_sheet_id}</strong>
                  )}
                </div>
                <div>
                  <span>Opening</span>
                  <strong>
                    {saved.settings.unit_size.replace("br", " bedroom")}, {saved.settings.move_in_date}
                  </strong>
                </div>
                <div>
                  <span>Income range</span>
                  <strong>
                    {`$${saved.settings.income_min.toLocaleString()} – $${saved.settings.income_max.toLocaleString()}`}
                  </strong>
                </div>
              </div>
            ) : (
              <form className="settings-form" onSubmit={saveSettings}>
                <label>
                  <span>Google Sheet link</span>
                  <input
                    value={draft.google_sheet_id}
                    onChange={(event) => setDraft({ ...draft, google_sheet_id: event.target.value })}
                    placeholder="Paste the response spreadsheet link"
                  />
                  {saved?.google_sheet_title && saved.google_sheet_url ? (
                    <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                      {saved.google_sheet_title}
                    </a>
                  ) : null}
                </label>
                <label>
                  <span>Unit size</span>
                  <select
                    value={draft.unit_size}
                    onChange={(event) =>
                      setDraft({ ...draft, unit_size: event.target.value as AppSettings["unit_size"] })
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
                    value={draft.move_in_date}
                    onChange={(event) => setDraft({ ...draft, move_in_date: event.target.value })}
                  />
                </label>
                <label>
                  <span>Income minimum</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.income_min}
                    onChange={(event) => setDraft({ ...draft, income_min: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Income maximum</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.income_max}
                    onChange={(event) => setDraft({ ...draft, income_max: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Income mismatch tolerance</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.income_mismatch_tolerance}
                    onChange={(event) =>
                      setDraft({ ...draft, income_mismatch_tolerance: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  <span>Max adults per unit</span>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={draft.max_adults}
                    onChange={(event) => setDraft({ ...draft, max_adults: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Min adult age</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={draft.min_adult_age}
                    onChange={(event) => setDraft({ ...draft, min_adult_age: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max dogs</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={draft.max_dogs}
                    onChange={(event) => setDraft({ ...draft, max_dogs: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max cats</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={draft.max_cats}
                    onChange={(event) => setDraft({ ...draft, max_cats: Number(event.target.value) })}
                  />
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draft.allow_other_pets}
                    onChange={(event) => setDraft({ ...draft, allow_other_pets: event.target.checked })}
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
                          checked={!draft.disabled_rules.includes(rule.id)}
                          onChange={(event) => {
                            const disabled = event.target.checked
                              ? draft.disabled_rules.filter((r) => r !== rule.id)
                              : [...draft.disabled_rules, rule.id];
                            setDraft({ ...draft, disabled_rules: disabled });
                          }}
                        />
                        <span>{rule.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="rules-section">
                  <h3>AI Screening</h3>
                  <p className="rules-hint">
                    The quality-flag run is blocked before it starts if its estimated cost
                    exceeds this cap.
                  </p>
                  <label>
                    <span>Spending cap (USD per run)</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.ai.spending_cap_usd}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          ai: { ...draft.ai, spending_cap_usd: Number(event.target.value) },
                        })
                      }
                    />
                  </label>
                </div>
                <div className="settings-actions">
                  <button className="primary-button" type="submit" disabled={isSavingSettings}>
                    {isSavingSettings ? "Saving" : "Save settings"}
                  </button>
                  {settingsMessage ? <span>{settingsMessage}</span> : null}
                </div>
              </form>
            )}
          </section>

          {!hasGoogleSheetLink ? (
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

            {/* Ordered screening workflow. Each step's input depends on the
                previous (sync sets the pool, quality checks refine who's
                eligible, essay analysis runs on the eligible set), so later
                steps are hard-gated until the previous step has run. The
                "done" flags come from the backend, so gating survives reload. */}
            <div className="workflow-strip">
              <span className="workflow-strip-label">Screening workflow</span>
              <ol className="workflow-steps">
                <WorkflowStep
                  n={1}
                  title="Sync applications"
                  icon={<RefreshCw size={16} />}
                  done={workflow.synced}
                  busy={isSyncing}
                  busyLabel="Syncing"
                  // Step 1 is always available once a sheet is configured.
                  disabled={isSyncing || !hasGoogleSheetLink}
                  onClick={syncApplications}
                />
                <WorkflowStep
                  n={2}
                  title="Run quality checks"
                  icon={<Sparkles size={16} />}
                  done={workflow.qualityChecksRun}
                  busy={qfRunning}
                  busyLabel={
                    qfProgress
                      ? `Running ${qfProgress.processed}/${qfProgress.total} (${Math.round(qfPercent(qfProgress))}%)`
                      : "Running checks"
                  }
                  // Gated until a sync has happened; also needs eligible apps and
                  // no estimate prompt already open.
                  disabled={
                    !workflow.synced ||
                    qfRunning ||
                    qfEstimate !== null ||
                    dashboardCounts.status.eligible === 0
                  }
                  onClick={requestQualityFlagsEstimate}
                />
                <WorkflowStep
                  n={3}
                  title="Analyze essays"
                  icon={<Sparkles size={16} />}
                  done={workflow.essaysAnalyzed}
                  busy={eaRunning}
                  busyLabel={
                    eaProgress
                      ? `Analyzing ${eaProgress.processed}/${eaProgress.total} (${Math.round(qfPercent(eaProgress))}%)`
                      : "Analyzing essays"
                  }
                  // Gated until quality checks have run; also needs eligible apps.
                  disabled={
                    !workflow.qualityChecksRun ||
                    eaRunning ||
                    eaEstimate !== null ||
                    dashboardCounts.status.eligible === 0
                  }
                  onClick={requestEssayAnalysisEstimate}
                  last
                />
              </ol>
            </div>

            {qfEstimate ? (
              <div className="qf-confirm">
                <div className="qf-confirm-body">
                  <strong>Run AI quality checks?</strong>
                  <p>
                    Analyze {qfEstimate.to_analyze} eligible applicant
                    {qfEstimate.to_analyze === 1 ? "" : "s"}
                    {qfEstimate.cached > 0 ? ` (${qfEstimate.cached} already cached)` : ""}. Estimated cost{" "}
                    <strong>${qfEstimate.estimated_usd.toFixed(4)}</strong> (cap ${qfEstimate.cap_usd.toFixed(2)}).
                  </p>
                  {!qfEstimate.within_cap ? (
                    <p className="qf-confirm-warn">
                      Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
                    </p>
                  ) : null}
                </div>
                <div className="qf-confirm-actions">
                  <button
                    className="primary-button"
                    type="button"
                    onClick={runQualityFlags}
                    disabled={qfRunning || !qfEstimate.within_cap}
                  >
                    {qfRunning ? "Running" : "Confirm & run"}
                  </button>
                  <button className="secondary-button" type="button" onClick={() => setQfEstimate(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}
            {qfRunning ? (
              <div className="qf-progress">
                <div className="qf-progress-label">
                  {qfProgress
                    ? `Analyzing applications… ${qfProgress.processed}/${qfProgress.total} ` +
                      `(${Math.round(qfPercent(qfProgress))}%)`
                    : "Starting analysis…"}
                </div>
                {/* Until the first progress event arrives, show an indeterminate bar
                    so the indicator appears instantly on confirm, not seconds later
                    once the first application finishes. */}
                <div className="qf-progress-track">
                  {qfProgress ? (
                    <div
                      className="qf-progress-fill"
                      style={{ width: `${qfPercent(qfProgress)}%` }}
                    />
                  ) : (
                    <div className="qf-progress-fill qf-progress-fill-indeterminate" />
                  )}
                </div>
              </div>
            ) : null}
            {qfMessage ? <div className="qf-message">{qfMessage}</div> : null}

            {eaEstimate ? (
              <div className="qf-confirm">
                <div className="qf-confirm-body">
                  <strong>Run AI essay analysis?</strong>
                  <p>
                    Analyze the essays of {eaEstimate.to_analyze} eligible applicant
                    {eaEstimate.to_analyze === 1 ? "" : "s"}
                    {eaEstimate.cached > 0 ? ` (${eaEstimate.cached} already cached)` : ""}. Estimated cost{" "}
                    <strong>${eaEstimate.estimated_usd.toFixed(4)}</strong> (cap ${eaEstimate.cap_usd.toFixed(2)}).
                  </p>
                  {!eaEstimate.within_cap ? (
                    <p className="qf-confirm-warn">
                      Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
                    </p>
                  ) : null}
                </div>
                <div className="qf-confirm-actions">
                  <button
                    className="primary-button"
                    type="button"
                    onClick={runEssayAnalysis}
                    disabled={eaRunning || !eaEstimate.within_cap}
                  >
                    {eaRunning ? "Running" : "Confirm & run"}
                  </button>
                  <button className="secondary-button" type="button" onClick={() => setEaEstimate(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}
            {eaRunning ? (
              <div className="qf-progress">
                <div className="qf-progress-label">
                  {eaProgress
                    ? `Analyzing essays… ${eaProgress.processed}/${eaProgress.total} ` +
                      `(${Math.round(qfPercent(eaProgress))}%)`
                    : "Starting analysis…"}
                </div>
                <div className="qf-progress-track">
                  {eaProgress ? (
                    <div
                      className="qf-progress-fill"
                      style={{ width: `${qfPercent(eaProgress)}%` }}
                    />
                  ) : (
                    <div className="qf-progress-fill qf-progress-fill-indeterminate" />
                  )}
                </div>
              </div>
            ) : null}
            {eaMessage ? <div className="qf-message">{eaMessage}</div> : null}

            {selectedApp ? (() => {
              const flaggedFields = new Set(
                selectedApp.hardFilterReasons.flatMap((reason) => REASON_FIELDS[reason.code] ?? []),
              );
              return (
              <div className="app-detail">
                <button className="back-button" onClick={() => setSelectedApp(null)}>
                  <ChevronLeft size={16} />
                  <span>Back to list</span>
                </button>
                <div className="app-detail-header">
                  <h3>{selectedApp.applicantName || selectedApp.primaryEmail}</h3>
                  <span className={`status-badge status-${selectedApp.status}`}>
                    {STATUS_LABELS[selectedApp.status]}
                  </span>
                  {selectedApp.statusSource !== "untouched" ? (
                    <span className={`source-badge source-${selectedApp.statusSource}`}>
                      {SOURCE_LABELS[selectedApp.statusSource]}
                    </span>
                  ) : null}
                </div>
                {selectedApp.coApplicantName ? (
                  <p className="co-applicant-line">Co-applicant: {selectedApp.coApplicantName}</p>
                ) : null}

                <div className="status-panel">
                  <p className="status-source-line">{SOURCE_DESCRIPTIONS[selectedApp.statusSource]}</p>
                  {selectedApp.stale ? (
                    <p className="stale-note">
                      New AI findings since this was last reviewed — you may want to look again.
                    </p>
                  ) : null}
                  <div className="status-override">
                    <span className="status-override-label">Set status:</span>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={
                        selectedApp.status === "eligible" && selectedApp.statusSource === "human"
                      }
                      onClick={() => overrideStatus(selectedApp.id, "eligible")}
                    >
                      Eligible
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={
                        selectedApp.status === "ineligible" && selectedApp.statusSource === "human"
                      }
                      onClick={() => overrideStatus(selectedApp.id, "ineligible")}
                    >
                      Ineligible
                    </button>
                  </div>
                </div>
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
                {selectedApp.qualityFlags && selectedApp.qualityFlags.length > 0 ? (
                  <div className="quality-flags">
                    <strong>AI quality flags</strong>
                    <p className="quality-flags-hint">
                      The AI raised these. Decide for yourself which matter — set the status above.
                    </p>
                    <ul>
                      {selectedApp.qualityFlags.map((flag, i) => (
                        <li key={i} className={`quality-flag quality-flag-${flag.severity}`}>
                          <span className="quality-flag-category">
                            {FLAG_CATEGORY_LABELS[flag.category] ?? flag.category}
                          </span>
                          <span className="quality-flag-summary">{flag.summary}</span>
                          {flag.evidence ? (
                            <span className="quality-flag-evidence">{flag.evidence}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : selectedApp.qualityFlags ? (
                  <p className="quality-flags-clean">AI quality checks found no concerns.</p>
                ) : null}
                {selectedApp.essayAnalysis ? (
                  <div className="essay-analysis">
                    <h4>AI essay summary</h4>
                    <p className="essay-analysis-hint">
                      A neutral digest of what the applicant wrote. It describes what they said, not how good it is.
                    </p>
                    <p className="essay-analysis-summary">{selectedApp.essayAnalysis.summary}</p>
                    <dl className="essay-analysis-fields">
                      {renderEssayText("Household", selectedApp.essayAnalysis.household_context)}
                      {renderEssayText("Employment", selectedApp.essayAnalysis.employment_background)}
                      {renderEssayText("Prior co-op experience", selectedApp.essayAnalysis.prior_co_op_experience)}
                      {renderEssayChips("Skills offered", selectedApp.essayAnalysis.skills_offered)}
                      {renderEssayChips("Stated contributions", selectedApp.essayAnalysis.stated_contributions)}
                      {renderEssayChips("Motivations", selectedApp.essayAnalysis.stated_motivations)}
                      {renderEssayChips("Interests", selectedApp.essayAnalysis.interests)}
                      {renderEssayChips("Values", selectedApp.essayAnalysis.values)}
                    </dl>
                  </div>
                ) : null}
                {selectedApp.essays?.some((essay) => essay.answer) ? (
                  <div className="app-detail-essays">
                    <h4>Essay responses</h4>
                    {selectedApp.essays.map((essay) => (
                      <div key={essay.question} className="essay-block">
                        <h5>{essay.label}</h5>
                        {essay.answer ? (
                          <p>{essay.answer}</p>
                        ) : (
                          <p className="essay-empty">No response provided.</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="app-detail-fields">
                  <h4>Applicant data</h4>
                  <dl>
                    {Object.entries(selectedApp.normalized).map(([key, value]) => {
                      const flagged = flaggedFields.has(key);
                      return (
                        <div key={key} className={flagged ? "field-flagged" : undefined}>
                          <dt>{fieldLabel(key)}</dt>
                          <dd>{formatFieldValue(value, key)}</dd>
                        </div>
                      );
                    })}
                  </dl>
                </div>
                {selectedApp.rawRow ? (
                  <details className="raw-row-section">
                    <summary>Raw source row</summary>
                    <pre>{JSON.stringify(selectedApp.rawRow, null, 2)}</pre>
                  </details>
                ) : null}
                {selectedApp.aiNarrative ? (
                  <details className="raw-row-section">
                    <summary>Raw AI narrative (quality flags)</summary>
                    <div className="ai-narrative">
                      <ReactMarkdown>{selectedApp.aiNarrative}</ReactMarkdown>
                    </div>
                  </details>
                ) : null}
                {selectedApp.essayAnalysisNarrative ? (
                  <details className="raw-row-section">
                    <summary>Raw AI narrative (essay analysis)</summary>
                    <div className="ai-narrative">
                      <ReactMarkdown>{selectedApp.essayAnalysisNarrative}</ReactMarkdown>
                    </div>
                  </details>
                ) : null}
              </div>
              );
            })() : (
              <>
                <div className="app-controls">
                  {(() => {
                    // Each group toggles one axis of the filter, preserving the
                    // other, so Status and "Decided by" combine (AND).
                    const applyFilter = (next: typeof appFilter) => {
                      setAppFilter(next);
                      fetchApplications(next, 1, appSearch);
                    };
                    // Counts are faceted: each group reflects the OTHER group's
                    // active filter (plus search). "All"/"Any" sums the facet.
                    const statusFacet = appFacets?.status ?? dashboardCounts.status;
                    const sourceFacet = appFacets?.source ?? dashboardCounts.source;
                    const sum = (counts: Record<string, number>) =>
                      Object.values(counts).reduce((a, b) => a + b, 0);
                    const statusOptions = [
                      { label: "All", value: undefined, count: sum(statusFacet) },
                      { label: "Eligible", value: "eligible" as const, count: statusFacet.eligible },
                      { label: "Ineligible", value: "ineligible" as const, count: statusFacet.ineligible },
                    ];
                    const sourceOptions = [
                      { label: "Any", value: undefined, count: sum(sourceFacet) },
                      { label: "Rules", value: "rules" as const, count: sourceFacet.rules },
                      { label: "AI", value: "ai" as const, count: sourceFacet.ai },
                      { label: "Reviewer", value: "human" as const, count: sourceFacet.human },
                    ];
                    return (
                      <>
                        <div className="filter-group">
                          <span className="filter-group-label">Status</span>
                          <div className="app-tabs">
                            {statusOptions.map((opt) => (
                              <button
                                key={opt.label}
                                className={`tab-button ${appFilter.status === opt.value ? "active" : ""}`}
                                onClick={() => applyFilter({ ...appFilter, status: opt.value })}
                              >
                                {opt.label} ({opt.count})
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="filter-group">
                          <span className="filter-group-label">Decided by</span>
                          <div className="app-tabs">
                            {sourceOptions.map((opt) => (
                              <button
                                key={opt.label}
                                className={`tab-button ${
                                  appFilter.status_source === opt.value ? "active" : ""
                                }`}
                                onClick={() => applyFilter({ ...appFilter, status_source: opt.value })}
                              >
                                {opt.label} ({opt.count})
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    );
                  })()}
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
                    <p>
                      {appFilter.status || appFilter.status_source
                        ? "No applications match this filter."
                        : "No applications imported yet."}
                    </p>
                  </div>
                ) : (
                  <>
                    <table className="app-table">
                      <thead>
                        <tr>
                          {(
                            [
                              { label: "Applicant", key: "applicant" },
                              { label: "Co-applicant", key: "co_applicant" },
                              { label: "Children", key: "children" },
                              { label: "Income", key: "income" },
                              { label: "Status", key: "status" },
                            ] as Array<{ label: string; key: SortKey }>
                          ).map((col) => (
                            <th key={col.key}>
                              <button
                                type="button"
                                className={`sort-header ${appSort?.key === col.key ? "active" : ""}`}
                                onClick={() => toggleSort(col.key)}
                              >
                                <span>{col.label}</span>
                                {appSort?.key === col.key ? (
                                  appSort.direction === "asc" ? (
                                    <ChevronUp size={14} />
                                  ) : (
                                    <ChevronDown size={14} />
                                  )
                                ) : null}
                              </button>
                            </th>
                          ))}
                          <th>Decided by</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {applications.map((app) => {
                          // Reason cell shows the machine's "why" for an exclusion: rules
                          // reasons, or AI flag categories. Human overrides show neither.
                          const reason =
                            app.statusSource === "rules"
                              ? app.hardFilterReasons.map((r) => r.message).join("; ")
                              : app.statusSource === "ai"
                                ? (app.flagCategories ?? []).map(flagCategoryLabel).join("; ")
                                : "—";
                          return (
                            <tr key={app.id} onClick={() => viewApplication(app.id)} className="clickable-row">
                              <td>{app.applicantName || app.primaryEmail}</td>
                              <td>{app.coApplicantName || "—"}</td>
                              <td>{app.childCount ?? "?"}</td>
                              <td>
                                {app.householdIncome != null ? `$${app.householdIncome.toLocaleString()}` : "?"}
                              </td>
                              <td>
                                <span className={`status-badge status-${app.status}`}>
                                  {STATUS_LABELS[app.status]}
                                </span>
                              </td>
                              <td>
                                {app.statusSource === "untouched" ? (
                                  "—"
                                ) : (
                                  <span className={`source-badge source-${app.statusSource}`}>
                                    {SOURCE_LABELS[app.statusSource]}
                                  </span>
                                )}
                                {app.stale ? (
                                  <span className="stale-badge" title="New AI findings since last review">
                                    stale
                                  </span>
                                ) : null}
                              </td>
                              <td className="reason-cell">{reason}</td>
                            </tr>
                          );
                        })}
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
      {syncError || syncMessage ? (
        <div
          className={`toast ${syncError ? "toast-error" : "toast-success"}`}
          aria-live={syncError ? "assertive" : "polite"}
          role={syncError ? "alert" : "status"}
        >
          <div className="toast-message">{syncError || syncMessage}</div>
          <div className="toast-actions">
            {syncError ? (
              <button
                className="toast-button"
                aria-label="Copy sync error"
                title="Copy sync error"
                onClick={() => navigator.clipboard.writeText(syncError)}
              >
                <Clipboard size={16} />
              </button>
            ) : null}
            <button
              className="toast-button"
              aria-label="Dismiss notification"
              title="Dismiss notification"
              onClick={() => {
                setSyncError("");
                setSyncMessage("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        </div>
      ) : null}
    </main>
  );
}
