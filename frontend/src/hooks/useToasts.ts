import { useRef, useState } from "react";
import type { Toast } from "../types";

const TOAST_DURATION_MS = 10000;

export interface ToastControls {
  toasts: Toast[];
  /** A success toast — auto-dismisses after {@link TOAST_DURATION_MS}. */
  showToast: (message: string) => void;
  /** An error toast — persists until the user dismisses it. */
  showError: (message: string) => void;
  /** A degraded-run warning — like an error, stays until acknowledged. */
  showWarning: (message: string) => void;
  dismissToast: (id: number) => void;
}

/** The bottom-right toast stack. Success toasts auto-dismiss; error and warning
 * toasts persist until dismissed. A monotonic sequence gives each a unique id so
 * they stack rather than clobber. Self-contained — no dependency on app state. */
export function useToasts(): ToastControls {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);

  function showToast(message: string) {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant: "success" }]);
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, TOAST_DURATION_MS);
  }

  function showError(message: string) {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant: "error" }]);
    // No auto-dismiss: errors stay until the user reads and dismisses them.
  }

  function showWarning(message: string) {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant: "warning" }]);
    // No auto-dismiss: a degraded-run warning should stay until the user reads it,
    // like an error — it's non-fatal but worth a deliberate acknowledgement.
  }

  function dismissToast(id: number) {
    setToasts((current) => current.filter((t) => t.id !== id));
  }

  return { toasts, showToast, showError, showWarning, dismissToast };
}
