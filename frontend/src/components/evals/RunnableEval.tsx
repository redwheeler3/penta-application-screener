import { type ReactNode, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchEvalCases, runEval, saveEvalCase, streamNdjson } from "../../api";
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

export type RunMode = { evalKey: "live_scoring" | "judge" | "stability"; label: string; rowLabel: string; calls: number };

type RunState = { running: boolean; thinking: string; result: any | null; ranMode: RunMode["evalKey"]; error: string | null };
type Confirm = { mode: RunMode; caseKey?: string; calls: number } | null;

export function RunnableEval(props: {
  // "live_scoring" | "judge" — the fixture whose cases we read/edit (stability shares judge's).
  caseEvalKey: "live_scoring" | "judge";
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
  const thinkingRef = useRef<HTMLDivElement>(null);

  const loadCases = () => {
    fetchEvalCases(caseEvalKey)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCases(d?.cases ?? []));
  };
  useEffect(loadCases, [caseEvalKey]);
  useEffect(() => {
    const el = thinkingRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  async function doRun(mode: RunMode, caseKey?: string) {
    setRun({ running: true, thinking: "", result: null, ranMode: mode.evalKey, error: null });
    try {
      const resp = await runEval(mode.evalKey, { caseKey });
      if (!resp.ok || !resp.body) {
        setRun((r) => ({ ...r, running: false, error: `Request failed (${resp.status})` }));
        return;
      }
      await streamNdjson(resp.body, (e) => {
        if (e.type === "thinking") setRun((r) => ({ ...r, thinking: r.thinking + e.text }));
        else if (e.type === "summary") setRun((r) => ({ ...r, running: false, result: e.result }));
        else if (e.type === "error") setRun((r) => ({ ...r, running: false, error: e.message }));
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

  const resultByKey: Record<string, any> = {};
  if (run.result?.cases) for (const c of run.result.cases) resultByKey[c.key] = c;

  const selectedCase = cases?.find((c) => c.key === selected) ?? null;
  const perCaseCalls = (m: RunMode) => (cases?.length ? Math.max(1, Math.round(m.calls / cases.length)) : 1);

  return (
    <div className="eval-section">
      <p className="eval-card-desc">{props.description}</p>

      {confirm ? (
        <InlineConfirm
          title={confirm.caseKey ? `Run case “${confirm.caseKey}”?` : `${confirm.mode.label}?`}
          body={`This makes ~${confirm.calls} model call${confirm.calls === 1 ? "" : "s"} and costs real money.`}
          onConfirm={() => {
            const t = confirm;
            setConfirm(null);
            void doRun(t.mode, t.caseKey);
          }}
          onCancel={() => setConfirm(null)}
        />
      ) : null}

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
      {run.result ? <RunHeadline evalKey={run.ranMode} result={run.result} /> : null}

      <div className="eval-master-detail">
        <div className="eval-master">
          <CaseList
            cases={cases}
            groupBy={props.groupBy}
            selected={selected}
            resultByKey={resultByKey}
            ranMode={run.ranMode}
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
                    className="secondary-button"
                    disabled={run.running}
                    onClick={() => setConfirm({ mode: m, caseKey: String(selectedCase.key), calls: perCaseCalls(m) })}
                  >
                    {m.rowLabel}
                  </button>
                ))}
                <button
                  type="button"
                  className="secondary-button"
                  disabled={run.running}
                  onClick={() => {
                    setSaveError(null);
                    setEditing({ existing: selectedCase });
                  }}
                >
                  Edit
                </button>
              </div>
              {resultByKey[String(selectedCase.key)] ? (
                <CaseResult evalKey={run.ranMode} result={resultByKey[String(selectedCase.key)]} />
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
  resultByKey: Record<string, any>;
  ranMode: RunMode["evalKey"];
  onSelect: (key: string) => void;
}): ReactNode {
  const { cases } = props;
  if (cases === null) return <p className="eval-hint">Loading cases…</p>;
  if (!cases.length) return <p className="eval-hint">No cases yet.</p>;

  const groups: { heading: string | null; items: Record<string, unknown>[] }[] = [];
  if (props.groupBy) {
    const byGroup = new Map<string, Record<string, unknown>[]>();
    for (const c of cases) {
      const g = String(c[props.groupBy] ?? "consolidation"); // judge default pass
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
            const r = props.resultByKey[key];
            const dot = r ? (resultOk(props.ranMode, r) ? "ok" : "fail") : null;
            return (
              <button
                key={key}
                type="button"
                className={`eval-case-item${props.selected === key ? " selected" : ""}`}
                onClick={() => props.onSelect(key)}
              >
                {dot ? <span className={`eval-case-dot ${dot}`} aria-hidden="true" /> : null}
                <span className="eval-case-item-key">{key}</span>
                {c.expected ? <span className="eval-case-item-expected">{String(c.expected)}</span> : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function resultOk(ranMode: RunMode["evalKey"], r: any): boolean {
  if (ranMode === "live_scoring") return r.passed;
  if (ranMode === "stability") return r.marker === "[stable]";
  return r.marker === "[ok]";
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
  const ok = resultOk(evalKey, r);
  return (
    <div className={`eval-case-result ${ok ? "ok" : "fail"}`}>
      <span className="eval-case-result-head">{ok ? "✓ passed" : "✗ failed"}</span>
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
