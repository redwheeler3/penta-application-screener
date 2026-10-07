import type { ReactNode } from "react";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { AnalysisTraceScope } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

// Keep the same trace mounted during observations, including failed refreshes. The
// envelope distinguishes a successfully loaded empty audit from an initial read.
export function AnalysisTraceResource<T>(props: {
  scope: AnalysisTraceScope;
  fetcher: () => Promise<T>;
  children: (data: T) => ReactNode;
}) {
  const identity = `${props.scope.openingId}:${props.scope.analysisId}`;
  const resource = useFetchResource(async () => ({ identity, value: await props.fetcher() }), {
    reloadKey: props.scope,
  });
  const current = resource.data?.identity === identity ? resource.data : null;
  const error = resource.state === "error"
    ? <RetryLoadError message={current ? "Couldn’t refresh this trace. Showing the last loaded results." : "Couldn’t load this trace."}
        onRetry={resource.reload} /> : null;
  if (current === null) return error ?? <p className="panel-hint">Loading…</p>;
  return <>{error}{props.children(current.value)}</>;
}
