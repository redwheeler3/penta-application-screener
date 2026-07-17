import { type ReactNode } from "react";
import { FIELD_LABELS, FLAG_CATEGORY_LABELS, MONEY_FIELDS } from "./constants";
import type { SettingsResponse } from "./types";

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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

// The configured sheet id from a server response: prefer the resolved URL, falling
// back to the bare id. Returns "" when no sheet is configured.
export function resolveSheetId(payload: SettingsResponse): string {
  return payload.googleSheetUrl || payload.settings.googleSheetId;
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

// An RFC 9457 problem+json body (the backend's one error shape). `code` is the
// stable machine identifier the UI can branch on; `detail`/`title` are human text.
export type Problem = {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  instance?: string;
  [key: string]: unknown; // extension members, e.g. capUsd
};

// Read a problem+json error body off a failed Response, returning a human message
// (detail, falling back to title). Returns null if the body isn't a problem (e.g.
// a network/HTML error), so callers can fall back to a status-based message.
export async function readProblem(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as Partial<Problem>;
    return body.detail ?? body.title ?? null;
  } catch {
    return null;
  }
}
