import { type ReactNode } from "react";

/** Consistent in-place recovery for a failed, read-only panel request. */
export function RetryLoadError(props: { message: string; onRetry: () => void }): ReactNode {
  return (
    <div className="inline-load-error" role="alert">
      <p className="panel-hint">{props.message}</p>
      <button type="button" className="secondary-button" onClick={props.onRetry}>
        Retry
      </button>
    </div>
  );
}
