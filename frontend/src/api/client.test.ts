import { afterEach, expect, it, vi } from "vitest";

import { request, streamNdjson, streamRequest } from "./client";
import type { ThinkingEvent } from "../types";

function chunks(parts: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(part);
      controller.close();
    },
  });
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function stalledFetch() {
  vi.stubGlobal("fetch", vi.fn((_url, init: RequestInit) => Promise.resolve(new Response(new ReadableStream({
    start(controller) {
      init.signal!.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
    },
  })))));
}

it("times out an ordinary response body after its headers have arrived", async () => {
  vi.useFakeTimers();
  stalledFetch();
  const pending = request("/settings", {}, 100);
  await vi.advanceTimersByTimeAsync(100);
  const response = await pending;
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ detail: "Request timed out. Please try again." });
});

it("keeps caller cancellation attached to a live stream after the handshake", async () => {
  vi.useFakeTimers();
  stalledFetch();
  const controller = new AbortController();
  const response = await streamRequest("/ranking/run", controller.signal);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(controller.signal.aborted).toBe(false);
  const reading = response.body!.getReader().read();
  const rejected = expect(reading).rejects.toThrow("Aborted");
  controller.abort();
  await rejected;
});

it("cancels an open stream when an event consumer fails", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode('{"type":"ping","phase":"criteria"}\n')); },
    cancel,
  });
  await expect(streamNdjson(body, () => { throw new Error("consumer failed"); })).rejects.toThrow("consumer failed");
  expect(cancel).toHaveBeenCalledOnce();
  expect(body.locked).toBe(false);
});

it("parses fragmented Unicode and a final event without a newline", async () => {
  const first: ThinkingEvent = { type: "thinking", phase: "criteria", text: "A café" };
  const final: ThinkingEvent = { type: "thinking", phase: "criteria", text: "Finished" };
  const encoded = new TextEncoder().encode(`\n${JSON.stringify(first)}\n\n${JSON.stringify(final)}`);
  const body = chunks([...encoded].map((byte) => Uint8Array.of(byte)));
  const received: ThinkingEvent[] = [];
  await streamNdjson<ThinkingEvent>(body, (event) => received.push(event));
  expect(received).toEqual([first, final]);
  expect(body.locked).toBe(false);
});

it("reports truncated JSON and releases the stream reader", async () => {
  const body = chunks([new TextEncoder().encode('{"type":"summary"')]);
  await expect(streamNdjson(body, () => {})).rejects.toThrow("incomplete or invalid message");
  expect(body.locked).toBe(false);
});

it("releases the reader when processing an event fails", async () => {
  const body = chunks([new TextEncoder().encode('{"type":"ping","phase":"criteria"}\n')]);
  await expect(streamNdjson(body, () => { throw new Error("consumer failed"); }))
    .rejects.toThrow("consumer failed");
  expect(body.locked).toBe(false);
});
