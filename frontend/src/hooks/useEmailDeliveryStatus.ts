import { useEffect, useState } from "react";

import { fetchPublicEmailDeliveryStatus } from "../api/emailDelivery";

export function useEmailDeliveryStatus(): boolean {
  const [delayed, setDelayed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void fetchPublicEmailDeliveryStatus(controller.signal)
      .then((status) => setDelayed(status.delayed))
      // Delivery-status reporting is advisory. An unavailable provider report
      // must never disable email access or present an unsupported delay claim.
      .catch(() => setDelayed(false));
    return () => controller.abort();
  }, []);

  return delayed;
}
