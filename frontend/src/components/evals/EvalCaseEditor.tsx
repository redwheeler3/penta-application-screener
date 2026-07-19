import { type ReactNode, useState } from "react";
import { type FieldObject, StructuredFields } from "./StructuredFields";

// Field-level editor for one eval case — typed inputs, not raw JSON. Known scalar fields
// render as inputs; nested objects (evidence / applicant / dimension / expect) render as
// labeled sub-sections with add/remove (see StructuredFields). The `key` field is fixed
// while editing (it's the identity the upsert keys on); a NEW case lets you set it.
//
// Templates seed a new case with the family's expected shape so you're filling fields, not
// inventing structure. Save writes to the versioned fixture FILE (server-validated); the
// operator commits to git.

// Fields are grouped by CONSUMER (see each fixture's `_comment`): metadata is harness-only;
// input goes to the scoring model; evidence + judge/prompt are what the judge sees.
const TEMPLATES: Record<string, FieldObject> = {
  live_scoring: {
    key: "",
    metadata: { note: "", expect: { score_equals: 0 } },
    input: {
      applicant: { facts: {}, essays: { essay: "" } },
      dimension: { key: "", name: "", definition: "", high_end: "", low_end: "" },
    },
    judge: {
      question:
        "Given the dimension and the applicant's cited evidence, decide whether the returned score and confidence are SUPPORTED or UNSUPPORTED by that evidence — judge the score as produced, whatever its value.",
    },
  },
  live_consolidation: {
    key: "",
    metadata: { pass: "consolidation", note: "", expected: "keep", label_rationale: "" },
    given: {
      pair: [
        { key: "", name: "", definition: "" },
        { key: "", name: "", definition: "" },
      ],
    },
    judge: {
      question:
        "Decide MERGE (same underlying concept, a duplicate) or KEEP (genuinely distinct axes that only correlate) for these two dimension definitions.",
    },
  },
  live_matching: {
    key: "",
    metadata: { pass: "matching", note: "", expected: "matches", label_rationale: "" },
    given: {
      prior: [{ key: "", name: "", definition: "" }],
      new: [{ key: "", name: "", definition: "" }],
    },
  },
  live_decomposition: {
    key: "",
    metadata: { pass: "decomposition", note: "", expected: "merge", label_rationale: "" },
    given: {
      reports: [
        [{ key: "", name: "", definition: "" }],
        [{ key: "", name: "", definition: "" }],
      ],
    },
  },
  judge: {
    key: "",
    metadata: { pass: "scoring", title: "", expected: "supported", label_rationale: "" },
    evidence: { dimension: "", dimension_definition: "", cited_evidence: "", score: 0 },
    prompt: {
      question:
        "Given the dimension and the applicant's cited evidence, decide whether the score is SUPPORTED or UNSUPPORTED by that evidence.",
    },
  },
};

export function EvalCaseEditor(props: {
  evalKey: "live_scoring" | "live_consolidation" | "live_matching" | "live_decomposition" | "judge";
  existing: Record<string, unknown> | null;
  error: string | null; // server-side validation error, if any
  onCancel: () => void;
  onSave: (c: FieldObject) => void;
}): ReactNode {
  const [value, setValue] = useState<FieldObject>(
    () => (props.existing as FieldObject | null) ?? TEMPLATES[props.evalKey],
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
