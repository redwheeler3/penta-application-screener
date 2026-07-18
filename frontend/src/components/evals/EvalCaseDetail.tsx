import { type ReactNode } from "react";

// Read-only, COMPLETE rendering of one eval case — the master-detail counterpart to the
// case list. Every field is shown in full (no truncation): scalars as labeled values,
// nested objects (evidence / applicant / dimension / expect) as titled sub-sections.
// This is the "view" half; editing is EvalCaseEditor.

function label(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function Value(props: { value: unknown }): ReactNode {
  const v = props.value;
  if (v === null || v === undefined || v === "") return <span className="eval-detail-empty">—</span>;
  if (typeof v === "object" && !Array.isArray(v)) {
    return (
      <div className="eval-detail-object">
        {Object.entries(v as Record<string, unknown>).map(([k, cv]) => (
          <div key={k} className="eval-detail-row">
            <span className="eval-detail-key">{label(k)}</span>
            <div className="eval-detail-val">
              <Value value={cv} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (Array.isArray(v)) {
    return (
      <ul className="eval-detail-list">
        {v.map((item, i) => (
          <li key={i}>
            <Value value={item} />
          </li>
        ))}
      </ul>
    );
  }
  return <span className="eval-detail-scalar">{String(v)}</span>;
}

// Field display order: put the identifying/label fields first, then the rest as-authored.
const LEAD_KEYS = ["key", "title", "task", "note", "expected", "expect"];

export function EvalCaseDetail(props: { evalCase: Record<string, unknown> }): ReactNode {
  const c = props.evalCase;
  const keys = Object.keys(c);
  const lead = LEAD_KEYS.filter((k) => k in c);
  const rest = keys.filter((k) => !LEAD_KEYS.includes(k));
  const ordered = [...lead, ...rest];

  return (
    <div className="eval-detail" role="region" aria-label={`Case ${String(c.key ?? "")}`}>
      {ordered.map((k) => (
        <div key={k} className="eval-detail-field">
          <span className="eval-detail-fieldname">{label(k)}</span>
          <div className="eval-detail-fieldval">
            <Value value={c[k]} />
          </div>
        </div>
      ))}
    </div>
  );
}
