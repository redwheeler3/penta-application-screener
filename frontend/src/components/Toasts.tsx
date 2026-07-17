// Bottom-right toast stack. Success toasts auto-dismiss (handled by the caller);
// error AND warning toasts persist (with a copy button) until dismissed — a warning
// is non-fatal but still worth a deliberate read. One mechanism for every workflow step.
import { Clipboard, X } from "lucide-react";
import { type ReactNode } from "react";
import type { Toast } from "../types";

const VARIANT_CLASS = {
  success: "toast-success",
  error: "toast-error",
  warning: "toast-warning",
} as const;

export function Toasts(props: { toasts: Toast[]; onDismiss: (id: number) => void }): ReactNode {
  if (props.toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {props.toasts.map((toast) => {
        // Error and warning both persist and get a copy button; only success auto-dismisses.
        const persists = toast.variant === "error" || toast.variant === "warning";
        return (
          <div
            key={toast.id}
            className={`toast ${VARIANT_CLASS[toast.variant]}`}
            aria-live={persists ? "assertive" : "polite"}
            role={persists ? "alert" : "status"}
          >
            <div className="toast-message">{toast.message}</div>
            <div className="toast-actions">
              {persists ? (
                <button
                  className="toast-button"
                  aria-label="Copy message"
                  title="Copy message"
                  onClick={() => navigator.clipboard.writeText(toast.message)}
                >
                  <Clipboard size={16} />
                </button>
              ) : null}
              <button
                className="toast-button"
                aria-label="Dismiss notification"
                title="Dismiss notification"
                onClick={() => props.onDismiss(toast.id)}
              >
                <X size={16} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
