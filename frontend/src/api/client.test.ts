import { expect, it } from "vitest";

import { streamNdjson } from "./client";
import type { ThinkingEvent } from "../types";

function chunks(parts: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(part);
      controller.close();
    },
  });
}

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
