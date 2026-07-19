import { type ReactNode, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchEvalCases, fetchLastEvalRun, runEval, saveEvalCase, streamNdjson } from "../../api";
import type { LastEvalRun } from "../../types";
import { EvalCaseDetail } from "./EvalCaseDetail";
import { EvalCaseEditor } from "./EvalCaseEditor";
import { HarvestPanel } from "./HarvestPanel";
import { InlineConfirm } from "./InlineConfirm";
import type { FieldObject } from "./StructuredFields";

// A runnable eval subtab (Live scoring, or Judge). Master-detail: a case LIST on the left
// (grouped, e.g. judge cases by the production pass they exercise), a full case DETAIL /
// EDITOR on the right. Whole-set run buttons (one per mode) and per-case run links, both
// spend-confirmed inline (the workflow card, not window.confirm). The model's reasoning
// streams as rendered markdown; results merge back onto each case row + into the detail.

export type RunMode = { evalKey: "live_scoring" | "live_scoring_stability" | "live_consolidation" | "live_consolidation_stability" | "live_matching" | "live_matching_stability" | "live_decomposition" | "live_decomposition_stability" | "live_screening" | "live_screening_stability" | "judge" | "stability"; label: string; rowLabel: string; calls: number };

type RunState = { running: boolean; thinking: string; result: any | null; ranMode: RunMode["evalKey"]; error: string | null };
type Confirm = { mode: RunMode; caseKey?: string; calls: number } | null;

