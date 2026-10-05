import { useCommitteeApi } from "../api/identity";
import { useState } from "react";

import * as settingsApi from "../api/settings";
import { readProblem } from "../api/problems";
import type { EligibilityRules } from "../types";
import { useFetchResource } from "./useFetchResource";
import { useRequestScope } from "./useRequestScope";

type RuleDraft = {
  scope: string;
  draft: EligibilityRules;
  isDefault: boolean;
  committeeDefault: EligibilityRules;
};

/** The two eligibility editors share scope, draft acknowledgement, and write ordering. */
export function useEligibilityRules(options: {
  openingId: number;
  kind: "member" | "committee-default";
  onError: (message: string) => void;
  onUpdated: () => void;
}) {
  const api = useCommitteeApi(settingsApi);

  const { openingId, kind } = options;
  const scope = `${kind}:${openingId}`;
  const requests = useRequestScope(scope);
  const [action, setAction] = useState<{ scope: string; kind: "save" | "reset" } | null>(null);
  const [confirmation, setConfirmation] = useState<{ scope: string; rules: EligibilityRules } | null>(null);
  const resource = useFetchResource<RuleDraft>(async () => {
    const [committeeDefault, memberRules] = await Promise.all([
      api.fetchCommitteeDefaultRules(openingId),
      kind === "member" ? api.fetchEligibilityRules(openingId) : Promise.resolve(null),
    ]);
    const mine = memberRules ?? { rules: committeeDefault, isDefault: true };
    return { scope, draft: mine.rules, isDefault: mine.isDefault, committeeDefault };
  }, {
    reloadKey: scope,
    onError: () => options.onError(kind === "member"
      ? "Could not load your eligibility rules."
      : "Could not load the committee default rules."),
  });
  const data = resource.data?.scope === scope ? resource.data : null;
  const busy = action?.scope === scope;

  function setDraft(draft: EligibilityRules) {
    resource.setData((current) => current?.scope === scope ? { ...current, draft } : current);
    setConfirmation(null);
  }

  async function write(operation: "save" | "reset") {
    if (!data || busy || !requests.isFor(scope)) return;
    const submitted = data.draft;
    const isCurrent = requests.capture();
    // Invalidate any read begun before this write without replacing the editable draft.
    resource.invalidateReads();
    setAction({ scope, kind: operation });
    setConfirmation(null);
    const failure = operation === "reset" ? "Could not reset to the committee default."
      : kind === "member" ? "Your eligibility rules could not be saved."
        : "The committee default rules could not be saved.";
    try {
      const response = operation === "reset"
        ? await api.resetEligibilityRules(openingId)
        : kind === "member"
          ? await api.saveEligibilityRules(openingId, submitted)
          : await api.saveCommitteeDefaultRules(openingId, submitted);
      if (!isCurrent()) return;
      if (!response.ok) {
        const problem = await readProblem(response);
        if (isCurrent()) options.onError(problem ?? failure);
        return;
      }
      const accepted = kind === "member"
        ? await response.json() as { rules: EligibilityRules; isDefault: boolean }
        : { rules: await response.json() as EligibilityRules, isDefault: true };
      if (!isCurrent()) return;
      resource.setData((current) => current?.scope === scope ? {
        ...current,
        draft: current.draft === submitted ? accepted.rules : current.draft,
        isDefault: accepted.isDefault,
        committeeDefault: operation === "reset" || kind === "committee-default"
          ? accepted.rules : current.committeeDefault,
      } : current);
      options.onUpdated();
      if (operation === "save") {
        const saved = { scope, rules: accepted.rules };
        setConfirmation(saved);
        window.setTimeout(() => {
          if (isCurrent()) setConfirmation((current) => current === saved ? null : current);
        }, 2000);
      }
    } catch {
      if (isCurrent()) options.onError(failure);
    } finally {
      if (isCurrent()) setAction(null);
    }
  }

  return {
    draft: data?.draft ?? null,
    isDefault: data?.isDefault ?? true,
    committeeDefault: data?.committeeDefault ?? null,
    state: resource.state,
    reload: resource.reload,
    setDraft,
    save: () => write("save"),
    reset: () => write("reset"),
    busy,
    saving: busy && action.kind === "save",
    resetting: busy && action.kind === "reset",
    savedTick: confirmation?.scope === scope && data?.draft === confirmation?.rules,
  };
}
