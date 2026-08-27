import type { ReactNode } from "react";
import { Info } from "lucide-react";

// The screening-check toggle group, shared by the member's Eligibility Settings and the
// admin's Committee Defaults. Both edit `disabledChecks`; `onToggle` supplies the
// surface-specific persistence behavior.

// A compact info icon carrying a check's plain-language description. Rendered as a CSS
// tooltip (not native title=) so the show delay is ours — native title sits at a
// browser-fixed ~1.5s; this reveals in ~200ms on hover/focus. aria-label keeps it legible
// to screen readers, and the icon is focusable (tabIndex) so keyboard users get it too.
export function CheckInfo(props: { description: string; label: string }): ReactNode {
  return (
    <span
      className="check-info"
      tabIndex={0}
      aria-label={`${props.label}: ${props.description}`}
    >
      <Info size={13} aria-hidden="true" />
      <span className="check-info-tip" role="tooltip">
        {props.description}
      </span>
    </span>
  );
}

// One labeled group of check toggles (Deterministic rules / AI screening checks). A check is
// ON when it is NOT in `disabledChecks`. Sorted by label (defensively — the catalogs are
// already alphabetical). Each row carries its description as a hover/reader tooltip.
export function CheckGroup(props: {
  title: string;
  hint?: string;
  checks: readonly { id: string; label: string; description: string }[];
  disabledChecks: string[];
  onToggle: (id: string, on: boolean) => void;
}): ReactNode {
  const { title, hint, checks, disabledChecks, onToggle } = props;
  return (
    <div className="check-group">
      <h4>{title}</h4>
      {hint ? <p className="rules-hint">{hint}</p> : null}
      <div className="rules-grid">
        {[...checks].sort((a, b) => a.label.localeCompare(b.label)).map((check) => (
          <label key={check.id} className="checkbox-label rule-toggle">
            <input
              type="checkbox"
              checked={!disabledChecks.includes(check.id)}
              onChange={(event) => onToggle(check.id, event.target.checked)}
            />
            <span>{check.label}</span>
            <CheckInfo description={check.description} label={check.label} />
          </label>
        ))}
      </div>
    </div>
  );
}
