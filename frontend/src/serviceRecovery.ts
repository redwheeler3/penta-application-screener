export type ServiceRecoveryStage = "waking" | "extended" | "failed";

const RETRY_INTERVAL_MS = 10_000;
const RETRY_DEADLINE_MS = 120_000;
const WAKING_MESSAGE_DELAY_MS = 5_000;
const EXTENDED_MESSAGE_DELAY_MS = 60_000;

/** Retry a read needed to enter the app while Fly wakes or recovers. */
export async function retryForServiceRecovery<T>(
  operation: () => Promise<T>,
  onStage: (stage: Exclude<ServiceRecoveryStage, "failed">) => void,
): Promise<T> {
  const startedAt = Date.now();
  let lastError: unknown = new Error("Service recovery timed out.");
  const wakingMessage = window.setTimeout(
    () => onStage("waking"),
    WAKING_MESSAGE_DELAY_MS,
  );
  const extendedMessage = window.setTimeout(
    () => onStage("extended"),
    EXTENDED_MESSAGE_DELAY_MS,
  );

  try {
    while (Date.now() - startedAt < RETRY_DEADLINE_MS) {
      const attemptStartedAt = Date.now();
      try {
        return await operation();
      } catch (error) {
        lastError = error;
      }

      const remaining = RETRY_DEADLINE_MS - (Date.now() - startedAt);
      if (remaining <= 0) break;
      const attemptDuration = Date.now() - attemptStartedAt;
      await new Promise((resolve) => window.setTimeout(
        resolve,
        Math.min(remaining, Math.max(0, RETRY_INTERVAL_MS - attemptDuration)),
      ));
    }
    throw lastError;
  } finally {
    window.clearTimeout(wakingMessage);
    window.clearTimeout(extendedMessage);
  }
}
