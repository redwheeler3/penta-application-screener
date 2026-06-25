// Bottom-right toast stack. Success toasts auto-dismiss (handled by the caller);
// error toasts persist (with a copy button) until dismissed. One mechanism for
// every workflow step.
import { Clipboard, X } from "lucide-react";
import { type ReactNode } from "react";
import type { Toast } from "../types";

export function Toasts(props: { toasts: Toast[]; onDismiss: (id: number) => void }): ReactNode {
  if (props.toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {props.toasts.map((toast) => {
        const isError = toast.variant === "error";
        return (
          <div
            key={toast.id}
            className={`toast ${isError ? "toast-error" : "toast-success"}`}
            aria-live={isError ? "assertive" : "polite"}
            role={isError ? "alert" : "status"}
          >
            <div className="toast-message">{toast.message}</div>
            <div className="toast-actions">
              {isError ? (
                <button
                  className="toast-button"
                  aria-label="Copy error"
                  title="Copy error"
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
