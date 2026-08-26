import { AlertTriangle, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import type { AdminActions } from "../types";

export function AdminActionBanner(props: {
  actions: AdminActions | null;
  onReviewOpenings: () => void;
}): ReactNode {
  const openings = props.actions?.archivedOpeningsNeedingSelection ?? [];
  if (openings.length === 0) return null;

  return (
    <aside className="admin-action-banner no-print" role="alert">
      <AlertTriangle size={20} aria-hidden="true" />
      <div>
        <strong>Opening decision required</strong>
        <span>
          {openings.length === 1
            ? "An archived opening needs a final decision before closeout email can be sent."
            : `${openings.length} archived openings need a final decision before closeout email can be sent.`}
        </span>
      </div>
      <button type="button" onClick={props.onReviewOpenings}>
        Review {openings.length === 1 ? "opening" : "openings"}
        <ArrowRight size={16} aria-hidden="true" />
      </button>
    </aside>
  );
}
