import { apiBaseUrl } from "../constants";
import type { EvalStreamEvent, RankingStreamEvent, ScreeningStreamEvent } from "../types";

const GET_TIMEOUT_MS = 15_000;
const ACTION_REQUEST_TIMEOUT_MS = 30_000;

export function url(path: string): string {
  return `${apiBaseUrl}${path}`;
}

export async function request(
  path: string,
  init: RequestInit = {},
  timeoutMs = ACTION_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const abortForCaller = () => controller.abort();
  if (callerSignal?.aborted) {
    controller.abort();
  } else {
    callerSignal?.addEventListener("abort", abortForCaller, { once: true });
  }
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url(path), { ...init, credentials: "include", signal: controller.signal });
  } catch (error) {
    if (callerSignal?.aborted) throw error;
    const detail = error instanceof DOMException && error.name === "AbortError"
      ? "Request timed out. Please try again."
      : "Network request failed. Please try again.";
    return new Response(JSON.stringify({ detail }), {
      status: 503,
      headers: { "Content-Type": "application/problem+json" },
    });
  } finally {
    window.clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortForCaller);
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, GET_TIMEOUT_MS);
  if (!response.ok) {
    throw new Error(`GET ${path} failed (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

export function streamRequest(path: string): Promise<Response> {
  return request(path, { method: "POST" });
}

export async function streamNdjson<
  TEvent extends ScreeningStreamEvent | RankingStreamEvent | EvalStreamEvent,
>(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: TEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      onEvent(JSON.parse(line) as TEvent);
    }
  }
}
