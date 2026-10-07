import { type ReactNode } from "react";
import { NumberInput } from "../shared/NumberInput";

export type FieldValue = string | number | boolean | null | FieldObject | FieldValue[];
export type FieldObject = { [k: string]: FieldValue };
type FieldContext = { path: string[]; readOnlyKeys: string[] };

function label(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** New list entries keep the preceding entry's structure, without copying its answers. */
function blankLike(value: FieldValue): FieldValue {
  if (Array.isArray(value)) return value.map(blankLike);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, blankLike(v)]));
  if (typeof value === "number") return 0;
  if (typeof value === "boolean") return false;
  return "";
}

function FieldRow(props: FieldContext & {
  name: string; value: FieldValue; onChange: (next: FieldValue) => void; onRemove: () => void;
}): ReactNode {
  const here = props.path.join(".");
  const locked = props.readOnlyKeys.some((key) => here === key || here.startsWith(`${key}.`));
  const containsLock = props.readOnlyKeys.some((key) => key.startsWith(`${here}.`));
  return <div className="eval-field-row">
    <div className="eval-field-labelrow">
      <span className="eval-field-label">{props.name}</span>
      {!locked && !containsLock ? <button type="button" className="eval-field-remove"
        aria-label={`Remove ${props.path.at(-1)}`} title="Remove field" onClick={props.onRemove}>✕</button> : null}
    </div>
    {locked ? <span className="eval-field-locked">{String(props.value ?? "")}</span>
      : <ValueInput {...props} />}
  </div>;
}

function ValueInput(props: FieldContext & { value: FieldValue; onChange: (next: FieldValue) => void }): ReactNode {
  const { value, onChange, path, readOnlyKeys } = props;
  const name = path.map(label).join(" / ");
  if (Array.isArray(value)) {
    return <div className="eval-fields depth-1">
      {value.map((item, index) => <FieldRow key={index} name={`Item ${index + 1}`} value={item}
        path={[...path, String(index)]} readOnlyKeys={readOnlyKeys}
        onChange={(next) => onChange(value.map((entry, i) => i === index ? next : entry))}
        onRemove={() => onChange(value.filter((_entry, i) => i !== index))} />)}
      <div className="eval-field-add">
        <button type="button" className="eval-link" onClick={() => onChange([...value, blankLike(value.at(-1) ?? "")])}>+ Add item</button>
        {value.length === 0 ? <>
          {" "}<button type="button" className="eval-link" onClick={() => onChange([{}])}>+ Add object</button>
          {" "}<button type="button" className="eval-link" onClick={() => onChange([[]])}>+ Add list</button>
        </> : null}
      </div>
    </div>;
  }
  if (value !== null && typeof value === "object") {
    return <ObjectSection obj={value} path={path} readOnlyKeys={readOnlyKeys} onChange={onChange} />;
  }
  if (typeof value === "boolean") return <label className="eval-field-bool">
    <input type="checkbox" aria-label={name} checked={value} onChange={(event) => onChange(event.target.checked)} /> {String(value)}
  </label>;
  if (typeof value === "number") return <NumberInput className="eval-field-input" aria-label={name}
    value={value} onChange={(next) => onChange(next ?? 0)} />;
  const text = value ?? "";
  // Keep the same control mounted as text grows, preserving focus and selection.
  return <textarea className="eval-field-textarea" aria-label={name} value={text}
    rows={Math.min(10, Math.max(1, Math.ceil(text.length / 70)))} onChange={(event) => onChange(event.target.value)} />;
}

function ObjectSection(props: FieldContext & { obj: FieldObject; onChange: (next: FieldObject) => void }): ReactNode {
  const { obj, path, readOnlyKeys, onChange } = props;
  function addField() {
    const key = window.prompt("New field name (snake_case):")?.trim();
    if (!key) return;
    if (key in obj) { window.alert(`A field named "${key}" already exists.`); return; }
    onChange({ ...obj, [key]: "" });
  }
  return <div className={`eval-fields depth-${Math.min(path.length, 2)}`}>
    {Object.entries(obj).map(([key, value]) => <FieldRow key={key} name={label(key)} value={value}
      path={[...path, key]} readOnlyKeys={readOnlyKeys}
      onChange={(next) => onChange({ ...obj, [key]: next })}
      onRemove={() => {
        const { [key]: _removed, ...rest } = obj;
        onChange(rest);
      }} />)}
    <div className="eval-field-add"><button type="button" className="eval-link" onClick={addField}>+ add field</button></div>
  </div>;
}

/** Immutable field editing for the scalar, object, and list shapes in eval fixtures. */
export function StructuredFields(props: { value: FieldObject; readOnlyKeys?: string[]; onChange: (next: FieldObject) => void }): ReactNode {
  return <ObjectSection obj={props.value} path={[]} readOnlyKeys={props.readOnlyKeys ?? []} onChange={props.onChange} />;
}
