import { useEffect, useState } from "react";

import {
  fetchCachedEmailDeliveryStatus,
  refreshEmailDeliveryStatus,
} from "../api/emailDelivery";

export function useEmailDeliveryStatus(): boolean {
  const [delayed, setDelayed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function loadStatus() {
      try {
        const cached = await fetchCachedEmailDeliveryStatus(controller.signal);
        if (cached.available) setDelayed(cached.delayed);
      } catch {
        // A missing cache is equivalent to no advisory warning. Email access remains enabled.
      }
      try {
        // This separate request stays open while SocketLabs responds, preventing Fly from
        // suspending mid-refresh without delaying the login screen's first render.
        const refreshed = await refreshEmailDeliveryStatus(controller.signal);
        if (refreshed.available) setDelayed(refreshed.delayed);
      } catch {
        // Retain the cached value when provider reporting is unavailable.
      }
    }
    void loadStatus();
    return () => controller.abort();
  }, []);

  return delayed;
}
