import { type ReactNode, useState } from "react";
import type { EvalFixtureKey } from "../../types";
import { type FieldObject, StructuredFields } from "./StructuredFields";

// Field-level editor for one eval case — typed inputs, not raw JSON. Known scalar fields
// render as inputs; nested objects (metadata / given: applicant / dimension / pair) render
// as labeled sub-sections with add/remove (see StructuredFields). The `key` field is fixed
// while editing (it's the identity the upsert keys on); a NEW case lets you set it.
//
// Templates seed a new case with the family's expected shape so you're filling fields, not
// inventing structure. Save writes to the versioned fixture FILE (server-validated); the
// operator commits to git.

// A NEW case is seeded from its pass's template so you fill fields, not invent structure.
// Fields are grouped by consumer: `metadata` is harness-only; `given` is what the real prompt
// receives. (The judge tab adds no new cases — addable=false — so it needs no template here.)
const TEMPLATES: Partial<Record<EvalFixtureKey, FieldObject>> = {
  scoring: {
    key: "",
    metadata: { pass: "scoring", note: "", expected: { score_min: -0.15, score_max: 0.15, confidence: "low" } },
    given: {
      applicant: { facts: {}, essays: { essay: "" } },
      dimension: { key: "", name: "", definition: "", high_end: "", low_end: "" },
    },
  },
  consolidation: {
    key: "",
    metadata: { pass: "consolidation", note: "", expected: "keep", label_rationale: "" },
    given: {
      pair: [
        { key: "", name: "", definition: "" },
        { key: "", name: "", definition: "" },
      ],
    },
  },
  matching: {
    key: "",
    metadata: { pass: "matching", note: "", expected: "matches", label_rationale: "" },
    given: {
      prior: [{ key: "", name: "", definition: "" }],
      new: [{ key: "", name: "", definition: "" }],
    },
  },
  decomposition: {
    key: "",
    metadata: { pass: "decomposition", note: "", expected: "merge", label_rationale: "" },
    given: {
      reports: [
        [{ key: "", name: "", definition: "" }],
        [{ key: "", name: "", definition: "" }],
      ],
    },
  },
  screening: {
    key: "",
    metadata: { pass: "screening", note: "", expected: { fires: [], absent: [] } },
    given: {
      fields: { applicant_name: "", pets_text: "", applicant_email: "" },
      essays: {},
    },
  },
};

export function EvalCaseEditor(props: {
  evalKey: EvalFixtureKey;
  existing: Record<string, unknown> | null;
  error: string | null; // server-side validation error, if any
  onCancel: () => void;
  onSave: (c: FieldObject) => void;
}): ReactNode {
  const [value, setValue] = useState<FieldObject>(
    // judge owns no template (addable=false, so no new judge case is created here) → {} fallback.
    () => (props.existing as FieldObject | null) ?? TEMPLATES[props.evalKey] ?? { key: "" },
  );

  const isNew = props.existing === null;
  // `key` is read-only when editing an existing case; editable (required) for a new one.
  const readOnlyKeys = isNew ? [] : ["key"];

  function save() {
    const key = typeof value.key === "string" ? value.key.trim() : "";
    if (!key) {
      // Surface inline rather than saving an unkeyed case; server would 422 anyway.
      window.alert("A case needs a non-empty key.");
      return;
    }
    props.onSave(value);
  }

  return (
    <div className="eval-editor">
      <div className="eval-editor-head">
        <strong>{isNew ? "Add case" : `Edit case: ${String(props.existing?.key ?? "")}`}</strong>
        <span className="eval-hint">
          Saves to the committed fixture file — commit it to git afterward.
        </span>
      </div>

      <StructuredFields value={value} readOnlyKeys={readOnlyKeys} onChange={setValue} />

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
