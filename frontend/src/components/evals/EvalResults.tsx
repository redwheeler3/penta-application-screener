import { evalCaseIdentity, savedRunSummary } from "../../api/evals";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { formatPacificDate, reasoningEffortLabel } from "../../format";
import type { EvalCaseOutcome, EvalConfiguration, LastEvalRun } from "../../types";
import { configurationChanges } from "./evalResultState";
import { evalCaseStatus, runSummary } from "./evalResultPresentation";

function restoredLabel(evalKey: string): string {
  const stability = evalKey.endsWith("_stability");
  const base = evalKey.replace(/_stability$/, "");
  const pass = base === "stability" ? "judge" : base;  // judge's stability key is bare "stability"
  const name = pass.charAt(0).toUpperCase() + pass.slice(1);
  return stability || evalKey === "stability" ? `${name} stability` : name;
}

// One self-contained line per run mode: label, result summary, when it ran, the prompt
// version, and the model. Turns amber when either identity no longer matches the current
// configuration. One line carries pass name + prompt + model.
export function EvalRunHistoryMarker(props: { run: LastEvalRun; current?: EvalConfiguration; totalCases: number }): ReactNode {
  const { run } = props;
  const summary = runSummary(savedRunSummary(run), props.totalCases);
  const current = props.current;
  const drift = current ? configurationChanges(run, current) : null;
  const corpusStale = current && (run.result.cases ?? []).some((item) =>
    item.inputFingerprint !== current.caseFingerprints[evalCaseIdentity(item.key, item.passName)]);
  const changes = current && drift ? [
    drift.promptStale ? `prompt is now ${current.promptVersion}` : "",
    corpusStale ? "case inputs or labels changed" : "",
    drift.modelStale ? `model is now ${current.modelId}` : "",
    drift.reasoningStale ? `reasoning is now ${current.reasoningEffort || "not applicable"}` : "",
  ].filter(Boolean).join(" · ") : "current configuration unconfirmed";
  const stale = Boolean(changes);
  return (
    <div className={`eval-restored${stale ? " stale" : ""}`}>
      {restoredLabel(run.evalKey)}
      {summary ? ` · ${summary}` : ""} · last run {relativeTime(run.ranAt)} · prompt {run.promptVersion || "—"}
      {run.modelId ? ` · ${run.modelId}` : ""}
      {run.modelId ? ` · reasoning ${reasoningEffortLabel(run.supportsReasoningEffort, run.reasoningEffort || null)}` : ""}
      {stale ? ` · ${changes}${current ? " — re-run to refresh" : ""}` : ""}
    </div>
  );
}

// Compact relative time, falling back to the date for older timestamps.
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
  return formatPacificDate(iso);
}

