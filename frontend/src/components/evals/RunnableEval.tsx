import { type ReactNode, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchEvalCases, fetchLastEvalRun, runEval, saveEvalCase, streamNdjson } from "../../api";
import type { LastEvalRun } from "../../types";
import { EvalCaseDetail } from "./EvalCaseDetail";
import { EvalCaseEditor } from "./EvalCaseEditor";
import { HarvestPanel } from "./HarvestPanel";
import { InlineConfirm } from "./InlineConfirm";
import type { FieldObject } from "./StructuredFields";

// A runnable eval subtab (a pass, or Judge). Master-detail: a case LIST on the left
// (grouped, e.g. judge cases by the production pass they exercise), a full case DETAIL /
// EDITOR on the right. Whole-set run buttons (one per mode) and per-case run links, both
// spend-confirmed inline (the workflow card, not window.confirm). The model's reasoning
// streams as rendered markdown; results merge back onto each case row + into the detail.

export type RunMode = { evalKey: "scoring" | "scoring_stability" | "consolidation" | "consolidation_stability" | "matching" | "matching_stability" | "decomposition" | "decomposition_stability" | "screening" | "screening_stability" | "judge" | "stability"; label: string; rowLabel: string; calls: number };

type RunState = { running: boolean; thinking: string; result: any | null; ranMode: RunMode["evalKey"]; error: string | null };
type Confirm = { mode: RunMode; caseKey?: string; calls: number } | null;

