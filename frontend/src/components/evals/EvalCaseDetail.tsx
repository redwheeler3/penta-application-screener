import { type ReactNode } from "react";

// Read-only, COMPLETE rendering of one eval case — the master-detail counterpart to the
// case list. Fields are grouped on disk into by-CONSUMER blocks; this renders each block
// under a heading with a badge naming WHO sees it, so it's obvious at a glance which fields
// reach a model and which are harness-only. Every field is shown in full (no truncation).
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
    // An array of scalars renders inline as "a | b" (an "at least one of" group, e.g. a
    // screening fires entry) — a vertical list would misread as separate requirements. Arrays
    // holding objects/arrays (e.g. child_details) still stack for legibility.
    const allScalar = v.every((item) => item === null || typeof item !== "object");
    if (allScalar) {
      return <span className="eval-detail-scalar">{v.map((item) => String(item)).join(" | ")}</span>;
    }
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

// Per-block "who consumes this" badge. Keyed by the block's field name; an unknown block
// renders without a badge rather than a wrong one. The uniform envelope has two blocks.
const BLOCK_CONSUMER: Record<string, { badge: string; tone: string }> = {
  metadata: { badge: "harness only — no model sees this", tone: "neutral" },
  given: { badge: "sent to the model under test", tone: "model" },
};

// Model-facing blocks lead (they're the POINT of the case — what actually reaches a model);
// the harness-only `metadata` bookkeeping trails last, so the view never opens on "no model
// sees this" while burying what the model does see.
const BLOCK_ORDER = ["given", "input", "produced", "evidence", "prompt", "judge", "metadata"];

export function EvalCaseDetail(props: { evalCase: Record<string, unknown> }): ReactNode {
  const c = props.evalCase;
  const blockKeys = Object.keys(c).filter((k) => k !== "key");
  const ordered = [
    ...BLOCK_ORDER.filter((k) => blockKeys.includes(k)),
    ...blockKeys.filter((k) => !BLOCK_ORDER.includes(k)),
  ];

  return (
    <div className="eval-detail" role="region" aria-label={`Case ${String(c.key ?? "")}`}>
      <div className="eval-detail-field">
        <span className="eval-detail-fieldname">Key</span>
        <div className="eval-detail-fieldval">
          <Value value={c.key} />
        </div>
      </div>
      {ordered.map((k) => {
        const consumer = BLOCK_CONSUMER[k];
        return (
          <div key={k} className="eval-detail-block">
            <div className="eval-detail-block-head">
              <span className="eval-detail-block-name">{label(k)}</span>
              {consumer ? (
                <span className={`eval-detail-badge ${consumer.tone}`}>{consumer.badge}</span>
              ) : null}
            </div>
            <div className="eval-detail-block-body">
              <Value value={c[k]} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
