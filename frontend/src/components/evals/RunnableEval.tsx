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

export type RunMode = { evalKey: "live_scoring" | "live_consolidation" | "judge" | "stability"; label: string; rowLabel: string; calls: number };

type RunState = { running: boolean; thinking: string; result: any | null; ranMode: RunMode["evalKey"]; error: string | null };
type Confirm = { mode: RunMode; caseKey?: string; calls: number } | null;

export function RunnableEval(props: {
  // The fixture whose cases we read/edit (stability shares judge's; live-stability, when it
  // lands, shares its pass's golden set).
  caseEvalKey: "live_scoring" | "live_consolidation" | "judge";
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
  // Per-case results, keyed by case key, each with the mode it was run under (so a case run
  // under judge vs. stability shows the right dot). A WHOLE-SET run replaces this map; a
  // PER-CASE run merges just its one entry — so running one case never wipes the others'
  // dots/results (the bug where running case B cleared case A's green result).
  const [caseResults, setCaseResults] = useState<Record<string, { ranMode: RunMode["evalKey"]; result: any }>>({});
  // Set when the shown result was REHYDRATED from a past run (not this session); null for a
  // live run. Drives the "last run · prompt" marker so history is never mistaken for fresh.
  const [restored, setRestored] = useState<LastEvalRun | null>(null);
  const thinkingRef = useRef<HTMLDivElement>(null);

  const loadCases = () => {
    fetchEvalCases(caseEvalKey)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCases(d?.cases ?? []));
  };
  useEffect(loadCases, [caseEvalKey]);

  // On mount, restore the last persisted run for this tab so switching subtabs and coming
  // back shows what you last saw (result + case dots) instead of a blank tab. Thinking is
  // not restored (per the outcome-not-replay choice); a fresh run clears `restored`.
  useEffect(() => {
    let live = true;
    fetchLastEvalRun(props.runKeys)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: LastEvalRun | null) => {
        if (!live || !d?.found) return;
        setRestored(d);
        setRun((r) => ({ ...r, result: d.result, ranMode: d.evalKey as RunMode["evalKey"] }));
        // Seed the per-case dots/results from the restored run too.
        const cases: any[] = d.result?.cases ?? [];
        const seeded: Record<string, { ranMode: RunMode["evalKey"]; result: any }> = {};
        for (const c of cases) seeded[c.key] = { ranMode: d.evalKey as RunMode["evalKey"], result: c };
        setCaseResults(seeded);
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
    setRestored(null); // a live run supersedes any rehydrated history
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
          // Fold the per-case results into the accumulated map: a WHOLE-SET run replaces it;
          // a PER-CASE run merges only its one case, so it never clears the other cases' dots.
          const cases: any[] = e.result?.cases ?? [];
          setCaseResults((prev) => {
            const next = caseKey ? { ...prev } : {};
            for (const c of cases) next[c.key] = { ranMode: mode.evalKey, result: c };
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
      {restored?.found ? <RestoredMarker run={restored} /> : null}
      {run.result ? <RunHeadline evalKey={run.ranMode} result={run.result} /> : null}

      <div className="eval-master-detail">
        <div className="eval-master">
          <CaseList
            cases={cases}
            groupBy={props.groupBy}
            selected={selected}
            caseResults={caseResults}
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
                    {m.rowLabel}
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
              {selectedResult ? (
                <CaseResult evalKey={selectedResult.ranMode} result={selectedResult.result} />
              ) : null}
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

// The case list, optionally grouped by a field (judge: by production pass).
function CaseList(props: {
  cases: Record<string, unknown>[] | null;
  groupBy?: string;
  selected: string | null;
  caseResults: Record<string, { ranMode: RunMode["evalKey"]; result: any }>;
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
            const entry = props.caseResults[key];
            // A contested consolidation case is informational (◐), never a red fail dot.
            const dot = entry
              ? entry.ranMode === "live_consolidation" && entry.result.contested
                ? "contested"
                : resultOk(entry.ranMode, entry.result) ? "ok" : "fail"
              : null;
            return (
              <button
                key={key}
                type="button"
                className={`eval-case-item${props.selected === key ? " selected" : ""}`}
                onClick={() => props.onSelect(key)}
              >
                {dot ? <span className={`eval-case-dot ${dot}`} aria-hidden="true" /> : null}
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
  if (ranMode === "live_scoring" || ranMode === "live_consolidation") return r.passed;
  if (ranMode === "stability") return r.marker === "[stable]";
  return r.marker === "[ok]";
}

// Marks a REHYDRATED result as history (not a fresh run): when it ran + which prompt, and
// an amber warning when that prompt no longer matches the current one (so a stale result is
// never read as live). A fresh run clears it.
function RestoredMarker(props: { run: LastEvalRun }): ReactNode {
  const { run } = props;
  return (
    <div className={`eval-restored${run.stale ? " stale" : ""}`}>
      Last run {relativeTime(run.ranAt)} · prompt {run.promptVersion || "—"}
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
  if (evalKey === "live_consolidation") {
    return (
      <div className="eval-headline">
        {result.passed}/{result.total} passed · consolidation {result.promptVersion} · {result.model}
      </div>
    );
  }
  if (evalKey === "stability") {
    return <div className="eval-headline">K={result.k} · {result.judgeModel}</div>;
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

// One case's result, shown in the detail pane above its input.
function CaseResult(props: { evalKey: RunMode["evalKey"]; result: any }): ReactNode {
  const { evalKey, result: r } = props;
  // A contested consolidation case has no honest pass/fail on verdict direction — show it
  // as informational (◐), never a red ✗.
  const contested = evalKey === "live_consolidation" && r.contested;
  const ok = resultOk(evalKey, r);
  const cls = contested ? "contested" : ok ? "ok" : "fail";
  const head = contested ? "◐ contested" : ok ? "✓ passed" : "✗ failed";
  return (
    <div className={`eval-case-result ${cls}`}>
      <span className="eval-case-result-head">{head}</span>
      {evalKey === "live_scoring" ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">score {r.score}</span> · {r.confidence} confidence
          {r.judgeVerdict ? <span className="eval-verdict"> · judge: {r.judgeVerdict}</span> : null}
          {r.evidence ? <div className="eval-case-result-ev">“{r.evidence}”</div> : null}
          {r.failures?.map((f: string) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
        </div>
      ) : evalKey === "live_consolidation" ? (
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{r.expected}</span> → produced{" "}
          <span className="eval-mono">{r.verdict}</span>
          {r.judgeVerdict ? (
            <span className="eval-verdict">
              {" · "}judge: {r.judgeVerdict}
              {r.judgeVerdict !== r.expected ? " (disagrees)" : ""}
            </span>
          ) : null}
          {r.reason ? <div className="eval-case-result-ev">{r.reason}</div> : null}
        </div>
      ) : evalKey === "stability" ? (
        <div className="eval-case-result-body">
          <span className="eval-mono">{r.marker}</span> {Math.round(r.agreement * 100)}% agreement over K —{" "}
          {Object.entries(r.tally).map(([v, n]) => `${v}×${n}`).join(", ")}
        </div>
      ) : (
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{r.expected}</span> → judge said{" "}
          <span className="eval-mono">{r.verdict}</span>
          {r.reason ? <div className="eval-case-result-ev">{r.reason}</div> : null}
        </div>
      )}
    </div>
  );
}