export function RunnableEval(props: {
  // The fixture whose cases we read/edit (a pass's stability mode shares its golden set).
  caseEvalKey: "scoring" | "consolidation" | "matching" | "decomposition" | "screening" | "judge";
  // The eval keys whose last run restores this tab on remount (Scoring: ["scoring"];
  // Judge: ["judge", "stability"] — the two share the tab, so the newer of the two shows).
  runKeys: RunMode["evalKey"][];
  description: string;
  modes: RunMode[];
  // Group cases under headings by this case field (e.g. "pass" for judge); undefined = flat.
  groupBy?: string;
  // Judge only: offer "Harvest from current run" — propose fidelity-preserving candidate
  // cases from the current Rank's scoring/screening output, opened in the editor to label.
  harvestable?: boolean;
  // Whether cases can be added/edited here. The Judge tab is READ-ONLY over cases (it owns no
  // files — it audits every pass's golden set), so it passes false: no "+ Add case", no
  // per-case edit. Editing happens in each pass's own tab. Defaults to true.
  editable?: boolean;
  // Extra content rendered above the run controls (the Judge tab's per-pass background editors).
  header?: ReactNode;
}): ReactNode {
  const { caseEvalKey, modes } = props;
  const editable = props.editable ?? true;
  const [cases, setCases] = useState<Record<string, unknown>[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null); // selected case key
  const [editing, setEditing] = useState<{ existing: Record<string, unknown> | null } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [run, setRun] = useState<RunState>({ running: false, thinking: "", result: null, ranMode: modes[0].evalKey, error: null });
  // Per-case results, nested case key → mode → result. Nesting by MODE lets a case hold its
  // live-run result AND its stability result at once (running stability no longer clobbers
  // the live dot, and vice versa). A whole-set run replaces every case's entry FOR THAT MODE;
  // a per-case run merges just its one case+mode — so no run wipes another case's or another
  // mode's result.
  type ModeResults = Partial<Record<RunMode["evalKey"], any>>;
  const [caseResults, setCaseResults] = useState<Record<string, ModeResults>>({});
  // Rehydrated past runs (not this session), one per mode that had one — drives the "last
  // run · prompt" marker so history is never mistaken for fresh. A fresh run of a mode clears
  // that mode's entry.
  const [restored, setRestored] = useState<Record<string, LastEvalRun>>({});
  const thinkingRef = useRef<HTMLDivElement>(null);

  const loadCases = () => {
    fetchEvalCases(caseEvalKey)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCases(d?.cases ?? []));
  };
  useEffect(loadCases, [caseEvalKey]);

  // Load the last persisted run PER MODE for this tab. Used on mount (so switching subtabs and
  // coming back shows what you last saw — result + case dots — instead of a blank tab; a tab
  // with two evals restores BOTH) AND right after a fresh run completes (so its "last run just
  // now · prompt …" marker reappears without a page reload — the backend persists the row
  // before it emits the summary, so a re-fetch here always sees the just-finished run). When
  // ``seedResults`` is true (mount only) it also rehydrates the per-case dots; a post-run
  // refresh leaves the freshly-merged case results alone. Thinking is never restored (the
  // outcome-not-replay choice). Returns a promise so callers can await the refresh.
  const loadLastRuns = (seedResults: boolean) =>
    fetchLastEvalRun(props.runKeys)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { runs?: LastEvalRun[] } | null) => {
        if (!d?.runs?.length) return;
        const byMode: Record<string, LastEvalRun> = {};
        for (const run of d.runs) byMode[run.evalKey as RunMode["evalKey"]] = run;
        setRestored(byMode);
        if (!seedResults) return;
        const seeded: Record<string, ModeResults> = {};
        for (const run of d.runs) {
          const mode = run.evalKey as RunMode["evalKey"];
          for (const c of (run.result?.cases ?? []) as any[]) {
            (seeded[c.key] ??= {})[mode] = c;
          }
        }
        setCaseResults(seeded);
        // Show the newest restored run's headline (pick the most recent overall).
        const newest = d.runs.reduce((a, b) => (a.ranAt >= b.ranAt ? a : b));
        setRun((r) => ({ ...r, result: newest.result, ranMode: newest.evalKey as RunMode["evalKey"] }));
      });
  useEffect(() => {
    void loadLastRuns(true);
    // props.runKeys is a stable per-tab literal; joining keeps the dep primitive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.runKeys.join(",")]);
  useEffect(() => {
    // Keep the newest line in view as it streams in (the box is a small capped scroller,
    // like the Rank reasoning box).
    const el = thinkingRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  async function doRun(mode: RunMode, caseKey?: string) {
    // A fresh run of a mode supersedes only THAT mode's rehydrated history (the other mode's
    // restored marker stays).
    setRestored((prev) => {
      const { [mode.evalKey]: _drop, ...rest } = prev;
      return rest;
    });
    setRun({ running: true, thinking: "", result: null, ranMode: mode.evalKey, error: null });
    try {
      const resp = await runEval(mode.evalKey, { caseKey });
      if (!resp.ok || !resp.body) {
        setRun((r) => ({ ...r, running: false, error: `Request failed (${resp.status})` }));
        return;
      }
      await streamNdjson(resp.body, (e) => {
        if (e.type === "thinking") setRun((r) => ({ ...r, thinking: r.thinking + e.text }));
        else if (e.type === "summary") {
          setRun((r) => ({ ...r, running: false, result: e.result }));
          // Merge this run's per-case results under THIS MODE, preserving other modes'
          // results on each case. A whole-set run replaces every case's entry for this mode
          // (clear the mode first); a per-case run touches only its one case+mode.
          const cases: any[] = e.result?.cases ?? [];
          setCaseResults((prev) => {
            const next: Record<string, ModeResults> = {};
            for (const [k, modeMap] of Object.entries(prev)) {
              // On a whole-set run, drop this mode from every case (a stale case not in the
              // new results shouldn't keep an old dot); a per-case run keeps everything.
              next[k] = caseKey ? { ...modeMap } : { ...modeMap, [mode.evalKey]: undefined };
            }
            for (const c of cases) (next[c.key] ??= {})[mode.evalKey] = c;
            return next;
          });
          // Re-fetch the last-run markers so THIS run's "last run just now · prompt …" marker
          // reappears immediately (it was cleared when the run started). The row is already
          // persisted by the time the summary arrives, so this always sees the fresh run.
          void loadLastRuns(false);
        } else if (e.type === "error") setRun((r) => ({ ...r, running: false, error: e.message }));
      });
      setRun((r) => (r.running ? { ...r, running: false } : r));
    } catch (err) {
      setRun((r) => ({ ...r, running: false, error: String(err) }));
    }
  }

  async function persistCase(evalCase: FieldObject) {
    setSaveError(null);
    const resp = await saveEvalCase(caseEvalKey, evalCase);
    if (resp.ok) {
      setCases((await resp.json()).cases);
      setSelected(String(evalCase.key));
      setEditing(null);
    } else {
      const problem = await resp.json().catch(() => null);
      setSaveError(problem?.detail ?? `Save failed (${resp.status})`);
    }
  }

  const selectedCase = cases?.find((c) => c.key === selected) ?? null;
  const selectedResult = selected ? caseResults[selected] : undefined;
  const perCaseCalls = (m: RunMode) => (cases?.length ? Math.max(1, Math.round(m.calls / cases.length)) : 1);

  // The spend-confirm renders INLINE next to the button that triggered it: the whole-set
  // buttons at the top, a per-case button down in the detail pane. Keyed by whether the
  // pending confirm carries a caseKey, so it never appears far from what launched it.
  const renderConfirm = () => (
    <InlineConfirm
      title={confirm!.caseKey ? `Run case “${confirm!.caseKey}”?` : `${confirm!.mode.label}?`}
      body={`This makes ~${confirm!.calls} model call${confirm!.calls === 1 ? "" : "s"} and costs real money.`}
      onConfirm={() => {
        const t = confirm!;
        setConfirm(null);
        void doRun(t.mode, t.caseKey);
      }}
      onCancel={() => setConfirm(null)}
    />
  );

  return (
    <div className="eval-section">
      <p className="eval-card-desc">{props.description}</p>

      {props.header}

      {confirm && !confirm.caseKey ? renderConfirm() : null}

      <div className="eval-section-actions">
        {modes.map((m) => (
          <button
            key={m.evalKey}
            type="button"
            className="primary-button"
            disabled={run.running}
            onClick={() => setConfirm({ mode: m, calls: m.calls })}
          >
            {run.running ? "Running…" : `${m.label} (~${m.calls})`}
          </button>
        ))}
        {editable ? (
          <button
            type="button"
            className="secondary-button"
            disabled={run.running}
            onClick={() => {
              setSaveError(null);
              setEditing({ existing: null });
              setSelected(null);
            }}
          >
            + Add case
          </button>
        ) : null}
      </div>

      {props.harvestable ? (
        <HarvestPanel
          onEditCandidate={(candidate) => {
            setSaveError(null);
            setSelected(null);
            setEditing({ existing: candidate });
          }}
        />
      ) : null}

      {run.error ? <p className="eval-error">{run.error}</p> : null}
      {run.running || run.thinking ? (
        <div className="eval-thinking" ref={thinkingRef}>
          <div className="ai-narrative">
            <ReactMarkdown>{run.thinking || "_Starting…_"}</ReactMarkdown>
          </div>
        </div>
      ) : null}
      {Object.keys(restored).length ? (
        // One block so the section's grid row-gap applies ONCE above it, not between each
        // stacked marker (which otherwise spread far apart — see .eval-runinfo). Each marker
        // is one self-contained line (label · result · when · prompt · model).
        <div className="eval-runinfo">
          {Object.values(restored).map((r) => (
            <RestoredMarker key={r.evalKey} run={r} totalCases={cases?.length ?? 0} />
          ))}
        </div>
      ) : null}

      <div className="eval-master-detail">
        <div className="eval-master">
          <CaseList
            cases={cases}
            groupBy={props.groupBy}
            selected={selected}
            caseResults={caseResults}
            modes={modes}
            onSelect={(k) => {
              setSelected(k);
              setEditing(null);
            }}
          />
        </div>
        <div className="eval-detail-pane">
          {editing ? (
            <EvalCaseEditor
              evalKey={caseEvalKey}
              existing={editing.existing}
              error={saveError}
              onCancel={() => setEditing(null)}
              onSave={persistCase}
            />
          ) : selectedCase ? (
            <div>
              <div className="eval-detail-actions">
                {modes.map((m) => (
                  <button
                    key={m.evalKey}
                    type="button"
                    className="primary-button"
                    disabled={run.running}
                    onClick={() => setConfirm({ mode: m, caseKey: String(selectedCase.key), calls: perCaseCalls(m) })}
                  >
                    {run.running ? "Running…" : m.rowLabel}
                  </button>
                ))}
                {editable ? (
                  <button
                    type="button"
                    className="secondary-button eval-detail-edit"
                    disabled={run.running}
                    onClick={() => {
                      setSaveError(null);
                      setEditing({ existing: selectedCase });
                    }}
                  >
                    Edit
                  </button>
                ) : null}
              </div>
              {confirm?.caseKey === String(selectedCase.key) ? renderConfirm() : null}
              {selectedResult
                ? modes
                    .filter((m) => selectedResult[m.evalKey])
                    .map((m) => (
                      <CaseResult key={m.evalKey} evalKey={m.evalKey} result={selectedResult[m.evalKey]} />
                    ))
                : null}
              <EvalCaseDetail evalCase={selectedCase} />
            </div>
          ) : (
            <p className="eval-detail-placeholder">
              {editable ? "Select a case to see its full input, or add a new one." : "Select a case to see its full input."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// One mode's result read as a dot. Contested cases are never red (both verdicts defensible),
// but they aren't always amber either: on a SINGLE run, agreeing with the leaning is the
// fine, unremarkable outcome (green) — only a DIVERGENCE from the leaning is review-worthy
// (amber). A stability run that actually wobbled ([contested-split]) stays amber — the
// wobble IS the review event.
// The categorical dimension-comparison live passes share one result shape (passed / verdict /
// expected / contested / reason / judgeVerdict), so every renderer branch treats them alike.
const CATEGORICAL = new Set(["consolidation", "matching", "decomposition"]);

function dotFor(mode: RunMode["evalKey"], result: any): "ok" | "fail" | "contested" {
  if (result.marker === "[contested-split]") return "contested";  // stability wobble
  if (CATEGORICAL.has(mode) && result.contested) {
    return result.verdict === result.expected ? "ok" : "contested";  // agree = green, diverge = amber
  }
  return resultOk(mode, result) ? "ok" : "fail";
}

// The case list, optionally grouped by a field (judge: by production pass).
function CaseList(props: {
  cases: Record<string, unknown>[] | null;
  groupBy?: string;
  selected: string | null;
  caseResults: Record<string, Record<string, any>>;
  // The tab's run modes, in button order — one dot per mode so live + stability read as two
  // distinct indicators (not one aggregate that hides which check is in what state).
  modes: RunMode[];
  onSelect: (key: string) => void;
}): ReactNode {
  const { cases } = props;
  if (cases === null) return <p className="eval-hint">Loading cases…</p>;
  if (!cases.length) return <p className="eval-hint">No cases yet.</p>;

  // The grouping/label fields (pass, expected) live in the harness-only `metadata` block.
  const meta = (c: Record<string, unknown>) => (c.metadata ?? {}) as Record<string, unknown>;

  const groups: { heading: string | null; items: Record<string, unknown>[] }[] = [];
  if (props.groupBy) {
    const byGroup = new Map<string, Record<string, unknown>[]>();
    for (const c of cases) {
      const g = String(meta(c)[props.groupBy] ?? "consolidation"); // judge default pass
      (byGroup.get(g) ?? byGroup.set(g, []).get(g)!).push(c);
    }
    for (const [heading, items] of [...byGroup.entries()].sort()) groups.push({ heading, items });
  } else {
    groups.push({ heading: null, items: cases });
  }

  return (
    <div className="eval-case-list">
      {groups.map((g) => (
        <div key={g.heading ?? "all"} className="eval-case-group">
          {g.heading ? <div className="eval-case-group-head">{g.heading}</div> : null}
          {g.items.map((c) => {
            const key = String(c.key);
            const modeMap = props.caseResults[key] ?? {};
            // ALWAYS one dot per mode, in button order (left = first mode, e.g. live; right =
            // stability). A mode not yet run shows grey, so position tells you which ran: e.g.
            // green+grey = live passed, stability not run yet. Only render the cluster once a
            // tab has >1 mode OR any result exists (a single-mode tab with no runs stays clean).
            const showDots = props.modes.length > 1 || props.modes.some((m) => modeMap[m.evalKey]);
            return (
              <button
                key={key}
                type="button"
                className={`eval-case-item${props.selected === key ? " selected" : ""}`}
                onClick={() => props.onSelect(key)}
              >
                {showDots ? (
                  <span className="eval-case-dots">
                    {props.modes.map((m) => {
                      const result = modeMap[m.evalKey];
                      const dot = result ? dotFor(m.evalKey, result) : "empty";
                      return (
                        <span
                          key={m.evalKey}
                          className={`eval-case-dot ${dot}`}
                          title={`${m.label}: ${result ? dot : "not run"}`}
                        />
                      );
                    })}
                  </span>
                ) : null}
                <span className="eval-case-item-key">{key}</span>
                {meta(c).expected !== undefined ? (
                  <span className="eval-case-item-expected">{expectedLabel(meta(c).expected)}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// A compact label for a case's `metadata.expected` chip. Categorical labels are strings;
// scoring is a band ({score_min, score_max, confidence?}); screening is {fires, absent}.
// Mirrors the backend _seed_str so a case reads the same in the list and the run marker.
function expectedLabel(expected: unknown): string {
  if (typeof expected === "string") return expected;
  if (expected && typeof expected === "object") {
    const e = expected as Record<string, unknown>;
    if ("fires" in e || "absent" in e) {
      const parts: string[] = [];
      const fires = e.fires as string[] | undefined;
      const absent = e.absent as string[] | undefined;
      if (fires?.length) parts.push(`fires: ${fires.join(", ")}`);
      if (absent?.length) parts.push(`absent: ${absent.join(", ")}`);
      return parts.join(" · ") || "clean";
    }
    if ("score_min" in e || "score_max" in e || "confidence" in e) {
      const lo = e.score_min ?? "-1";
      const hi = e.score_max ?? "1";
      const conf = e.confidence ? ` ${e.confidence}` : "";
      return `[${lo}, ${hi}]${conf}`;
    }
  }
  return String(expected);
}

function resultOk(ranMode: RunMode["evalKey"], r: any): boolean {
  if (ranMode === "scoring" || ranMode === "screening" || CATEGORICAL.has(ranMode)) return r.passed;
  if (ranMode.endsWith("_stability") || ranMode === "stability") return r.marker === "[stable]";
  return r.marker === "[ok]";
}

// Marks a REHYDRATED result as history (not a fresh run): which eval, when it ran + which
// prompt, and an amber warning when that prompt no longer matches the current one (so a stale
// result is never read as live). A tab with two evals shows one marker each; the label names
// the pass + mode ("Matching", "Matching stability") so each marker is self-describing.
function restoredLabel(evalKey: string): string {
  const stability = evalKey.endsWith("_stability");
  const base = evalKey.replace(/^live_/, "").replace(/_stability$/, "");
  const pass = base === "stability" ? "judge" : base;  // judge's stability key is bare "stability"
  const name = pass.charAt(0).toUpperCase() + pass.slice(1);
  return stability || evalKey === "stability" ? `${name} stability` : name;
}

// The model a run used, read from whichever field that mode's result shape carries (scoring
// uses `scoringModel`; the judge uses `judgeModel`; the rest use `model`). Empty if absent.
function runModel(result: any): string {
  return result?.model || result?.scoringModel || result?.judgeModel || "";
}

// The one-line RESULT summary for a run mode. The NUMERATOR counts the run's per-case results
// the SAME way the dots do (via dotFor), so it always matches the green dots — including a
// per-case run and contested-agree cases (green, counted ok) which the backend's passed/total
// excludes. The DENOMINATOR is the TOTAL case count (every dot slot in the list), not how many
// have a result yet — so a partial run reads "4/5", not "4/4". Graded: "X/Y passed"; stability:
// "X/Y stable"; the judge adds its agreement block. Empty ⇒ no summary segment.
function runSummary(evalKey: RunMode["evalKey"], result: any, totalCases: number): string {
  if (!result) return "";
  const cases = (result.cases ?? []) as any[];
  const total = totalCases || cases.length;  // fall back to run-cases if the list isn't loaded
  const stab = evalKey.endsWith("_stability") || evalKey === "stability";
  const ok = cases.filter((c) => dotFor(evalKey, c) === "ok").length;
  if (evalKey === "judge") {
    const a = result.agreement;
    const head = total ? `${ok}/${total} agree` : "";
    if (!a) return head;
    const parts = head ? [head] : [];
    parts.push(`κ ${a.kappa !== null ? a.kappa.toFixed(2) : "n/a"}`);
    if (a.failureRecall !== null)
      parts.push(`failure-recall ${a.failureCaught}/${a.failureTotal} = ${Math.round(a.failureRecall * 100)}%`);
    return parts.join(" · ");
  }
  if (!total) return "";
  return `${ok}/${total} ${stab ? "stable" : "passed"}`;
}

// One self-contained line per run mode: label, result summary, when it ran, the prompt
// version, and the model. Turns amber when the run's prompt no longer matches the current one
// (so a stale result is never read as live). Replaces the old separate "headline" — everything
// it carried lives here now, without repeating the pass name/prompt/model on a second line.
function RestoredMarker(props: { run: LastEvalRun; totalCases: number }): ReactNode {
  const { run } = props;
  const summary = runSummary(run.evalKey as RunMode["evalKey"], run.result, props.totalCases);
  const model = runModel(run.result);
  return (
    <div className={`eval-restored${run.stale ? " stale" : ""}`}>
      {restoredLabel(run.evalKey)}
      {summary ? ` · ${summary}` : ""} · last run {relativeTime(run.ranAt)} · prompt {run.promptVersion || "—"}
      {model ? ` · ${model}` : ""}
      {run.stale ? ` · prompt has since changed (now ${run.currentPromptVersion}) — re-run to refresh` : ""}
    </div>
  );
}

// A compact "2h ago" / "3d ago" from an ISO timestamp; falls back to the date for old runs.
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "earlier";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

// Model-produced prose (evidence, reasons, per-run detail) is markdown — the AI writes it
// that way — so render it as such rather than dumping the raw source. `className` carries the
// surrounding style (muted/italic); `eval-md` tightens react-markdown's block margins so a
// one-liner doesn't get paragraph spacing. NB: deterministic, code-generated strings (the
// `failures` list) are NOT model text and stay plain.
function Md({ text, className }: { text: string; className?: string }): ReactNode {
  return (
    <div className={`eval-md${className ? ` ${className}` : ""}`}>
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}

// The per-run breakdown of a stability case: each of the K runs' outcome + the model's own
// reasoning for it. This is what makes a flip self-explaining — a bare "3× matches, 2×
// mismatches" doesn't say WHY the two mismatched; the reasoning does. Older runs (persisted
// before per-run detail existed) have no `runs`, so render nothing.
function StabilityRuns({ runs }: { runs?: { outcome: string; detail: string }[] }): ReactNode {
  if (!runs?.length) return null;
  return (
    <ol className="eval-stability-runs">
      {runs.map((run, i) => (
        <li key={i}>
          <span className="eval-mono">{run.outcome}</span>
          {run.detail ? <Md text={run.detail} className="eval-case-result-ev" /> : null}
        </li>
      ))}
    </ol>
  );
}

// One case's result, shown in the detail pane above its input.
function CaseResult(props: { evalKey: RunMode["evalKey"]; result: any }): ReactNode {
  const { evalKey, result: r } = props;
  // Header color is the single dot decision (dotFor): green when it passed or a contested
  // case agreed with its leaning; amber for a contested divergence / stability wobble; red
  // only for a non-contested fail. One source of truth so dot and header can't disagree.
  const cls = dotFor(evalKey, r);
  const head = cls === "contested" ? "◐ contested" : cls === "ok" ? "✓ passed" : "✗ failed";
  return (
    <div className={`eval-case-result ${cls}`}>
      <span className="eval-case-result-head">{head}</span>
      {evalKey === "scoring" ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">score {r.score}</span> · {r.confidence} confidence
          {r.evidence ? <Md text={`“${r.evidence}”`} className="eval-case-result-ev" /> : null}
          {r.failures?.map((f: string) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
        </div>
      ) : CATEGORICAL.has(evalKey) ? (
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{r.expected}</span> → produced{" "}
          <span className="eval-mono">{r.verdict}</span>
          {r.reason ? <Md text={r.reason} className="eval-case-result-ev" /> : null}
        </div>
      ) : evalKey === "screening" ? (
        <div className="eval-case-result-body">
          flags: <span className="eval-mono">{r.categories?.length ? r.categories.join(", ") : "none"}</span>
          {r.fires?.length ? <span className="eval-verdict">{" · "}expect: {r.fires.join(", ")}</span> : null}
          {r.absent?.length ? <span className="eval-verdict">{" · "}guard: no {r.absent.join(", ")}</span> : null}
          {r.failures?.map((f: string) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
          {r.reason ? <Md text={r.reason} className="eval-case-result-ev" /> : null}
        </div>
      ) : evalKey === "scoring_stability" ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">{r.marker}</span> {Math.round(r.agreement * 100)}% agreement over K —{" "}
          {Object.entries(r.tally).map(([v, n]) => `${v}×${n}`).join(", ")}
          <span className="eval-verdict">
            {" · "}score {r.scoreMin?.toFixed(2)}..{r.scoreMax?.toFixed(2)}
          </span>
          <StabilityRuns runs={r.runs} />
        </div>
      ) : evalKey === "stability" || evalKey.endsWith("_stability") ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">{r.marker}</span> {Math.round(r.agreement * 100)}% agreement over K —{" "}
          {Object.entries(r.tally).map(([v, n]) => `${v}×${n}`).join(", ")}
          <StabilityRuns runs={r.runs} />
        </div>
      ) : (
        // Judge (blind label audit): the human label vs. what the blind judge reproduced.
        <div className="eval-case-result-body">
          label <span className="eval-mono">{r.humanLabel}</span> → judge said{" "}
          <span className="eval-mono">{r.judgeLabel}</span>
          {r.humanLabel !== r.judgeLabel ? " (disagrees)" : ""}
          {r.detail ? <Md text={r.detail} className="eval-case-result-ev" /> : null}
        </div>
      )}
    </div>
  );
}
