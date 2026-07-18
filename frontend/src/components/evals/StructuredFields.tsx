import { type ReactNode } from "react";

// A field-level editor for an eval case — no raw JSON. A case is a nested object whose
// shape varies by family (a judge case has evidence{key_a, definition_a, …}; a live-scoring
// case has applicant{facts, essays}, dimension{…}, expect{…}). Rather than a rigid per-family
// form, this renders GENERICALLY and usefully:
//   - a scalar (string/number/bool) → a labeled typed input (textarea for long text)
//   - a nested object → a titled section of labeled rows, each removable, with "+ add field"
// so any family is editable at the field level, and a new evidence shape needs no new code.
//
// Values are edited immutably against a single `value` object the parent owns; every change
// calls onChange with the next object. Keys the caller marks readOnly (e.g. `key`, `pass`)
// render as fixed labels.

export type FieldValue = string | number | boolean | null | FieldObject | FieldValue[];
export type FieldObject = { [k: string]: FieldValue };

// Humanize a snake_case key for a label ("cited_evidence" → "Cited evidence").
function label(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function setAt(obj: FieldObject, path: string[], next: FieldValue): FieldObject {
  if (path.length === 0) return obj;
  const [head, ...rest] = path;
  const child = obj[head];
  return {
    ...obj,
    [head]:
      rest.length === 0
        ? next
        : setAt((child && typeof child === "object" && !Array.isArray(child) ? child : {}) as FieldObject, rest, next),
  };
}

function removeAt(obj: FieldObject, path: string[]): FieldObject {
  if (path.length === 0) return obj;
  const [head, ...rest] = path;
  if (rest.length === 0) {
    const { [head]: _drop, ...keep } = obj;
    return keep;
  }
  const child = obj[head];
  if (!child || typeof child !== "object" || Array.isArray(child)) return obj;
  return { ...obj, [head]: removeAt(child as FieldObject, rest) };
}

function ScalarInput(props: {
  value: string | number | boolean | null;
  onChange: (v: FieldValue) => void;
}): ReactNode {
  const { value } = props;
  if (typeof value === "boolean") {
    return (
      <label className="eval-field-bool">
        <input type="checkbox" checked={value} onChange={(e) => props.onChange(e.target.checked)} /> {String(value)}
      </label>
    );
  }
  if (typeof value === "number") {
    return (
      <input
        type="number"
        step="any"
        className="eval-field-input"
        value={value}
        onChange={(e) => props.onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      />
    );
  }
  const text = value ?? "";
  // Long strings get a growing textarea; short ones a single-line input.
  if (String(text).length > 60) {
    return (
      <textarea
        className="eval-field-textarea"
        value={String(text)}
        rows={Math.min(10, Math.max(2, Math.ceil(String(text).length / 70)))}
        onChange={(e) => props.onChange(e.target.value)}
      />
    );
  }
  return (
    <input
      type="text"
      className="eval-field-input"
      value={String(text)}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
}

// One object rendered as a section of labeled, removable rows + an add-field control.
function ObjectSection(props: {
  obj: FieldObject;
  path: string[];
  readOnlyKeys: Set<string>;
  onChange: (next: FieldValue, path: string[]) => void;
  onRemove: (path: string[]) => void;
  depth: number;
}): ReactNode {
  const { obj, path } = props;
  return (
    <div className={`eval-fields depth-${Math.min(props.depth, 2)}`}>
      {Object.entries(obj).map(([k, v]) => {
        const childPath = [...path, k];
        const isObj = v !== null && typeof v === "object" && !Array.isArray(v);
        const locked = props.depth === 0 && props.readOnlyKeys.has(k);
        return (
          <div key={k} className={`eval-field-row${isObj ? " is-object" : ""}`}>
            <div className="eval-field-labelrow">
              <span className="eval-field-label">{label(k)}</span>
              {!locked ? (
                <button
                  type="button"
                  className="eval-field-remove"
                  aria-label={`Remove ${k}`}
                  title="Remove field"
                  onClick={() => props.onRemove(childPath)}
                >
                  ✕
                </button>
              ) : null}
            </div>
            {isObj ? (
              <ObjectSection
                obj={v as FieldObject}
                path={childPath}
                readOnlyKeys={props.readOnlyKeys}
                onChange={props.onChange}
                onRemove={props.onRemove}
                depth={props.depth + 1}
              />
            ) : locked ? (
              <span className="eval-field-locked">{String(v ?? "")}</span>
            ) : (
              <ScalarInput value={v as string | number | boolean | null} onChange={(nv) => props.onChange(nv, childPath)} />
            )}
          </div>
        );
      })}
      <AddField onAdd={(key, kind) => props.onChange(kind === "object" ? {} : "", [...path, key])} existing={obj} />
    </div>
  );
}

function AddField(props: { onAdd: (key: string, kind: "text" | "object") => void; existing: FieldObject }): ReactNode {
  return (
    <div className="eval-field-add">
      <button
        type="button"
        className="eval-link"
        onClick={() => {
          const key = window.prompt("New field name (snake_case):")?.trim();
          if (!key) return;
          if (key in props.existing) {
            window.alert(`A field named "${key}" already exists.`);
            return;
          }
          props.onAdd(key, "text");
        }}
      >
        + add field
      </button>
    </div>
  );
}

export function StructuredFields(props: {
  value: FieldObject;
  readOnlyKeys?: string[];
  onChange: (next: FieldObject) => void;
}): ReactNode {
  const readOnly = new Set(props.readOnlyKeys ?? []);
  return (
    <ObjectSection
      obj={props.value}
      path={[]}
      readOnlyKeys={readOnly}
      depth={0}
      onChange={(next, path) => props.onChange(setAt(props.value, path, next))}
      onRemove={(path) => props.onChange(removeAt(props.value, path))}
    />
  );
}
