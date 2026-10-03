import { useEffect, useMemo, useRef } from "react";

export type RequestIsCurrent = () => boolean;

/** Owns async work for one resource. Reads also supersede earlier reads; writes can
 * capture the scope without cancelling other writes in the same resource. */
export function useRequestScope(key: string | number | boolean | null = null) {
  const scope = useRef({ key, generation: 0, request: 0, mounted: false });
  if (scope.current.key !== key) {
    scope.current.key = key;
    scope.current.generation += 1;
    scope.current.request += 1;
  }

  useEffect(() => {
    const current = scope.current;
    current.mounted = true;
    return () => {
      current.mounted = false;
      // Strict Mode can replay effects for the same mounted resource. Its one-shot
      // work may finish after setup resumes; a changed key still invalidates it above.
    };
  }, [key]);

  return useMemo(() => ({
    isFor(expectedKey: string | number | boolean | null): boolean {
      return scope.current.key === expectedKey;
    },
    capture(): RequestIsCurrent {
      const generation = scope.current.generation;
      return () => scope.current.mounted && generation === scope.current.generation;
    },
    begin(): RequestIsCurrent {
      const generation = scope.current.generation;
      const request = ++scope.current.request;
      return () => scope.current.mounted
        && generation === scope.current.generation
        && request === scope.current.request;
    },
    invalidate(): void {
      scope.current.request += 1;
    },
    reset(): void {
      // A session transition invalidates captured writes as well as ordered reads.
      scope.current.generation += 1;
      scope.current.request += 1;
    },
  }), []);
}
