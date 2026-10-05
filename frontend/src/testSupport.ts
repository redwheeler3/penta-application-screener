import { render, renderHook, type RenderOptions } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { RequestIdentityProvider } from "./api/identity";

/** Explicit synthetic committee context for isolated component/hook tests. */
function CommitteeTestIdentity({ children }: { children: ReactNode }) {
  return createElement(RequestIdentityProvider, { identity: { kind: "committee", id: 1 }, children });
}

export function renderCommittee(ui: ReactNode, options?: RenderOptions) {
  return render(ui, { wrapper: CommitteeTestIdentity, ...options });
}

export const renderCommitteeHook: typeof renderHook = (callback, options) =>
  renderHook(callback, { wrapper: CommitteeTestIdentity, ...options });

/** Control response order without timers in async regression tests. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