export function RunnableEval(props: {
  // The fixture whose cases we read/edit (a pass's stability mode shares its golden set).
  caseEvalKey: "live_scoring" | "live_consolidation" | "live_matching" | "live_decomposition" | "live_screening" | "judge";
  // The eval keys whose last run restores this tab on remount (Live scoring: ["live_scoring"];
  // Judge: ["judge", "stability"] — the two share the tab, so the newer of the two shows).
  runKeys: RunMode["evalKey"][];
  description: string;
  modes: RunMode[];
  // Group cases under headings by this case field (e.g. "pass" for judge); undefined = flat.
  groupBy?: string;
  // Judge only: offer "Harvest from current run" — propose fidelity-preserving candidate
  // cases from the current Rank's scoring/screening output, opened in the editor to label.
  harvestable?: boolean;
}): ReactNode {
  const { caseEvalKey, modes } = props;
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

  // On mount, restore the last persisted run PER MODE for this tab so switching subtabs and
  // coming back shows what you last saw (result + case dots) instead of a blank tab — and a
  // tab with two evals (live + stability) restores BOTH. Thinking is not restored (per the
  // outcome-not-replay choice); a fresh run of a mode clears that mode's restored marker.
  useEffect(() => {
    let live = true;
    fetchLastEvalRun(props.runKeys)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { runs?: LastEvalRun[] } | null) => {
        if (!live || !d?.runs?.length) return;
        const byMode: Record<string, LastEvalRun> = {};
        const seeded: Record<string, ModeResults> = {};
        for (const run of d.runs) {
          const mode = run.evalKey as RunMode["evalKey"];
          byMode[mode] = run;
          for (const c of (run.result?.cases ?? []) as any[]) {
            (seeded[c.key] ??= {})[mode] = c;
          }
        }
        setRestored(byMode);
        setCaseResults(seeded);
        // Show the newest restored run's headline (the runs come newest-first per key; pick
        // the most recent overall for the headline/detail summary).
        const newest = d.runs.reduce((a, b) => (a.ranAt >= b.ranAt ? a : b));
        setRun((r) => ({ ...r, result: newest.result, ranMode: newest.evalKey as RunMode["evalKey"] }));
      });
    return () => {
      live = false;
    };
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
      {Object.values(restored).map((r) => (
        <RestoredMarker key={r.evalKey} run={r} />
      ))}
      {run.result ? <RunHeadline evalKey={run.ranMode} result={run.result} /> : null}

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
            <p className="eval-detail-placeholder">Select a case to see its full input, or add a new one.</p>
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
const CATEGORICAL_LIVE = new Set(["live_consolidation", "live_matching", "live_decomposition"]);

function dotFor(mode: RunMode["evalKey"], result: any): "ok" | "fail" | "contested" {
  if (result.marker === "[contested-split]") return "contested";  // stability wobble
  if (CATEGORICAL_LIVE.has(mode) && result.contested) {
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
                {meta(c).expected ? (
                  <span className="eval-case-item-expected">{String(meta(c).expected)}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function resultOk(ranMode: RunMode["evalKey"], r: any): boolean {
  if (ranMode === "live_scoring" || ranMode === "live_screening" || CATEGORICAL_LIVE.has(ranMode)) return r.passed;
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

function RestoredMarker(props: { run: LastEvalRun }): ReactNode {
  const { run } = props;
  return (
    <div className={`eval-restored${run.stale ? " stale" : ""}`}>
      {restoredLabel(run.evalKey)} — last run {relativeTime(run.ranAt)} · prompt {run.promptVersion || "—"}
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

// A run's headline block: pass/total + agreement (judge) / K (stability) / prompt+model.
function RunHeadline(props: { evalKey: RunMode["evalKey"]; result: any }): ReactNode {
  const { evalKey, result } = props;
  if (evalKey === "live_scoring") {
    return (
      <div className="eval-headline">
        {result.passed}/{result.total} passed · scoring {result.scoringPromptVersion} · {result.scoringModel}
      </div>
    );
  }
  if (CATEGORICAL_LIVE.has(evalKey)) {
    const pass = evalKey === "live_matching" ? "matching" : evalKey === "live_decomposition" ? "decomposition" : "consolidation";
    return (
      <div className="eval-headline">
        {result.passed}/{result.total} passed · {pass} {result.promptVersion} · {result.model}
      </div>
    );
  }
  if (evalKey === "live_screening") {
    return (
      <div className="eval-headline">
        {result.passed}/{result.total} passed · screening {result.promptVersion} · {result.model}
      </div>
    );
  }
  if (evalKey === "live_screening_stability") {
    return <div className="eval-headline">K={result.k} · screening {result.promptVersion} · {result.model}</div>;
  }
  if (evalKey === "stability") {
    return <div className="eval-headline">K={result.k} · {result.judgeModel}</div>;
  }
  if (evalKey === "live_consolidation_stability" || evalKey === "live_matching_stability" || evalKey === "live_decomposition_stability") {
    const pass = evalKey === "live_matching_stability" ? "matching" : evalKey === "live_decomposition_stability" ? "decomposition" : "consolidation";
    return <div className="eval-headline">K={result.k} · {pass} {result.promptVersion} · {result.model}</div>;
  }
  if (evalKey === "live_scoring_stability") {
    return <div className="eval-headline">K={result.k} · scoring {result.scoringPromptVersion} · {result.scoringModel}</div>;
  }
  const a = result.agreement;
  return (
    <div className="eval-headline">
      {a ? (
        <>
          agreement {a.nAgree}/{a.nScored} = {Math.round(a.agreement * 100)}%
          {a.kappa !== null ? ` · κ ${a.kappa.toFixed(2)}` : ""}
          {a.failureRecall !== null
            ? ` · failure-recall ${a.failureCaught}/${a.failureTotal} = ${Math.round(a.failureRecall * 100)}%`
            : ""}{" · "}
        </>
      ) : null}
      {result.judgeModel}
    </div>
  );
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
      {evalKey === "live_scoring" ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">score {r.score}</span> · {r.confidence} confidence
          {r.judgeVerdict ? <span className="eval-verdict"> · judge: {r.judgeVerdict}</span> : null}
          {r.evidence ? <Md text={`“${r.evidence}”`} className="eval-case-result-ev" /> : null}
          {r.failures?.map((f: string) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
        </div>
      ) : CATEGORICAL_LIVE.has(evalKey) ? (
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{r.expected}</span> → produced{" "}
          <span className="eval-mono">{r.verdict}</span>
          {r.judgeVerdict ? (
            <span className="eval-verdict">
              {" · "}judge: {r.judgeVerdict}
              {r.judgeVerdict !== r.expected ? " (disagrees)" : ""}
            </span>
          ) : null}
          {r.reason ? <Md text={r.reason} className="eval-case-result-ev" /> : null}
        </div>
      ) : evalKey === "live_screening" ? (
        <div className="eval-case-result-body">
          flags: <span className="eval-mono">{r.categories?.length ? r.categories.join(", ") : "none"}</span>
          {r.fires?.length ? <span className="eval-verdict">{" · "}expect: {r.fires.join(", ")}</span> : null}
          {r.absent?.length ? <span className="eval-verdict">{" · "}guard: no {r.absent.join(", ")}</span> : null}
          {r.failures?.map((f: string) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
        </div>
      ) : evalKey === "live_scoring_stability" ? (
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
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{r.expected}</span> → judge said{" "}
          <span className="eval-mono">{r.verdict}</span>
          {r.reason ? <Md text={r.reason} className="eval-case-result-ev" /> : null}
        </div>
      )}
    </div>
  );
}
