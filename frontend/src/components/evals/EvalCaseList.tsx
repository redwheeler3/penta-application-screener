import { fixtureCaseIdentity } from "../../api/evals";
import type { ReactNode } from "react";
import { AI_PASS_PIPELINE_ORDER } from "../../constants";
import type { EvalCaseOutcomesByMode, EvalRunOption } from "../../types";
import { evalCaseStatus } from "./evalResultPresentation";

// The case list, optionally grouped by a field (judge: by production pass).
export function EvalCaseList(props: {
  cases: Record<string, unknown>[] | null;
  groupBy?: string;
  scopedByFamily?: boolean;
  selected: string | null;
  caseResults: Record<string, EvalCaseOutcomesByMode>;
  // The tab's run modes, in button order — one dot per mode so live + stability read as two
  // distinct indicators (not one aggregate that hides which check is in what state).
  modes: EvalRunOption[];
  onSelect: (key: string) => void;
}): ReactNode {
  const { cases } = props;
  if (cases === null) return <p className="eval-hint">Loading…</p>;
  if (!cases.length) return <p className="eval-hint">No cases yet.</p>;

  // The grouping/label fields (pass, expected) live in the harness-only `metadata` block.
  const meta = (c: Record<string, unknown>) => (c.metadata ?? {}) as Record<string, unknown>;

  // Cases within a group (or the whole flat list) read alphabetically by key, so a case is easy
  // to find regardless of file order.
  const byKey = (items: Record<string, unknown>[]) =>
    [...items].sort((a, b) => String(a.key).localeCompare(String(b.key)));

  const groups: { heading: string | null; items: Record<string, unknown>[] }[] = [];
  if (props.groupBy) {
    const byGroup = new Map<string, Record<string, unknown>[]>();
    for (const c of cases) {
      const g = String(meta(c)[props.groupBy] ?? "consolidation"); // judge default pass
      const group = byGroup.get(g);
      if (group) group.push(c);
      else byGroup.set(g, [c]);
    }
    // Order groups by PIPELINE order (matches the eval subtabs + how the app runs), not
    // alphabetically — so the judge's per-pass groups read screening → decomposition → matching
    // → scoring → consolidation. Any group not in the list sorts after, alphabetically.
    const order = (h: string) => {
      const i = (AI_PASS_PIPELINE_ORDER as readonly string[]).indexOf(h);
      return i === -1 ? AI_PASS_PIPELINE_ORDER.length : i;
    };
    const sorted = [...byGroup.entries()].sort(([a], [b]) => order(a) - order(b) || a.localeCompare(b));
    for (const [heading, items] of sorted) groups.push({ heading, items: byKey(items) });
  } else {
    groups.push({ heading: null, items: byKey(cases) });
  }

  return (
    <div className="eval-case-list">
      {groups.map((g) => (
        <div key={g.heading ?? "all"} className="eval-case-group">
          {g.heading ? <div className="eval-case-group-head">{g.heading}</div> : null}
          {g.items.map((c) => {
            const key = fixtureCaseIdentity(c, props.scopedByFamily);
            const modeMap = props.caseResults[key] ?? {};
            // ALWAYS one dot per mode, in button order (left = first mode, e.g. live; right =
            // stability). A mode not yet run shows grey, so position tells you which ran: e.g.
            // green+grey = live passed, stability not run yet. Only render the cluster once a
            // tab has >1 mode OR any result exists (a single-mode tab with no runs stays clean).
            const showDots = props.modes.length > 1 || props.modes.some((m) => modeMap[m.evalKey]);
            return (
              <button
                key={key}
                type="button"
                className={`eval-case-item${props.selected === key ? " selected" : ""}`}
                onClick={() => props.onSelect(key)}
              >
                {showDots ? (
                  <span className="eval-case-dots">
                    {props.modes.map((m) => {
                      const result = modeMap[m.evalKey];
                      const dot = result ? evalCaseStatus(result) : "empty";
                      return (
                        <span
                          key={m.evalKey}
                          className={`eval-case-dot ${dot}`}
                          title={`${m.label}: ${result ? dot : "not run"}`}
                        />
                      );
                    })}
                  </span>
                ) : null}
                <span className="eval-case-item-key">{String(c.key)}</span>
                {meta(c).expected !== undefined ? (
                  <span className="eval-case-item-expected">{expectedLabel(meta(c).expected)}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// A compact label for a case's `metadata.expected` chip. Categorical labels are strings;
// scoring is a band ({score_min, score_max, confidence?}); screening is {fires, absent}.
// Mirrors the backend _seed_str so a case reads the same in the list and the run marker.
function expectedLabel(expected: unknown): string {
  if (typeof expected === "string") return expected;
  if (expected && typeof expected === "object") {
    const e = expected as Record<string, unknown>;
    if ("fires" in e || "absent" in e) {
      const parts: string[] = [];
      const fires = e.fires as string[] | undefined;
      const absent = e.absent as string[] | undefined;
      if (fires?.length) parts.push(`fires: ${fires.join(", ")}`);
      if (absent?.length) parts.push(`absent: ${absent.join(", ")}`);
      return parts.join(" · ") || "clean";
    }
    if ("score_min" in e || "score_max" in e || "confidence" in e) {
      const lo = e.score_min ?? "-1";
      const hi = e.score_max ?? "1";
      const conf = e.confidence ? ` ${e.confidence}` : "";
      return `[${lo}, ${hi}]${conf}`;
    }
  }
  return String(expected);
}
