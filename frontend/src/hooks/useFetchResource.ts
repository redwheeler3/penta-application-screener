import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRequestScope } from "./useRequestScope";

// Shared reloadable resource state. This hook owns request ordering and retry state; callers may
// replace the cached data directly when a successful mutation already returned the new value.
export type FetchState = "loading" | "ready" | "error";

export function useFetchResource<T>(
  fetcher: () => Promise<T>,
  options: {
    reloadKey?: string | number | boolean | null;
    onError?: () => void;
  } = {},
): {
  data: T | null;
  state: FetchState;
  reload: () => Promise<void>;
  setData: Dispatch<SetStateAction<T | null>>;
} {
  const [data, setStoredData] = useState<T | null>(null);
  const [state, setState] = useState<FetchState>("loading");
  const fetcherRef = useRef(fetcher);
  const onErrorRef = useRef(options.onError);
  const requests = useRequestScope(options.reloadKey ?? null);

  fetcherRef.current = fetcher;
  onErrorRef.current = options.onError;

  const reload = useCallback(async (): Promise<void> => {
    const isCurrent = requests.begin();
    setState("loading");
    try {
      const next = await fetcherRef.current();
      if (!isCurrent()) return;
      setStoredData(next);
      setState("ready");
    } catch {
      if (!isCurrent()) return;
      setState("error");
      onErrorRef.current?.();
    }
  }, [requests]);

  useEffect(() => {
    void reload();
  }, [reload, options.reloadKey]);

  const setData = useCallback<Dispatch<SetStateAction<T | null>>>((next) => {
    // A mutation response is newer server truth than any GET already in flight.
    requests.invalidate();
    setStoredData(next);
    setState("ready");
  }, [requests]);

  return { data, state, reload, setData };
}
