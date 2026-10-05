import { apiBaseUrl } from "../constants";
import type {
  EvalStreamEvent,
  RankingStreamEvent,
  ScreeningStreamEvent,
} from "../types";

const GET_TIMEOUT_MS = 15_000;
const ACTION_REQUEST_TIMEOUT_MS = 30_000;

export type RequestIdentity = { kind: "committee" | "applicant"; id: number | null };
export type ApiClient = {
  request: typeof request;
  getJson: typeof getJson;
  streamRequest: typeof streamRequest;
};

export function signalSessionChange(kind: RequestIdentity["kind"], reason: "credentials" | "mismatch" = "credentials") {
  window.dispatchEvent(new CustomEvent("penta-session-changed", { detail: { kind, reason } }));
  if (reason === "credentials") {
    try { localStorage.setItem(`penta-session-change:${kind}`, String(Date.now())); } catch { /* Focus rechecks too. */ }
  }
}

/** Capture the displayed identity once; queued callbacks retain this client. */
export function identityClient(identity: RequestIdentity): ApiClient {
  const { kind, id } = identity;
  const expected = `${kind}:${id ?? "none"}`;
  async function boundRequest(path: string, init: RequestInit = {}, timeoutMs = ACTION_REQUEST_TIMEOUT_MS, streaming = false) {
    const headers = new Headers(init.headers);
    headers.set("X-Penta-Identity", expected);
    const response = await fetchResponse(path, { ...init, headers }, timeoutMs, streaming);
    if (response.status === 409) {
      const body = await response.clone().json().catch(() => null);
      if (body?.code === "session_changed") {
        signalSessionChange(kind, "mismatch");
      }
    }
    return response;
  }
  return {
    request: boundRequest,
    async getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
      const response = await boundRequest(path, { signal }, GET_TIMEOUT_MS);
      if (!response.ok) throw new Error(`GET ${path} failed (HTTP ${response.status})`);
      return response.json() as Promise<T>;
    },
    streamRequest: (path, signal) => boundRequest(path, { method: "POST", signal }, ACTION_REQUEST_TIMEOUT_MS, true),
  };
}

/** Serialize credential exchanges across tabs; ordinary reads/writes remain parallel. */
export async function credentialRequest(kind: RequestIdentity["kind"], path: string, init: RequestInit, client: ApiClient = publicClient) {
  const exchange = async () => {
    const response = await client.request(path, init);
    if (response.ok) signalSessionChange(kind);
    return response;
  };
  return navigator.locks ? navigator.locks.request(`penta-sign-in:${kind}`, exchange) : exchange();
}

/** Unbound calls are for public/bootstrap endpoints and manual API harnesses. */
export const publicClient: ApiClient = { request, getJson, streamRequest };

export function url(path: string): string {
  return `${apiBaseUrl}${path}`;
}

export async function request(
  path: string,
  init: RequestInit = {},
  timeoutMs = ACTION_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  return fetchResponse(path, init, timeoutMs, false);
}

async function fetchResponse(
  path: string, init: RequestInit, timeoutMs: number, streaming: boolean,
): Promise<Response> {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const signal = callerSignal ? AbortSignal.any([callerSignal, controller.signal]) : controller.signal;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url(path), { ...init, credentials: "include", signal });
    if (streaming && response.ok) return response;
    // Ordinary API responses acknowledge an action only after their complete body
    // arrives. Keep the deadline active through that read, including error bodies.
    const body = response.body === null ? null : await response.arrayBuffer();
    return new Response(body, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
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
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, GET_TIMEOUT_MS);
  if (!response.ok) {
    throw new Error(`GET ${path} failed (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

export function streamRequest(path: string, signal?: AbortSignal): Promise<Response> {
  // The deadline bounds the handshake; a successful AI stream can run for minutes.
  // Its caller signal still owns cancellation after the headers have arrived.
  return fetchResponse(path, { method: "POST", signal }, ACTION_REQUEST_TIMEOUT_MS, true);
}

export async function streamNdjson<
  TEvent extends
    | ScreeningStreamEvent
    | RankingStreamEvent
    | EvalStreamEvent,
>(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: TEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function deliver(line: string) {
    if (!line.trim()) return;
    let event: TEvent;
    try {
      event = JSON.parse(line) as TEvent;
    } catch {
      throw new Error("The progress stream contained an incomplete or invalid message.");
    }
    onEvent(event);
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        deliver(buffer + decoder.decode());
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) deliver(line);
    }
  } finally {
    // A parser/consumer failure must close the HTTP stream, not leave paid work
    // running after its only consumer stopped reading.
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
