import { ArrowDown, ChevronLeft, Printer } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { REASON_FIELDS, SOURCE_DESCRIPTIONS, SOURCE_LABELS, STATUS_LABELS } from "../../constants";
import {
  flagCategoryLabel,
  formatFieldValue,
  money,
  openingLabel,
  reasoningEffortLabel,
  scoreBand,
} from "../../format";
import type {
  AIResultTrace,
  ApplicationDetail,
  AppStatus,
  CommitteeOpening,
  DimensionScoringTrace,
} from "../../types";
import { buildDetailSections, type DetailField } from "./applicationDetailSections";
import { StarButton } from "./StarButton";

const MAX_PRIVATE_NOTE_HEIGHT_PX = 192;

// Render a field's value, rendering it as a new-tab link when the field is marked isLink and
// the value is an http(s) URL. Anything else (blank, or a non-URL answer someone typed instead
// of a link) falls back to the normal text formatting, so we never produce a broken anchor.
function renderFieldValue(field: DetailField): ReactNode {
  if (field.isLink && typeof field.value === "string") {
    const url = field.value.trim();
    if (/^https?:\/\/\S+$/i.test(url)) {
      return (
        <a href={url} target="_blank" rel="noreferrer noopener">
          {url}
        </a>
      );
    }
  }
  return formatFieldValue(field.value, field.normalizedKey ?? field.key);
}
export function CandidateDetail(props: {
  app: ApplicationDetail;
  openings: CommitteeOpening[];
  onBack: () => void;
  onOverrideStatus: (id: number, status: AppStatus) => void;
  onClearOverride: (id: number) => void;
  onSavePrivateNote: (id: number, note: string) => Promise<boolean>;
  onToggleStar: (id: number, starred: boolean) => void;
  readOnly?: boolean;
}): ReactNode {
  const { app } = props;
  const [privateNote, setPrivateNote] = useState(app.privateNote);
  const [noteStatus, setNoteStatus] = useState<"saved" | "saving" | "error">("saved");
  const privateNoteRef = useRef<HTMLTextAreaElement>(null);
  const aiScoringRef = useRef<HTMLElement>(null);
  const pendingNoteSave = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noteRevision = useRef(0);
  const savedNote = useRef(app.privateNote);

  useEffect(() => {
    if (pendingNoteSave.current !== null) clearTimeout(pendingNoteSave.current);
    noteRevision.current += 1;
    savedNote.current = app.privateNote;
    setPrivateNote(app.privateNote);
    setNoteStatus("saved");
  }, [app.id]);

  useEffect(
    () => () => {
      if (pendingNoteSave.current !== null) clearTimeout(pendingNoteSave.current);
    },
    [],
  );

  useLayoutEffect(() => {
    const textarea = privateNoteRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_PRIVATE_NOTE_HEIGHT_PX)}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_PRIVATE_NOTE_HEIGHT_PX ? "auto" : "hidden";
  }, [privateNote]);

  function persistPrivateNote(note: string, revision: number) {
    if (note === savedNote.current) {
      if (revision === noteRevision.current) setNoteStatus("saved");
      return;
    }
    setNoteStatus("saving");
    props.onSavePrivateNote(app.id, note).then((saved) => {
      if (revision !== noteRevision.current) return;
      if (saved) {
        savedNote.current = note;
        setNoteStatus("saved");
      } else {
        setNoteStatus("error");
      }
    });
  }

  function updatePrivateNote(note: string) {
    setPrivateNote(note);
    const revision = (noteRevision.current += 1);
    if (pendingNoteSave.current !== null) clearTimeout(pendingNoteSave.current);
    setNoteStatus("saving");
    pendingNoteSave.current = setTimeout(() => persistPrivateNote(note, revision), 600);
  }

  function flushPrivateNote() {
    if (pendingNoteSave.current !== null) {
      clearTimeout(pendingNoteSave.current);
      pendingNoteSave.current = null;
    }
    persistPrivateNote(privateNote, noteRevision.current);
  }

  const flaggedFields = new Set(
    app.hardFilterReasons.flatMap((reason) => REASON_FIELDS[reason.code] ?? []),
  );
  // Findings are grouped by source to match the status badge: the deterministic
  // rules (structured-field threshold reasons) vs. the AI screening pass. Pets are a hard-filter
  // reason but attribute to AI (the model extracts the pet counts), so they render in the AI
  // panel as evidence cards alongside the flags — not in the deterministic panel.
  const petReasons = app.hardFilterReasons.filter((r) => r.code === "pets_over_limit");
  const ruleReasons = app.hardFilterReasons.filter((r) => r.code !== "pets_over_limit");
  const normalizedFields = app.normalized ?? {};
  const petsText = typeof normalizedFields.pets_text === "string" ? normalizedFields.pets_text : "";
  const petReasoning = app.petFacts?.reasoning ?? "";
  const isHuman = app.statusSource === "human";
  const autoLabel = STATUS_LABELS[app.autoStatus];
  const detailSections = buildDetailSections(app);
  const hasEssayResponses = app.essays.length > 0;

  function scrollToAiScoring() {
    const aiScoring = aiScoringRef.current;
    if (!aiScoring) return;
    aiScoring.scrollIntoView({ behavior: "smooth", block: "start" });
    aiScoring.focus({ preventScroll: true });
  }

  return (
    <div className="app-detail">
      <div className="app-detail-actions no-print">
        <button type="button" className="secondary-button" onClick={props.onBack}>
          <ChevronLeft size={16} />
          <span>{props.readOnly ? "Back to openings" : "Back to list"}</span>
        </button>
        <button type="button" className="secondary-button" onClick={() => window.print()}>
          <Printer size={16} />
          Print
        </button>
      </div>
      <div className="app-detail-identity">
        {props.readOnly ? <span className="app-detail-star-spacer" /> : (
          <StarButton
            starred={app.starredByMe}
            onToggle={(next) => props.onToggleStar(app.id, next)}
            size="md"
          />
        )}
        <div className="app-detail-identity-content">
          <div className="app-detail-header">
            <h3>{app.applicantName || app.primaryEmail}</h3>
            <span className={`status-badge status-${app.status}`}>{STATUS_LABELS[app.status]}</span>
            {app.statusSource !== "untouched" ? (
              <span className={`source-badge source-${app.statusSource}`}>{SOURCE_LABELS[app.statusSource]}</span>
            ) : null}
          </div>
          {app.coApplicantName ? <p className="co-applicant-line">Co-applicant: {app.coApplicantName}</p> : null}
          <div className="application-openings" aria-label="Applied openings">
            <span>Applied for</span>
            {app.openingIds.length ? (
              app.openingIds.map((openingId) => {
                const opening = props.openings.find((candidate) => candidate.id === openingId);
                return opening ? <strong key={opening.id}>{openingLabel(opening)}</strong> : null;
              })
            ) : (
              <strong>No current opening</strong>
            )}
          </div>
        </div>
      </div>

      {!props.readOnly ? <div className="detail-review-row">
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
        <section className="private-note-panel">
          <div className="private-note-heading">
            <h4>My notes</h4>
          </div>
          <textarea
            ref={privateNoteRef}
            aria-label="Private notes"
            value={privateNote}
            onChange={(event) => updatePrivateNote(event.target.value)}
            onBlur={flushPrivateNote}
            placeholder="Add a private note about this applicant…"
            rows={2}
          />
          <div className="private-note-print">{privateNote}</div>
          {noteStatus !== "saved" ? (
            <p>{noteStatus === "saving" ? "Saving…" : "Could not save — try again."}</p>
          ) : null}
        </section>
      </div> : null}
      {ruleReasons.length > 0 ? (
        <div className="filter-reasons">
          <strong>Deterministic rules</strong>
          <p className="flags-hint">Decided directly from the application fields.</p>
          <ul>
            {ruleReasons.map((reason, i) => (
              <li key={i}>{reason.message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {(app.flags && app.flags.length > 0) || petReasons.length > 0 ? (
        <div className="flags-panel">
          <strong>AI screening</strong>
          <p className="flags-hint">
            Raised by the AI screening pass. Decide for yourself which matter — set the status above.
          </p>
          <ul>
            {/* Pet findings first: a deterministic verdict over AI-extracted pet counts,
                rendered as evidence cards like the flags — the raw pets field is the evidence
                the AI read the counts from, symmetric with a flag citing its field. */}
            {petReasons.map((reason, i) => (
              <li key={`pet-${i}`} className="flag">
                <span className="flag-category">Pet policy</span>
                <span className="flag-summary">{reason.message}</span>
                {/* Evidence = the AI's reasoning on the pets field (the analogue of a flag's
                    cited summary). Falls back to the raw field only if a result predates the
                    reasoning. */}
                {petReasoning ? (
                  <span className="flag-evidence">{petReasoning}</span>
                ) : petsText ? (
                  <span className="flag-evidence">pets: {petsText}</span>
                ) : null}
              </li>
            ))}
            {(app.flags ?? []).map((flag, i) => (
              <li key={i} className="flag">
                <span className="flag-category">{flagCategoryLabel(flag.category)}</span>
                <span className="flag-summary">{flag.summary}</span>
                {flag.evidence ? <span className="flag-evidence">{flag.evidence}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <section className="application-answers-section">
        <div className="detail-section-heading">
          <h4>Application answers</h4>
          {app.dimensionScores && app.dimensionScores.length > 0 ? (
            <button type="button" className="secondary-button detail-section-scroll-link no-print" onClick={scrollToAiScoring}>
              View AI scoring
              <ArrowDown size={15} aria-hidden="true" />
            </button>
          ) : null}
        </div>
        {hasEssayResponses ? (
          <div className="app-detail-essays">
            <h5>Essay responses</h5>
            {app.essays.map((essay) => (
              <div key={essay.question} className="essay-block">
                <h6>{essay.label}</h6>
                {essay.answer ? <p>{essay.answer}</p> : <p className="essay-empty">No response provided.</p>}
              </div>
            ))}
          </div>
        ) : null}
        <div className="app-detail-fields">
          <h5>Applicant data</h5>
          {detailSections.map((section) => (
            <section key={section.title} className="app-detail-field-group">
              <h6>{section.title}</h6>
              <dl>
                {section.fields.map((field) => {
                  const flagged = field.normalizedKey
                    ? flaggedFields.has(field.normalizedKey)
                    : flaggedFields.has(field.key);
                  return (
                    <div key={field.key} className={flagged ? "field-flagged" : undefined}>
                      <dt>{field.label}</dt>
                      <dd>{renderFieldValue(field)}</dd>
                    </div>
                  );
                })}
              </dl>
            </section>
          ))}
        </div>
      </section>
      {app.dimensionScores && app.dimensionScores.length > 0 ? (
        <section ref={aiScoringRef} className="dimension-scores" tabIndex={-1}>
          <div className="detail-section-heading">
            <h4>AI scoring</h4>
          </div>
          <ul>
            {app.dimensionScores.map((s) => {
              const sb = scoreBand(s.score);
              return (
                <li key={s.dimensionKey} className="dimension-score">
                  <div className="dimension-score-head">
                    <span className="dimension-score-name">{s.name}</span>
                    <span className="dimension-score-bar" aria-hidden="true">
                      <span className={`dimension-score-fill ${sb.cls}${s.score === 0 ? " is-zero" : ""}`} style={{ width: `${Math.round(((s.score + 1) / 2) * 100)}%` }} />
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
        </section>
      ) : null}
      {app.aiNarrative ? (
        <details className="raw-row-section">
          <summary>Raw AI narrative (screening)</summary>
          <div className="ai-narrative">
            <ReactMarkdown>{app.aiNarrative}</ReactMarkdown>
          </div>
        </details>
      ) : null}
      {app.screeningTrace || app.dimensionScoringTrace ? (
        <details className="raw-row-section ai-trace-section">
          <summary>AI trace</summary>
          {app.screeningTrace ? (
            <div className="ai-trace-score">
              <strong>Screening</strong>
              <AITrace trace={app.screeningTrace} />
            </div>
          ) : null}
          {app.dimensionScoringTrace ? (
            <div className="ai-trace-score">
              <strong>Dimension scoring</strong>
              <DimensionScoringTraceDetails trace={app.dimensionScoringTrace} />
            </div>
          ) : null}
        </details>
      ) : null}
    </div>
  );
}

function AITrace(props: { trace: AIResultTrace }): ReactNode {
  const { trace } = props;
  return (
    <dl className="ai-trace-meta">
      <div><dt>Model</dt><dd>{trace.modelId}</dd></div>
      <div><dt>Reasoning</dt><dd>{reasoningEffortLabel(trace.supportsReasoningEffort, trace.reasoningEffort)}</dd></div>
      <div><dt>Prompt</dt><dd><code>{trace.promptVersion}</code></dd></div>
      <div><dt>Tokens</dt><dd>{trace.inputTokens.toLocaleString()} in → {trace.outputTokens.toLocaleString()} out</dd></div>
      <div><dt>Attributed cost</dt><dd>{money(trace.costUsd)}</dd></div>
    </dl>
  );
}

function DimensionScoringTraceDetails(props: { trace: DimensionScoringTrace }): ReactNode {
  const { trace } = props;
  return (
    <dl className="ai-trace-meta">
      <div><dt>Criteria</dt><dd>{trace.dimensionCount} stored score{trace.dimensionCount === 1 ? "" : "s"}</dd></div>
      <div><dt>Model</dt><dd>{trace.models.map((model) => model.modelId).join(", ")}</dd></div>
      <div><dt>Reasoning</dt><dd>{trace.models.map((model) => reasoningEffortLabel(model.supportsReasoningEffort, model.reasoningEffort)).join(", ")}</dd></div>
      <div><dt>Prompt</dt><dd>{trace.promptVersions.map((version) => <code key={version}>{version}</code>)}</dd></div>
      <div><dt>Tokens</dt><dd>{trace.inputTokens.toLocaleString()} in → {trace.outputTokens.toLocaleString()} out</dd></div>
      <div><dt>Attributed cost</dt><dd>{money(trace.costUsd)}</dd></div>
    </dl>
  );
}
