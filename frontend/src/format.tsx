import { type ReactNode } from "react";
import { FIELD_LABELS, FLAG_CATEGORY_LABELS, MONEY_FIELDS } from "./constants";
import type { CommitteeOpening } from "./types";

export function openingLabel(opening: CommitteeOpening): string {
  const moveIn = new Date(`${opening.moveInDate}T12:00:00`).toLocaleDateString("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return `${opening.unitSizeBedrooms}-bedroom · ${moveIn}`;
}

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// A USD amount at 4-decimal precision — the app's standard for AI spend (per-run cost,
// estimates, cache savings), where sub-cent figures are meaningful. Coarser 2-dp totals
// (block subtotals, the spending cap) format inline at their call sites.
export function money(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function reasoningEffortLabel(
  supportsReasoningEffort: boolean,
  effort: string | null,
): string {
  if (effort) return effort;
  return supportsReasoningEffort ? "not recorded" : "not used";
}

const PACIFIC_TIME_ZONE = "America/Vancouver";

// All app-generated timestamps are stored and returned as UTC. Render them in the
// co-op's local time rather than inheriting the browser's time zone.
export function formatPacificDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: PACIFIC_TIME_ZONE,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatPacificDate(value: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: PACIFIC_TIME_ZONE,
    dateStyle: "medium",
  }).format(new Date(value));
}

export function formatDateOnly(value: string): string {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium" }).format(
    new Date(`${value}T12:00:00`),
  );
}

export function flagCategoryLabel(category: string): string {
  return FLAG_CATEGORY_LABELS[category] ?? category;
}

// Map a relative fit band ("Strong fit" … "Limited") to a CSS modifier class.
// Derived from the label so the backend stays the single source of band names.
export function bandClass(band: string): string {
  return band.toLowerCase().replace(/[^a-z]+/g, "-");
}

// A dimension SCORE (signed, -1..+1) as a qualitative band + CSS modifier — the
// applicant's standing on that axis (not the model's confidence). The scale is split
// into quarters: top quarter [0.5, +1] is a demonstrated strength (green); bottom
// quarter [-1, -0.5) is a demonstrated low (red); the two middle quarters [-0.5, 0.5)
// are neutral/weak-signal, where an unaddressed dimension (score 0) sits (blue).
export function scoreBand(score: number): { label: string; cls: string } {
  if (score >= 0.5) return { label: "Strong", cls: "score-strong" };
  if (score < -0.5) return { label: "Weak", cls: "score-weak" };
  return { label: "Neutral", cls: "score-neutral" };
}

// Percent complete (0–100) for a screening run, used for both the label text
// and the progress-bar width so the two never drift apart.
export function screeningPercent(progress: { processed: number; total: number }): number {
  return (progress.processed / progress.total) * 100;
}

export function formatArrayItem(item: unknown): string {
  if (typeof item !== "object" || item === null) return String(item);
  const obj = item as Record<string, unknown>;
  if ("first_name" in obj || "last_name" in obj) {
    const name = [obj.first_name, obj.last_name].filter(Boolean).join(" ");
    return obj.age != null ? `${name} (${obj.age})` : name || "—";
  }
  return Object.values(obj).filter((v) => v != null && v !== "").join(", ");
}

export function formatFieldValue(value: unknown, key?: string): ReactNode {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key && MONEY_FIELDS.has(key) && typeof value === "number") {
    return `$${value.toLocaleString()}`;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return (
      <ul className="field-list">
        {value.map((item, i) => (
          <li key={i}>{formatArrayItem(item)}</li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v != null && v !== "")
      .map(([, v]) => String(v))
      .join(", ");
  }
  return String(value);
}
