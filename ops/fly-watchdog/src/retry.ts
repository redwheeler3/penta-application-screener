export async function retryOnce<T>(
  operation: () => Promise<T>,
  delayMs: number,
  wait: (delayMs: number) => Promise<void> = (delay) =>
    new Promise((resolve) => setTimeout(resolve, delay)),
): Promise<T> {
  try {
    return await operation();
  } catch {
    await wait(delayMs);
    return operation();
  }
}
