import { ChevronLeft, Printer } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { FLAG_CATEGORY_LABELS, FLAG_FIELDS, REASON_FIELDS, SOURCE_DESCRIPTIONS, SOURCE_LABELS, STATUS_LABELS } from "../constants";
import { fieldLabel, formatFieldValue, scoreBand } from "../format";
import type { AIResultTrace, ApplicationDetail, AppStatus, DimensionScoringTrace } from "../types";

type DetailField = {
  key: string;
  label: string;
  value: unknown;
  normalizedKey?: string;
};

type DetailSection = {
  title: string;
  fields: DetailField[];
};

type SourceField = {
  key: string;
  label?: string;
  normalizedKey?: string;
  source?: "raw" | "normalized";
  consumesRawKeys?: string[];
};

const MAX_PRIVATE_NOTE_HEIGHT_PX = 192;

const CHILD_DETAIL_RAW_KEYS = [
  "First name [3]",
  "Last name [3]",
  "Age [3]",
  "First name [4]",
  "Last name [4]",
  "Age [4]",
  "First name [5]",
  "Last name [5]",
  "Age [5]",
  "First name [6]",
  "Last name [6]",
  "Age [6]",
];

const HIDDEN_RAW_KEYS = new Set(["Declaration"]);

const SOURCE_SECTIONS: Array<{ title: string; fields: SourceField[] }> = [
  {
    title: "Applicant",
    fields: [
      { key: "First name", label: "First name", normalizedKey: "applicant_name" },
      { key: "Last name", label: "Last name", normalizedKey: "applicant_name" },
      { key: "Age", normalizedKey: "applicant_age" },
      { key: "Phone number (xxx-xxx-xxxx)", label: "Phone number" },
      { key: "Email address", label: "Email address", normalizedKey: "applicant_email" },
    ],
  },
  {
    title: "Co-applicant",
    fields: [
      { key: "First name [2]", label: "First name", normalizedKey: "co_applicant_name" },
      { key: "Last name [2]", label: "Last name", normalizedKey: "co_applicant_name" },
      { key: "Age [2]", label: "Age", normalizedKey: "co_applicant_age" },
      { key: "Relationship to applicant" },
      { key: "Phone number (xxx-xxx-xxxx) [2]", label: "Phone number", normalizedKey: "co_applicant_phone" },
      { key: "Email address [2]", label: "Email address", normalizedKey: "co_applicant_email" },
    ],
  },
  {
    title: "Household composition",
    fields: [
      { key: "adult_count", label: "Number of adults", normalizedKey: "adult_count", source: "normalized" },
      {
        key: "How many children (under 18) will be living in the unit on the move in date?",
        label: "Number of children",
        normalizedKey: "child_count",
      },
      {
        key: "child_details",
        label: "Children",
        normalizedKey: "child_details",
        source: "normalized",
        consumesRawKeys: CHILD_DETAIL_RAW_KEYS,
      },
      {
        key: "If you have a link to a photo of yourself and the members of your household, please include it here.",
        label: "Household photo link",
      },
      { key: "If you have any pets, please describe them here.", label: "Pets", normalizedKey: "pets_text" },
    ],
  },
  {
    title: "Housing and references",
    fields: [
      { key: "Street address" },
      { key: "Street address 2" },
      { key: "City" },
      { key: "Province / State" },
      { key: "Postal / Zip Code" },
      { key: "Country" },
      { key: "Have you lived at your current address for 2 years or more?", label: "Current address 2+ years" },
      {
        key: "Do you own real estate (land, house, condominium, etc.)?",
        label: "Owns real estate",
        normalizedKey: "has_real_estate",
      },
      { key: "Current landlord name" },
      { key: "Current landlord email address" },
      { key: "Current landlord phone number (xxx-xxx-xxxx)", label: "Current landlord phone" },
      { key: "Previous landlord name" },
      { key: "Previous landlord email address" },
      { key: "Previous landlord phone number (xxx-xxx-xxxx)", label: "Previous landlord phone" },
    ],
  },
  {
    title: "Applicant employment",
    fields: [
      { key: "Job title" },
      { key: "Company name" },
      { key: "Start date at this company", normalizedKey: "applicant_employment_start" },
      { key: "Name of current manager" },
      { key: "Phone number (xxx-xxx-xxxx) of current manager", label: "Manager phone" },
      { key: "Email address of current manager", label: "Manager email" },
    ],
  },
  {
    title: "Co-applicant employment",
    fields: [
      { key: "Job title [2]", label: "Job title" },
      { key: "Company name [2]", label: "Company name" },
      {
        key: "Start date at this company [2]",
        label: "Start date at this company",
        normalizedKey: "co_applicant_employment_start",
      },
      { key: "Name of current manager [2]", label: "Name of current manager" },
      { key: "Phone number (xxx-xxx-xxxx) of current manager [2]", label: "Manager phone" },
      { key: "Email address of current manager [2]", label: "Manager email" },
    ],
  },
  {
    title: "Income and declaration",
    fields: [
      { key: "Total yearly gross income for applicant", normalizedKey: "applicant_income" },
      { key: "Total yearly gross income for co-applicant", normalizedKey: "co_applicant_income" },
      {
        key: "Total yearly gross income for your household (add up all the numbers above)",
        label: "Total household income",
        normalizedKey: "household_income",
      },
    ],
  },
  {
    title: "Submission",
    fields: [
      { key: "Timestamp" },
      { key: "Email Address", label: "Form submission email", normalizedKey: "form_submission_email" },
    ],
  },
];

