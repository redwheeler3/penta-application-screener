import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  fetchEvalCases,
  fetchEvalCatalog,
  fetchEvalInvariants,
  runEval,
  saveEvalCase,
  streamNdjson,
} from "../api";
import type { EvalDescriptor, InvariantsResult } from "../types";

// The Evals tab — the in-UI eval cockpit (developer/operator surface, not committee-
// facing). Three subtabs: Invariants (free), Live scoring (golden dataset), and Judge
// (the judge case set, run two ways — a one-pass judge+agreement run and a K-repeat
// stability run — since both read the SAME cases). Each runnable subtab shows its cases
// (the input dataset, from the committed JSON fixture) in a table, run actions (whole-set
// and per-row), the model's reasoning streamed live, and results inline. Cases are
// editable; a save writes back to the versioned fixture file (commit to git deliberately).
//
// Reuses the app's real plumbing (fidelity): the NDJSON stream reader the Rank/Screen jobs
// use, and the workflow's `.run-confirm` inline card before a spend.

type RunEvalKey = "live_scoring" | "judge" | "stability";
type SubtabKey = "invariants" | "live_scoring" | "judge";

// A run "mode" a subtab offers: which backend eval, its whole-set label, a short per-row
// label (for the case table's per-row run links), and its whole-set call estimate.
type RunMode = { evalKey: RunEvalKey; label: string; rowLabel: string; calls: number };

type ConfirmTarget = { mode: RunMode; caseKey?: string; caseCalls?: number } | null;

type RunState = { running: boolean; thinking: string; result: any | null; error: string | null };
const EMPTY_RUN: RunState = { running: false, thinking: "", result: null, error: null };

