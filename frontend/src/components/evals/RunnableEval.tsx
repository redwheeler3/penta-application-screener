import { useCommitteeApi } from "../../api/identity";
import { type ReactNode, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import * as evalsApi from "../../api/evals";
import { readProblem } from "../../api/problems";
import { useRequestScope } from "../../hooks/useRequestScope";
import type {
  EvalCaseOutcome,
  EvalFixtureKey,
  EvalRunMode,
  EvalRunOption,
} from "../../types";
import { EvalCaseList } from "./EvalCaseList";
import { EvalCaseResultView, EvalRunHistoryMarker } from "./EvalResults";
import { EvalCaseDetail } from "./EvalCaseDetail";
import { EvalCaseEditor } from "./EvalCaseEditor";
import { InlineConfirm } from "./InlineConfirm";
import type { FieldObject } from "./StructuredFields";
import { useEvalRunner } from "./useEvalRunner";

// A runnable eval subtab (a pass, or Judge). Master-detail: a case LIST on the left
// (grouped, e.g. judge cases by the production pass they exercise), a full case DETAIL /
// EDITOR on the right. Whole-set run buttons (one per mode) and per-case run links, both
// spend-confirmed inline (the workflow card, not window.confirm). The model's reasoning
// streams as rendered markdown; results merge back onto each case row + into the detail.

export type RunMode = EvalRunOption;
type Confirm = { mode: RunMode; caseKey?: string; calls: number } | null;

export function RunnableEval(props: {
  // The fixture whose cases we read/edit (a pass's stability mode shares its golden set).
  caseEvalKey: EvalFixtureKey;
  // The eval keys whose last run restores this tab on remount (Scoring: ["scoring", "scoring_stability"];
  // Judge: ["judge", "stability"] — the two share the tab, so the newer of the two shows).
  runKeys: EvalRunMode[];
  description: string;
  modes: RunMode[];
  // Group cases under headings by this case field (e.g. "pass" for judge); undefined = flat.
  groupBy?: string;
  // Whether a SELECTED case can be edited here. Defaults to true. The Judge tab sets this true
  // too: a judge-tab edit is routed to the case's own pass file (by metadata.pass), so it lands
  // in the same golden file the pass tab writes to.
  editable?: boolean;
  // Whether NEW cases can be added here ("+ Add case"). Defaults to `editable`. The Judge tab
  // passes false: it aggregates five families, so "add" has no single target file/shape —
  // add a new case from its own pass tab. (Editing an existing case is unambiguous: it already
  // carries metadata.pass.)
  addable?: boolean;
  // Extra content rendered above the run controls (the Judge tab's per-pass background editors).
  header?: ReactNode;
  // Save outcomes surface as the app's standard toasts (success auto-dismisses, error persists),
  // matching Settings/Rank — not inline text.
  onToast: (message: string) => void;
  onError: (message: string) => void;
}): ReactNode {
  const { saveEvalCase } = useCommitteeApi(evalsApi);

  const { caseEvalKey, modes } = props;
  const editable = props.editable ?? true;
  const addable = props.addable ?? editable;
  const [selected, setSelected] = useState<string | null>(null); // selected case key
  const [editing, setEditing] = useState<{ existing: Record<string, unknown> | null } | null>(null);
  const saves = useRef<Promise<void>>(Promise.resolve());
  const saveScope = useRequestScope(caseEvalKey);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const { cases, setCases, run, caseResults, restored, runMode } = useEvalRunner({
    caseEvalKey,
    runKeys: props.runKeys,
  });
  const thinkingRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = thinkingRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  function persistCase(evalCase: FieldObject): Promise<string | null> {
    const isCurrent = saveScope.capture();
    // Responses contain the whole fixture: serialize saves so an older list cannot
    // replace the result of a later save. Editor lifetime owns closing or keeping drafts.
    const result = saves.current.then(async () => {
      if (!isCurrent()) return "This case tab is no longer active.";
      try {
        const response = await saveEvalCase(caseEvalKey, evalCase);
        if (!isCurrent()) return "This case tab is no longer active.";
        if (!response.ok) {
          const problem = await readProblem(response) ?? `Save failed (${response.status})`;
          if (isCurrent()) props.onError(`Could not save case “${String(evalCase.key)}”: ${problem}`);
          return problem;
        }
        const body = await response.json();
        if (!isCurrent()) return "This case tab is no longer active.";
        setCases(body.cases);
        props.onToast(`Case “${String(evalCase.key)}” saved — commit the golden file to keep it.`);
        return null;
      } catch {
        const problem = `Could not confirm the save for case “${String(evalCase.key)}”. Please try again.`;
        if (isCurrent()) props.onError(problem);
        return problem;
      }
    });
    saves.current = result.then(() => {});
    return result;
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
        void runMode(t.mode, t.caseKey);
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
        {addable ? (
          <button
            type="button"
            className="secondary-button"
            disabled={run.running}
            onClick={() => {
              setEditing({ existing: null });
              setSelected(null);
            }}
          >
            + Add case
          </button>
        ) : null}
      </div>

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
            <EvalRunHistoryMarker key={r.evalKey} run={r} totalCases={cases?.length ?? 0} />
          ))}
        </div>
      ) : null}

      <div className="eval-master-detail">
        <div className="eval-master">
          <EvalCaseList
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
              key={editing.existing === null ? `${caseEvalKey}:add` : `${caseEvalKey}:edit:${editing.existing.key}`}
              evalKey={caseEvalKey}
              existing={editing.existing}
              onCancel={() => setEditing(null)}
              onSave={persistCase}
              onSaved={(key) => { setSelected(key); setEditing(null); }}
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
                    .map((m) => ({ m, result: selectedResult[m.evalKey] }))
                    .filter((x): x is { m: RunMode; result: EvalCaseOutcome } => !!x.result)
                    .map(({ m, result }) => (
                      <EvalCaseResultView key={m.evalKey} outcome={result} />
                    ))
                : null}
              <EvalCaseDetail evalCase={selectedCase} />
            </div>
          ) : (
            <p className="eval-detail-placeholder">
              {addable ? "Select a case to see its full input, or add a new one." : "Select a case to see its full input."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
