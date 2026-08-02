import { useRef, useState } from "react";
import type { Toast, ToastAction } from "../types";

const TOAST_DURATION_MS = 10000;

export interface ToastControls {
  toasts: Toast[];
  /** A success toast — auto-dismisses after {@link TOAST_DURATION_MS}. */
  showToast: (message: string) => void;
  /** An error toast — persists until the user dismisses it. */
  showError: (message: string) => void;
  /** A degraded-run warning — like an error, stays until acknowledged. An optional action
   * adds a recovery button (e.g. "Reload" on the stale-ranking notice); returns the toast id
   * so a caller can dismiss/de-dupe it. */
  showWarning: (message: string, action?: ToastAction) => number;
  dismissToast: (id: number) => void;
}

/** The bottom-right toast stack. Success toasts auto-dismiss; error and warning
 * toasts persist until dismissed. A monotonic sequence gives each a unique id so
 * they stack rather than clobber. Self-contained — no dependency on app state. */
export function useToasts(): ToastControls {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);

  // Append a toast with a fresh monotonic id and return the id for later dismissal.
  function push(variant: Toast["variant"], message: string, action?: ToastAction): number {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant, action }]);
    return id;
  }

  function showToast(message: string) {
    const id = push("success", message);
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, TOAST_DURATION_MS);
  }

  // No auto-dismiss on error/warning: both stay until the user reads and dismisses
  // them — non-fatal, but worth a deliberate acknowledgement.
  function showError(message: string) {
    push("error", message);
  }

  function showWarning(message: string, action?: ToastAction): number {
    return push("warning", message, action);
  }

  function dismissToast(id: number) {
    setToasts((current) => current.filter((t) => t.id !== id));
  }

  return { toasts, showToast, showError, showWarning, dismissToast };
}
