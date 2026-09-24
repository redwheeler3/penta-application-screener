import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

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
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<FetchState>("loading");
  const fetcherRef = useRef(fetcher);
  const onErrorRef = useRef(options.onError);
  const mounted = useRef(false);
  const requestVersion = useRef(0);

  fetcherRef.current = fetcher;
  onErrorRef.current = options.onError;

  const reload = useCallback(async (): Promise<void> => {
    const version = ++requestVersion.current;
    setState("loading");
    try {
      const next = await fetcherRef.current();
      if (!mounted.current || version !== requestVersion.current) return;
      setData(next);
      setState("ready");
    } catch {
      if (!mounted.current || version !== requestVersion.current) return;
      setState("error");
      onErrorRef.current?.();
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
      requestVersion.current += 1;
    };
  }, [reload, options.reloadKey]);

  return { data, state, reload, setData };
}
