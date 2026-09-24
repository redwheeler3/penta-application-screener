import type { ReactNode } from "react";

import { STATUS_LABELS } from "../../constants";
import type { AppStatus } from "../../types";

export function ApplicationStatusBadges(props: {
  selected: boolean;
  status: AppStatus;
}): ReactNode {
  return (
    <span className="application-status-badges">
      {props.selected ? (
        <span className="status-badge status-selected">Selected</span>
      ) : null}
      <span className={`status-badge status-${props.status}`}>
        {STATUS_LABELS[props.status]}
      </span>
    </span>
  );
}