export function EvalsView(): ReactNode {
  const [catalog, setCatalog] = useState<EvalDescriptor[] | null>(null);
  const [active, setActive] = useState<SubtabKey>("invariants");

  useEffect(() => {
    fetchEvalCatalog()
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setCatalog(d.evals));
  }, []);

  if (!catalog) return <p className="eval-hint">Loading evals…</p>;
  const calls = (k: string) => catalog.find((e) => e.key === k)?.estimatedCalls ?? 0;
  const desc = (k: string) => catalog.find((e) => e.key === k)?.description ?? "";

  const subtabs: { key: SubtabKey; label: string }[] = [
    { key: "invariants", label: "Invariants" },
    { key: "live_scoring", label: "Live scoring" },
    { key: "judge", label: "Judge" },
  ];

  return (
    <div className="evals-view">
      <div className="evals-header">
        <h3>Evals</h3>
        <p className="eval-hint">
          Quality checks over synthetic data (not committee-facing). Invariants are free; the
          others make real model calls, confirmed before running, and stream the model’s
          reasoning as it goes. Every run is saved.
        </p>
      </div>

      <div className="insights-subtabs" role="tablist" aria-label="Evals">
        {subtabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            className={`insights-subtab${active === t.key ? " active" : ""}`}
            onClick={() => setActive(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="insights-subtab-body">
        {active === "invariants" ? (
          <InvariantsSection />
        ) : active === "live_scoring" ? (
          <RunnableSection
            subtab="live_scoring"
            caseEvalKey="live_scoring"
            description={desc("live_scoring")}
            modes={[{ evalKey: "live_scoring", label: "Run live scoring", rowLabel: "run", calls: calls("live_scoring") }]}
          />
        ) : (
          <RunnableSection
            subtab="judge"
            caseEvalKey="judge"
            description="The judge case set, run two ways over the SAME cases: a one-pass judge run reports judge-vs-human agreement; a stability run judges each case K times to see if any verdict flips."
            modes={[
              { evalKey: "judge", label: "Run judge + agreement", rowLabel: "judge", calls: calls("judge") },
              { evalKey: "stability", label: "Run stability (K=5)", rowLabel: "stability", calls: calls("stability") },
            ]}
          />
        )}
      </div>
    </div>
  );
}

// --- Invariants (free, no cases to edit) ------------------------------------

function InvariantsSection(): ReactNode {
  const [result, setResult] = useState<InvariantsResult | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    fetchEvalInvariants()
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        setResult(d);
        setLoading(false);
      });
  };
  useEffect(load, []);

  return (
    <div className="eval-section">
      <div className="eval-section-head">
        <p className="eval-card-desc">
          Deterministic checks over the committed baseline fixture (poles present, no protected
          attributes). Free, instant — runs over the last blessed Rank.
        </p>
        <button type="button" className="secondary-button" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {result?.hasFixture === false ? (
        <p className="eval-hint">No baseline fixture recorded yet.</p>
      ) : result ? (
        <div className="eval-result">
          <div className="eval-headline">{result.dimensions} dimensions in the baseline</div>
          <table className="eval-table">
            <thead>
              <tr>
                <th></th>
                <th>Invariant</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {result.invariants.map((inv) => (
                <tr key={inv.check} className={inv.passed ? "ok" : "fail"}>
                  <td>{inv.passed ? "✓" : "✗"}</td>
                  <td>{inv.check}</td>
                  <td>
                    {inv.violations.map((v) => (
                      <div key={v} className="eval-check-detail">
                        {v}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="eval-hint">Loading…</p>
      )}
    </div>
  );
}

// --- A runnable subtab: cases + whole-set/per-row runs + results ------------

function RunnableSection(props: {
  subtab: SubtabKey;
  caseEvalKey: "live_scoring" | "judge";
  description: string;
  modes: RunMode[];
}): ReactNode {
  const { caseEvalKey, modes } = props;
  const [cases, setCases] = useState<any[] | null>(null);
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const [confirm, setConfirm] = useState<ConfirmTarget>(null);
  const [editing, setEditing] = useState<{ existing: any | null } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Which run mode produced the current result (so the table renders the right columns);
  // and, for a per-row run, which single case it scoped to.
  const [ranMode, setRanMode] = useState<RunEvalKey>(modes[0].evalKey);
  const thinkingRef = useRef<HTMLPreElement>(null);

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
    setRanMode(mode.evalKey);
    setRun({ ...EMPTY_RUN, running: true });
    try {
      const resp = await runEval(mode.evalKey, { caseKey });
      if (!resp.ok || !resp.body) {
        setRun({ ...EMPTY_RUN, error: `Request failed (${resp.status})` });
        return;
      }
      await streamNdjson(resp.body, (e) => {
        if (e.type === "thinking") setRun((r) => ({ ...r, thinking: r.thinking + e.text }));
        else if (e.type === "summary") setRun((r) => ({ ...r, running: false, result: e.result }));
        else if (e.type === "error") setRun((r) => ({ ...r, running: false, error: e.message }));
      });
      setRun((r) => (r.running ? { ...r, running: false } : r));
    } catch (err) {
      setRun({ ...EMPTY_RUN, error: String(err) });
    }
  }

  async function persistCase(evalCase: unknown) {
    setSaveError(null);
    const resp = await saveEvalCase(caseEvalKey, evalCase);
    if (resp.ok) {
      setCases((await resp.json()).cases);
      setEditing(null);
    } else {
      const problem = await resp.json().catch(() => null);
      setSaveError(problem?.detail ?? `Save failed (${resp.status})`);
    }
  }

  // Per-row run: one link per mode (e.g. "judge" / "stability"), each scoped to that case.
  // Estimate a single case's calls from the whole-set estimate over the case count.
  const perCaseCalls = (mode: RunMode) =>
    cases && cases.length ? Math.max(1, Math.round(mode.calls / cases.length)) : 1;

  return (
    <div className="eval-section">
      <div className="eval-section-head">
        <p className="eval-card-desc">{props.description}</p>
      </div>

      {confirm ? (
        <div className="run-confirm eval-run-confirm">
          <div className="run-confirm-body">
            <strong>
              {confirm.caseKey ? `Run case “${confirm.caseKey}”?` : `${confirm.mode.label}?`}
            </strong>
            <p>
              This makes ~{confirm.caseKey ? confirm.caseCalls : confirm.mode.calls} model call
              {(confirm.caseKey ? confirm.caseCalls : confirm.mode.calls) === 1 ? "" : "s"} and costs
              real money.
            </p>
          </div>
          <div className="run-confirm-actions">
            <button
              type="button"
              className="primary-button"
              onClick={() => {
                const t = confirm;
                setConfirm(null);
                void doRun(t.mode, t.caseKey);
              }}
            >
              Confirm &amp; run
            </button>
            <button type="button" className="secondary-button" onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <div className="eval-section-actions">
        {modes.map((m) => (
          <button
            key={m.evalKey}
            type="button"
            className="primary-button"
            disabled={run.running}
            onClick={() => setConfirm({ mode: m })}
          >
            {m.label} (~{m.calls})
          </button>
        ))}
        <button
          type="button"
          className="secondary-button"
          disabled={run.running}
          onClick={() => {
            setSaveError(null);
            setEditing({ existing: null });
          }}
        >
          + Add case
        </button>
      </div>

      {run.error ? <p className="eval-error">{run.error}</p> : null}
      {run.running || run.thinking ? (
        <pre ref={thinkingRef} className="eval-thinking">
          {run.thinking || "…"}
        </pre>
      ) : null}

      <CaseTable
        subtab={props.subtab}
        ranMode={ranMode}
        cases={cases}
        result={run.result}
        disabled={run.running}
        modes={modes}
        onEdit={(c) => {
          setSaveError(null);
          setEditing({ existing: c });
        }}
        onRunCase={(c, mode) =>
          setConfirm({ mode, caseKey: c.key, caseCalls: perCaseCalls(mode) })
        }
      />

      {editing ? (
        <CaseEditor
          evalKey={caseEvalKey}
          existing={editing.existing}
          error={saveError}
          onCancel={() => setEditing(null)}
          onSave={persistCase}
        />
      ) : null}
    </div>
  );
}

// --- Case table: input data (always) + result columns (after a run) ---------

function CaseTable(props: {
  subtab: SubtabKey;
  ranMode: RunEvalKey;
  cases: any[] | null;
  result: any | null;
  disabled: boolean;
  modes: RunMode[];
  onEdit: (c: any) => void;
  onRunCase: (c: any, mode: RunMode) => void;
}): ReactNode {
  const { subtab, ranMode, cases, result } = props;
  if (cases === null) return <p className="eval-hint">Loading cases…</p>;
  if (!cases.length) return <p className="eval-hint">No cases yet.</p>;

  const byKey: Record<string, any> = {};
  if (result?.cases) for (const c of result.cases) byKey[c.key] = c;

  return (
    <table className="eval-table eval-cases-table">
      <thead>
        <tr>
          <th>Case</th>
          <th>Input</th>
          <th>Expected</th>
          <th>Result</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => {
          const r = byKey[c.key];
          return (
            <tr key={c.key} className={r ? (resultOk(ranMode, r) ? "ok" : "fail") : ""}>
              <td className="eval-cell-key">{c.key}</td>
              <td className="eval-cell-input">{summarizeInput(subtab, c)}</td>
              <td>{summarizeExpected(subtab, c)}</td>
              <td>{r ? summarizeResult(ranMode, r) : <span className="eval-muted">—</span>}</td>
              <td className="eval-cell-actions">
                {props.modes.map((m) => (
                  <button
                    key={m.evalKey}
                    type="button"
                    className="eval-link"
                    disabled={props.disabled}
                    onClick={() => props.onRunCase(c, m)}
                  >
                    {m.rowLabel}
                  </button>
                ))}
                <button type="button" className="eval-link" disabled={props.disabled} onClick={() => props.onEdit(c)}>
                  edit
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function summarizeInput(subtab: SubtabKey, c: any): ReactNode {
  if (subtab === "live_scoring") {
    const essays = c.applicant?.essays ?? {};
    const text = Object.values(essays).join(" ");
    return (
      <>
        <div className="eval-cell-dim">{c.dimension?.name ?? c.dimension?.key}</div>
        <div className="eval-cell-sub">{text.slice(0, 90) || "(facts only)"}</div>
      </>
    );
  }
  const ev = c.evidence ?? {};
  const bits = ev.cited_evidence ?? ev.definition_a ?? c.task;
  return <div className="eval-cell-sub">{String(bits ?? "").slice(0, 110)}</div>;
}

function summarizeExpected(subtab: SubtabKey, c: any): ReactNode {
  if (subtab === "live_scoring") {
    const parts = Object.entries(c.expect ?? {}).map(([k, v]) => `${k}=${v}`);
    return <span className="eval-mono">{parts.join(", ")}</span>;
  }
  return <span className="eval-mono">{c.expected}</span>;
}

function summarizeResult(ranMode: RunEvalKey, r: any): ReactNode {
  if (ranMode === "live_scoring") {
    return (
      <>
        <span className="eval-mono">{r.score}</span> {r.confidence}
        {r.judgeVerdict ? <span className="eval-verdict"> · {r.judgeVerdict}</span> : null}
        {r.failures?.map((f: string) => (
          <div key={f} className="eval-check-detail">
            {f}
          </div>
        ))}
      </>
    );
  }
  if (ranMode === "stability") {
    return (
      <span className="eval-mono">
        {r.marker} {Math.round(r.agreement * 100)}%
      </span>
    );
  }
  return (
    <span className="eval-mono">
      {r.marker} {r.verdict}
    </span>
  );
}

function resultOk(ranMode: RunEvalKey, r: any): boolean {
  if (ranMode === "live_scoring") return r.passed;
  if (ranMode === "stability") return r.marker === "[stable]";
  return r.marker === "[ok]";
}

// --- Case editor: raw JSON, validated server-side --------------------------

function CaseEditor(props: {
  evalKey: "live_scoring" | "judge";
  existing: any | null;
  error: string | null;
  onCancel: () => void;
  onSave: (c: unknown) => void;
}): ReactNode {
  const template =
    props.existing ??
    (props.evalKey === "live_scoring"
      ? {
          key: "",
          note: "",
          applicant: { facts: {}, essays: { essay: "" } },
          dimension: { key: "", name: "", definition: "", high_end: "", low_end: "" },
          expect: { score_equals: 0.0 },
        }
      : {
          key: "",
          title: "",
          task: "Given the dimension and the applicant's cited evidence, decide whether the score is SUPPORTED or UNSUPPORTED by that evidence.",
          evidence: { dimension: "", dimension_definition: "", cited_evidence: "", score: 0.0 },
          expected: "supported",
        });
  const [text, setText] = useState(() => JSON.stringify(template, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);

  function save() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setParseError(String(e));
      return;
    }
    setParseError(null);
    props.onSave(parsed);
  }

  return (
    <div className="eval-editor">
      <div className="eval-editor-head">
        <strong>{props.existing ? `Edit case: ${props.existing.key}` : "Add case"}</strong>
        <span className="eval-hint">
          Writes to the committed fixture file — commit it to git deliberately.
        </span>
      </div>
      <textarea
        className="eval-editor-text"
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        rows={16}
      />
      {parseError ? <p className="eval-error">Invalid JSON: {parseError}</p> : null}
      {props.error ? <p className="eval-error">{props.error}</p> : null}
      <div className="run-confirm-actions">
        <button type="button" className="primary-button" onClick={save}>
          Save case
        </button>
        <button type="button" className="secondary-button" onClick={props.onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
