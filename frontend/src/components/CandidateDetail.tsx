import { ChevronLeft, Printer } from "lucide-react";
import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { FLAG_CATEGORY_LABELS, REASON_FIELDS, SOURCE_DESCRIPTIONS, SOURCE_LABELS, STATUS_LABELS } from "../constants";
import { fieldLabel, formatFieldValue, renderEssayChips, renderEssayText, scoreBand } from "../format";
import type { ApplicationDetail, AppStatus } from "../types";

export function CandidateDetail(props: {
  app: ApplicationDetail;
  onBack: () => void;
  onOverrideStatus: (id: number, status: AppStatus) => void;
  onClearOverride: (id: number) => void;
}): ReactNode {
  const { app } = props;
  const flaggedFields = new Set(app.hardFilterReasons.flatMap((reason) => REASON_FIELDS[reason.code] ?? []));
  const isHuman = app.statusSource === "human";
  const autoLabel = STATUS_LABELS[app.autoStatus];

  return (
    <div className="app-detail">
      <div className="app-detail-actions no-print">
        <button className="back-button" onClick={props.onBack}>
          <ChevronLeft size={16} />
          <span>Back to list</span>
        </button>
        <button type="button" className="secondary-button" onClick={() => window.print()}>
          <Printer size={16} />
          Print
        </button>
      </div>
      <div className="app-detail-header">
        <h3>{app.applicantName || app.primaryEmail}</h3>
        <span className={`status-badge status-${app.status}`}>{STATUS_LABELS[app.status]}</span>
        {app.statusSource !== "untouched" ? (
          <span className={`source-badge source-${app.statusSource}`}>{SOURCE_LABELS[app.statusSource]}</span>
        ) : null}
      </div>
      {app.coApplicantName ? <p className="co-applicant-line">Co-applicant: {app.coApplicantName}</p> : null}

      <div className="status-panel">
        <p className="status-source-line">{SOURCE_DESCRIPTIONS[app.statusSource]}</p>
        {app.stale ? (
          <p className="stale-note">New AI findings since this was last reviewed — you may want to look again.</p>
        ) : null}
        {/* The toggle is source ownership: "Automatic" (machine-decided) vs. a
            human-pinned status. Automatic clears the override; the helper line
            shows the current automatic verdict. */}
        <div className="status-decider">
          <span className="status-decider-label">Decided by:</span>
          <div className="segmented" role="group" aria-label="Status decided by">
            <button
              type="button"
              className="segment"
              aria-pressed={!isHuman}
              disabled={!isHuman}
              onClick={() => props.onClearOverride(app.id)}
            >
              Automatic
            </button>
            <button
              type="button"
              className="segment"
              aria-pressed={isHuman && app.status === "eligible"}
              disabled={isHuman && app.status === "eligible"}
              onClick={() => props.onOverrideStatus(app.id, "eligible")}
            >
              Eligible
            </button>
            <button
              type="button"
              className="segment"
              aria-pressed={isHuman && app.status === "ineligible"}
              disabled={isHuman && app.status === "ineligible"}
              onClick={() => props.onOverrideStatus(app.id, "ineligible")}
            >
              Ineligible
            </button>
          </div>
          {isHuman ? (
            <p className="status-decider-hint">
              Reviewer override. Automatic would mark this {autoLabel.toLowerCase()}.
            </p>
          ) : null}
        </div>
      </div>
      {app.hardFilterReasons.length > 0 ? (
        <div className="filter-reasons">
          <strong>Filter reasons:</strong>
          <ul>
            {app.hardFilterReasons.map((reason, i) => (
              <li key={i}>{reason.message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {app.flags && app.flags.length > 0 ? (
        <div className="flags-panel">
          <strong>Screening flags</strong>
          <p className="flags-hint">
            The AI raised these. Decide for yourself which matter — set the status above.
          </p>
          <ul>
            {app.flags.map((flag, i) => (
              <li key={i} className={`flag flag-${flag.severity}`}>
                <span className="flag-category">{FLAG_CATEGORY_LABELS[flag.category] ?? flag.category}</span>
                <span className="flag-summary">{flag.summary}</span>
                {flag.evidence ? <span className="flag-evidence">{flag.evidence}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {app.dimensionScores && app.dimensionScores.length > 0 ? (
        <div className="dimension-scores">
          <h4>Fit dimensions</h4>
          <p className="dimension-scores-hint">
            Ordered by how much each dimension moved this candidate's ranking — strengths and weaknesses together, most
            decisive first. Colour shows the score: green strong, blue moderate, amber weak.
          </p>
          <ul>
            {app.dimensionScores.map((s) => {
              const sb = scoreBand(s.score);
              return (
                <li key={s.dimensionKey} className="dimension-score">
                  <div className="dimension-score-head">
                    <span className="dimension-score-name">{s.name}</span>
                    <span className="dimension-score-bar" aria-hidden="true">
                      <span className={`dimension-score-fill ${sb.cls}`} style={{ width: `${Math.round(s.score * 100)}%` }} />
                    </span>
                    <span className={`dimension-score-band ${sb.cls}`}>{sb.label}</span>
                    <span className="dimension-score-confidence">{s.confidence} confidence</span>
                  </div>
                  <p className="dimension-score-rationale">{s.rationale}</p>
                  {s.evidence ? <p className="dimension-score-evidence">{s.evidence}</p> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {app.essays?.some((essay) => essay.answer) ? (
        <div className="app-detail-essays">
          <h4>Essay responses</h4>
          {app.essays.map((essay) => (
            <div key={essay.question} className="essay-block">
              <h5>{essay.label}</h5>
              {essay.answer ? <p>{essay.answer}</p> : <p className="essay-empty">No response provided.</p>}
            </div>
          ))}
        </div>
      ) : null}
      <div className="app-detail-fields">
        <h4>Applicant data</h4>
        <dl>
          {Object.entries(app.normalized).map(([key, value]) => {
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
      {app.rawRow ? (
        <details className="raw-row-section">
          <summary>Raw source row</summary>
          <pre>{JSON.stringify(app.rawRow, null, 2)}</pre>
        </details>
      ) : null}
      {app.aiNarrative ? (
        <details className="raw-row-section">
          <summary>Raw AI narrative (screening)</summary>
          <div className="ai-narrative">
            <ReactMarkdown>{app.aiNarrative}</ReactMarkdown>
          </div>
        </details>
      ) : null}
      {app.essayAnalysis ? (
        <details className="raw-row-section">
          <summary>AI essay summary</summary>
          <div className="essay-analysis">
            <p className="essay-analysis-hint">
              A neutral digest of what the applicant wrote. It describes what they said, not how good it is.
            </p>
            <p className="essay-analysis-summary">{app.essayAnalysis.summary}</p>
            <dl className="essay-analysis-fields">
              {renderEssayText("Household", app.essayAnalysis.householdContext)}
              {renderEssayText("Employment", app.essayAnalysis.employmentBackground)}
              {renderEssayText("Prior co-op experience", app.essayAnalysis.priorCoOpExperience)}
              {renderEssayChips("Skills offered", app.essayAnalysis.skillsOffered)}
              {renderEssayChips("Stated contributions", app.essayAnalysis.statedContributions)}
              {renderEssayChips("Motivations", app.essayAnalysis.statedMotivations)}
              {renderEssayChips("Interests", app.essayAnalysis.interests)}
              {renderEssayChips("Values", app.essayAnalysis.values)}
            </dl>
          </div>
        </details>
      ) : null}
    </div>
  );
}
