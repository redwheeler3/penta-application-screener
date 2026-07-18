import { type ReactNode } from "react";

// The app's inline confirm card — the same visual language as the workflow's pre-spend
// confirm (`.run-confirm`), used before any eval action that spends money or overwrites a
// committed file. NOT window.confirm: styled, in-flow, and consistent with Sync/Screen/Rank.
export function InlineConfirm(props: {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}): ReactNode {
  return (
    <div className="run-confirm eval-run-confirm" role="alertdialog" aria-label={props.title}>
      <div className="run-confirm-body">
        <strong>{props.title}</strong>
        <p>{props.body}</p>
      </div>
      <div className="run-confirm-actions">
        <button type="button" className="primary-button" onClick={props.onConfirm}>
          {props.confirmLabel ?? "Confirm & run"}
        </button>
        <button type="button" className="secondary-button" onClick={props.onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
