import { type InputHTMLAttributes, useEffect, useState } from "react";

// Text inputs avoid wheel increments and preserve intermediate decimal edits such as ".7".
type Props = {
  value: number | null;
  onChange: (value: number | null) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "inputMode">;

// Accept one decimal or a complete grouped number. Joining arbitrary digit groups changes meaning.
function decimalDraft(raw: string): string | null {
  const value = raw.trim();
  if (/^-?\d*(?:\.\d*)?$/.test(value)) return value;
  return /^-?\d{1,3}(?:,\d{3})+(?:\.\d*)?$/.test(value) ? value.replaceAll(",", "") : null;
}

// ".7" → "0.7", "-.5" → "-0.5", "5." → "5." (left mid-edit); "" / "-" / "." → "" (not a number).
function normalize(s: string): string {
  if (s === "" || s === "-" || s === "." || s === "-.") return "";
  return s.replace(/^(-?)\./, "$10.");
}

function toNumber(s: string): number | null {
  const n = normalize(s);
  if (n === "") return null;
  const parsed = Number(n);
  return Number.isNaN(parsed) ? null : parsed;
}

type TextProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "inputMode" | "value"> & { textValue: string };

export function NumberInput(props: Props): React.JSX.Element;
export function NumberInput(props: TextProps): React.JSX.Element;
export function NumberInput(props: Props | TextProps) {
  // Amount fields own their raw text so invalid pasted input can be corrected in place.
  if ("textValue" in props) {
    const { textValue, ...rest } = props;
    return <input {...rest} type="text" inputMode="decimal" value={textValue} />;
  }
  return <NumericInput {...props} />;
}

function NumericInput({ value, onChange, ...rest }: Props) {
  const [draft, setDraft] = useState<string>(String(value ?? ""));
  const [focused, setFocused] = useState(false);

  // While unfocused, mirror the parent's value (a programmatic change should show). While the
  // user is typing we leave the draft alone so mid-edit states survive.
  useEffect(() => {
    if (!focused) setDraft(String(value ?? ""));
  }, [value, focused]);

  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      value={draft}
      onFocus={() => setFocused(true)}
      onChange={(event) => {
        const next = decimalDraft(event.target.value);
        if (next === null || (normalize(next) && !Number.isFinite(Number(next)))) return;
        setDraft(next);
        onChange(toNumber(next));
      }}
      onBlur={(event) => {
        setFocused(false);
        // Snap the displayed text to the normalized number (".7" → "0.7"); blank stays blank.
        const n = toNumber(draft);
        setDraft(n === null ? "" : String(n));
        rest.onBlur?.(event);
      }}
    />
  );
}
