import { useEffect, useState } from "react";

// Fetch once on mount and track loading/ready/error — the shared shape the Insights panels
// (match/consolidate/decompose audit, discovery, cost, metrics) all repeated. Returns the data
// (null until ready) and a state tag; each panel renders its own error/empty text, since those
// differ per panel. `fetcher` should be stable (a module-level api fn or a Promise.all of them);
// it runs exactly once. The `live` guard drops a resolve that lands after unmount.
export type FetchState = "loading" | "ready" | "error";

export function useFetchOnce<T>(fetcher: () => Promise<T>): { data: T | null; state: FetchState } {
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<FetchState>("loading");

  useEffect(() => {
    let live = true;
    fetcher()
      .then((d) => live && (setData(d), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
    // Mount-once: fetchers are stable module fns; re-running on identity churn isn't wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { data, state };
}