// Model-produced prose (evidence, reasons, per-run detail) is markdown — the AI writes it
// that way — so render it as such rather than dumping the raw source. `className` carries the
// surrounding style (muted/italic); `eval-md` tightens react-markdown's block margins so a
// one-liner doesn't get paragraph spacing. NB: deterministic, code-generated strings (the
// `failures` list) are NOT model text and stay plain.
function ModelText({ text, className }: { text: string; className?: string }): ReactNode {
  return (
    <div className={`eval-md${className ? ` ${className}` : ""}`}>
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}

// Per-run outcomes and reasoning make stability flips inspectable.
function StabilityRuns({ runs }: { runs?: { outcome: string; detail: string }[] }): ReactNode {
  if (!runs?.length) return null;
  return (
    <ol className="eval-stability-runs">
      {runs.map((run, i) => (
        <li key={i}>
          <span className="eval-mono">{run.outcome}</span>
          {run.detail ? <ModelText text={run.detail} className="eval-case-result-ev" /> : null}
        </li>
      ))}
    </ol>
  );
}

export function EvalCaseResultView({ outcome, current = true }: { outcome: EvalCaseOutcome; current?: boolean }): ReactNode {
  const status = current ? evalCaseStatus(outcome) : "empty";
  const heading = !current ? "not current" : status === "contested" ? "contested" : status === "ok" ? "passed" : "failed";
  return (
    <div className={`eval-case-result ${status}`}>
      <span className="eval-case-result-head">
        <span className={`eval-case-dot ${status}`} />
        {heading}
      </span>
      <ResultBody {...outcome} />
    </div>
  );
}

function ResultBody({ mode, result }: EvalCaseOutcome): ReactNode {
  switch (mode) {
    case "scoring":
      return (
        <div className="eval-case-result-body">
          <span className="eval-mono">{result.score === null ? "No score returned" : `score ${result.score}`}</span>
          {result.score !== null ? ` · ${result.confidence} confidence` : null}
          {result.evidence ? <ModelText text={`“${result.evidence}”`} className="eval-case-result-ev" /> : null}
          {result.failures.map((f) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
        </div>
      );
    case "consolidation":
    case "matching":
    case "decomposition":
      return (
        <div className="eval-case-result-body">
          expected <span className="eval-mono">{result.expected}</span> → produced{" "}
          <span className="eval-mono">{result.verdict}</span>
          {result.reason ? <ModelText text={result.reason} className="eval-case-result-ev" /> : null}
        </div>
      );
    case "screening":
      return (
        <div className="eval-case-result-body">
          flags: <span className="eval-mono">{result.categories.length ? result.categories.join(", ") : "none"}</span>
          {result.fires.length ? <span className="eval-verdict">{" · "}expect: {result.fires.join(", ")}</span> : null}
          {result.absent.length ? <span className="eval-verdict">{" · "}guard: no {result.absent.join(", ")}</span> : null}
          {result.contested ? <span className="eval-verdict">{" · "}contested (a miss is expected)</span> : null}
          {result.failures.map((f) => (
            <div key={f} className="eval-check-detail">
              {f}
            </div>
          ))}
          {result.reason ? <ModelText text={result.reason} className="eval-case-result-ev" /> : null}
        </div>
      );
    case "scoring_stability":
      return (
        <div className="eval-case-result-body">
          <span className="eval-mono">{result.marker}</span> {Math.round(result.agreement * 100)}% agreement over K —{" "}
          {Object.entries(result.tally).map(([v, n]) => `${v}×${n}`).join(", ")}
          <span className="eval-verdict">
            {" · "}{result.scoreMin === null || result.scoreMax === null
              ? "No scores returned"
              : `score ${result.scoreMin.toFixed(2)}..${result.scoreMax.toFixed(2)}`}
          </span>
          <StabilityRuns runs={result.runs} />
        </div>
      );
    case "judge":
      return (
        // Use the backend verdict: a scoring judge compares a numeric score to a band,
        // so its displayed labels cannot be compared as strings.
        <div className="eval-case-result-body">
          {result.contested ? "leaning" : "label"} <span className="eval-mono">{result.humanLabel}</span> → judge said{" "}
          <span className="eval-mono">{result.judgeLabel}</span>
          {result.marker === "[ok]" ? "" : result.contested ? " (contested — both defensible)" : " (disagrees)"}
          {result.detail ? <ModelText text={result.detail} className="eval-case-result-ev" /> : null}
          {/* Why the human chose this label — shown on a divergence, where it's the context
              for deciding whether the label or the judge is the one to trust. */}
          {result.marker !== "[ok]" && result.labelRationale ? (
            <ModelText text={`_Label rationale:_ ${result.labelRationale}`} className="eval-case-result-ev" />
          ) : null}
        </div>
      );
    default:
      return (
        <div className="eval-case-result-body">
          <span className="eval-mono">{result.marker}</span> {Math.round(result.agreement * 100)}% agreement over K —{" "}
          {Object.entries(result.tally).map(([v, n]) => `${v}×${n}`).join(", ")}
          <StabilityRuns runs={result.runs} />
        </div>
      );
  }
}
