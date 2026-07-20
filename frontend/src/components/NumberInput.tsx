import { type InputHTMLAttributes, useEffect, useState } from "react";

// One number input used everywhere a number is typed (settings, eval case fields). It fixes two
// papercuts that plain <input type="number"> has:
//
//   1. Mouse-wheel over a focused number input silently changes its value — so scrolling the
//      page edits a field you didn't mean to touch. We render as type="text" (with
//      inputMode="decimal" so touch keyboards still show a number pad), and a text input has no
//      wheel-to-increment behaviour at all, so scrolling never mutates it.
//   2. A native number input rejects a leading-dot literal (".7" is not a valid floating-point
//      value per the HTML spec, so input.value reads ""), forcing you to type the zero. As text
//      we keep exactly what you type and normalize ".7" → "0.7" (and "-.5" → "-0.5") on the way
//      out, so ".7" just works.
//
// The parent owns a numeric `value`; we keep a local DRAFT string while focused so intermediate
// states ("", "-", ".", "0.") don't get stomped by re-parsing every keystroke. onChange fires
// with the parsed number (or null when the field is blank/only a sign/dot — the parent decides
// what a blank means, e.g. 0). Non-numeric characters are dropped so it stays a number field.

type Props = {
  value: number;
  onChange: (value: number | null) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "inputMode">;

// Keep only characters that can form a decimal number (digits, one dot, one leading minus).
function sanitize(raw: string): string {
  // Strip anything that isn't a digit, dot, or minus; collapse to one leading minus + one dot.
  let s = raw.replace(/[^0-9.-]/g, "");
  const negative = s.startsWith("-");
  s = s.replace(/-/g, "");
  const firstDot = s.indexOf(".");
  if (firstDot !== -1) {
    s = s.slice(0, firstDot + 1) + s.slice(firstDot + 1).replace(/\./g, "");
  }
  return (negative ? "-" : "") + s;
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

export function NumberInput({ value, onChange, ...rest }: Props) {
  const [draft, setDraft] = useState<string>(String(value));
  const [focused, setFocused] = useState(false);

  // While unfocused, mirror the parent's value (a programmatic change should show). While the
  // user is typing we leave the draft alone so mid-edit states survive.
  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);

  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      value={draft}
      onFocus={() => setFocused(true)}
      onChange={(event) => {
        const next = sanitize(event.target.value);
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