export function CandidateDetail(props: {
  app: ApplicationDetail;
  onBack: () => void;
  onOverrideStatus: (id: number, status: AppStatus) => void;
  onClearOverride: (id: number) => void;
  onSavePrivateNote: (id: number, note: string) => Promise<boolean>;
}): ReactNode {
  const { app } = props;
  const [privateNote, setPrivateNote] = useState(app.privateNote);
  const [noteStatus, setNoteStatus] = useState<"saved" | "saving" | "error">("saved");
  const privateNoteRef = useRef<HTMLTextAreaElement>(null);
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

  const flaggedFields = new Set([
    ...app.hardFilterReasons.flatMap((reason) => REASON_FIELDS[reason.code] ?? []),
    ...(app.flags ?? []).flatMap((flag) => FLAG_FIELDS[flag.category] ?? []),
  ]);
  const isHuman = app.statusSource === "human";
  const autoLabel = STATUS_LABELS[app.autoStatus];
  const detailSections = buildDetailSections(app);

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

      <div className="detail-review-row">
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
          <ul>
            {app.dimensionScores.map((s) => {
              const sb = scoreBand(s.score);
              return (
                <li key={s.dimensionKey} className="dimension-score">
                  <div className="dimension-score-head">
                    <span className="dimension-score-name">{s.name}</span>
                    <span className="dimension-score-bar" aria-hidden="true">
                      <span className={`dimension-score-fill ${sb.cls}`} style={{ width: `${Math.round(((s.score + 1) / 2) * 100)}%` }} />
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
        {detailSections.map((section) => (
          <section key={section.title} className="app-detail-field-group">
            <h5>{section.title}</h5>
            <dl>
              {section.fields.map((field) => {
                const flagged = field.normalizedKey
                  ? flaggedFields.has(field.normalizedKey)
                  : flaggedFields.has(field.key);
                return (
                  <div key={field.key} className={flagged ? "field-flagged" : undefined}>
                    <dt>{field.label}</dt>
                    <dd>{formatFieldValue(field.value, field.normalizedKey ?? field.key)}</dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ))}
      </div>
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
      <div><dt>Prompt</dt><dd><code>{trace.promptVersion}</code></dd></div>
      <div><dt>Tokens</dt><dd>{trace.inputTokens.toLocaleString()} in → {trace.outputTokens.toLocaleString()} out</dd></div>
      <div><dt>Attributed cost</dt><dd>${trace.costUsd.toFixed(4)}</dd></div>
    </dl>
  );
}

function DimensionScoringTraceDetails(props: { trace: DimensionScoringTrace }): ReactNode {
  const { trace } = props;
  return (
    <dl className="ai-trace-meta">
      <div><dt>Criteria</dt><dd>{trace.dimensionCount} stored score{trace.dimensionCount === 1 ? "" : "s"}</dd></div>
      <div><dt>Model</dt><dd>{trace.modelIds.join(", ")}</dd></div>
      <div><dt>Prompt</dt><dd>{trace.promptVersions.map((version) => <code key={version}>{version}</code>)}</dd></div>
      <div><dt>Tokens</dt><dd>{trace.inputTokens.toLocaleString()} in → {trace.outputTokens.toLocaleString()} out</dd></div>
      <div><dt>Attributed cost</dt><dd>${trace.costUsd.toFixed(4)}</dd></div>
    </dl>
  );
}

function buildDetailSections(app: ApplicationDetail): DetailSection[] {
  const rawRow = app.rawRow ?? {};
  const normalized = app.normalized ?? {};
  const usedRawKeys = new Set<string>();
  const essayKeys = new Set(app.essays.map((essay) => essay.question));

  const sections = SOURCE_SECTIONS.map((section) => {
    const fields = section.fields
      .filter((field) => {
        if (field.source === "normalized") {
          return Object.prototype.hasOwnProperty.call(normalized, field.normalizedKey ?? field.key);
        }
        return Object.prototype.hasOwnProperty.call(rawRow, field.key);
      })
      .map((field) => {
        const isNormalized = field.source === "normalized";
        if (!isNormalized) usedRawKeys.add(field.key);
        field.consumesRawKeys?.forEach((key) => usedRawKeys.add(key));
        return {
          key: field.key,
          label: field.label ?? fieldLabel(field.key),
          value: isNormalized ? normalized[field.normalizedKey ?? field.key] : rawRow[field.key],
          normalizedKey: field.normalizedKey,
        };
      });
    return { title: section.title, fields };
  }).filter((section) => section.fields.length > 0);

  const otherRawFields = Object.entries(rawRow)
    .filter(([key]) => !usedRawKeys.has(key) && !essayKeys.has(key) && !HIDDEN_RAW_KEYS.has(key))
    .map(([key, value]) => ({
      key,
      label: fieldLabel(key),
      value,
      normalizedKey: undefined,
    }));

  if (otherRawFields.length > 0) {
    const submission = sections.find((section) => section.title === "Submission");
    if (submission) {
      submission.fields.push(...otherRawFields);
    } else {
      sections.push({ title: "Submission", fields: otherRawFields });
    }
  }

  return sections;
}
