import { type ReactNode, useEffect, useRef, useState } from "react";
import { useRequestScope } from "../../hooks/useRequestScope";

import { fetchJudgeBackgrounds, saveJudgeBackground } from "../../api/evals";
import { readProblem } from "../../api/problems";
import type { JudgeBackground } from "../../types";

// The Judge tab's per-pass background editors. The blind judge reproduces each pass's output
// from THIS brief (+ the case's given), so it's the one knob that tunes the audit — hence
// editable here, saved to that pass's golden file (the operator commits deliberately). Read-only
// case viewing lives in the RunnableEval below this; adding/editing cases happens in each pass's
// own tab (the judge owns no case files).
export function JudgeBackgrounds(props: {
  // Save outcomes surface as the app's standard toasts, same as Settings — not inline text.
  onToast: (message: string) => void;
  onError: (message: string) => void;
}): ReactNode {
  const [items, setItems] = useState<JudgeBackground[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const pending = useRef(new Set<string>());
  const requests = useRequestScope();

  useEffect(() => {
    let live = true;
    fetchJudgeBackgrounds()
      .then((data) => {
        if (live) setItems(data.backgrounds);
      });
    return () => {
      live = false;
    };
  }, []);

  async function save(passName: string) {
    const text = drafts[passName];
    if (text === undefined || pending.current.has(passName)) return;
    const isCurrent = requests.capture();
    pending.current.add(passName);
    setSaving((current) => new Set(current).add(passName));
    try {
      const resp = await saveJudgeBackground(passName, text);
      if (!isCurrent()) return;
      if (!resp.ok) {
        const detail = await readProblem(resp);
        if (isCurrent()) props.onError(`Could not save ${passName} brief: ${detail ?? `HTTP ${resp.status}`}`);
        return;
      }
      const saved: JudgeBackground = await resp.json();
      if (!isCurrent()) return;
      setItems((prev) => (prev ?? []).map((b) => (b.passName === passName ? saved : b)));
      setDrafts((prev) => {
        if (prev[passName] !== text) return prev;
        const { [passName]: _drop, ...rest } = prev;
        return rest;
      });
      props.onToast(`${passName} brief saved — commit the golden file to keep it.`);
    } catch {
      if (isCurrent()) props.onError(`Could not save ${passName} brief.`);
    } finally {
      pending.current.delete(passName);
      if (isCurrent()) setSaving((current) => {
        const next = new Set(current);
        next.delete(passName);
        return next;
      });
    }
  }

  if (!items) return null;

  return (
    <details className="eval-backgrounds">
      <summary>
        Judge briefs <span className="eval-backgrounds-hint">— what each pass does (shown to the blind judge)</span>
      </summary>
      <p className="eval-backgrounds-desc">
        The blind judge reproduces each pass's output from this plain-language brief plus the
        case's input (never the human label), then the harness compares to the label. Editing a
        brief changes what the judge is told on the next run; save writes it to that pass's
        golden file (commit to keep).
      </p>
      {items.map((b) => {
        const draft = drafts[b.passName];
        const dirty = draft !== undefined && draft !== b.background;
        return (
          <div key={b.passName} className="eval-background">
            <div className="eval-background-head">
              <strong>{b.passName}</strong>
              <span className="eval-background-count">{b.caseCount} cases</span>
            </div>
            <textarea
              aria-label={`${b.passName} judge brief`}
              className="eval-background-text"
              rows={4}
              value={draft ?? b.background}
              onChange={(e) => setDrafts((prev) => ({ ...prev, [b.passName]: e.target.value }))}
            />
            <div className="eval-background-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={!dirty || saving.has(b.passName)}
                onClick={() => void save(b.passName)}
              >
                {saving.has(b.passName) ? "Saving…" : "Save brief"}
              </button>
            </div>
          </div>
        );
      })}
    </details>
  );
}
