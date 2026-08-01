/** Retry a read-only operation after short quadratic backoff delays. Callers choose the
 * attempt count because recovery policy is product-specific, not a transport default. */
export async function retryWithBackoff<T>(
  operation: () => Promise<T>,
  attempts: number,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt < attempts - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 300 * (attempt + 1) ** 2));
      }
    }
  }
  throw lastError;
}
