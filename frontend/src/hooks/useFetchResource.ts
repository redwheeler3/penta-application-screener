import { useCallback, useEffect, useRef, useState } from "react";

// Shared read-only resource state. A panel owns its copy and wording, while this hook owns the
// request lifecycle and gives every failed load an in-place retry without remounting the tab.
export type FetchState = "loading" | "ready" | "error";

export function useFetchResource<T>(fetcher: () => Promise<T>): {
  data: T | null;
  state: FetchState;
  reload: () => Promise<void>;
} {
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<FetchState>("loading");
  const fetcherRef = useRef(fetcher);
  const live = useRef(true);

  fetcherRef.current = fetcher;

  const reload = useCallback(async (): Promise<void> => {
    setState("loading");
    try {
      const next = await fetcherRef.current();
      if (!live.current) return;
      setData(next);
      setState("ready");
    } catch {
      if (live.current) setState("error");
    }
  }, []);

  useEffect(() => {
    live.current = true;
    void reload();
    return () => {
      live.current = false;
    };
  }, [reload]);

  return { data, state, reload };
}
