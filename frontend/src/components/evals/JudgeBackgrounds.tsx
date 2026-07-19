import { type ReactNode, useEffect, useState } from "react";

import { fetchJudgeBackgrounds, saveJudgeBackground } from "../../api";

// One pass's editable "what this pass does" brief + how many golden cases it contributes.
type Background = { passName: string; background: string; caseCount: number };

// The Judge tab's per-pass background editors. The blind judge reproduces each pass's output
// from THIS brief (+ the case's given), so it's the one knob that tunes the audit — hence
// editable here, saved to that pass's golden file (the operator commits deliberately). Read-only
// case viewing lives in the RunnableEval below this; adding/editing cases happens in each pass's
// own tab (the judge owns no case files).
export function JudgeBackgrounds(): ReactNode {
  const [items, setItems] = useState<Background[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchJudgeBackgrounds()
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { backgrounds?: Background[] } | null) => {
        if (live && d?.backgrounds) setItems(d.backgrounds);
      });
    return () => {
      live = false;
    };
  }, []);

  async function save(passName: string) {
    const text = drafts[passName];
    if (text === undefined) return;
    setSaving(passName);
    setError(null);
    setSavedNote(null);
    const resp = await saveJudgeBackground(passName, text);
    setSaving(null);
    if (resp.ok) {
      const saved: Background = await resp.json();
      setItems((prev) => (prev ?? []).map((b) => (b.passName === passName ? saved : b)));
      setDrafts((prev) => {
        const { [passName]: _drop, ...rest } = prev;
        return rest;
      });
      setSavedNote(`${passName} background saved — commit the golden file to keep it.`);
    } else {
      const problem = await resp.json().catch(() => null);
      setError(problem?.detail ?? `Save failed (${resp.status})`);
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
      {error ? <p className="eval-error">{error}</p> : null}
      {savedNote ? <p className="eval-backgrounds-saved">{savedNote}</p> : null}
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
              className="eval-background-text"
              rows={4}
              value={draft ?? b.background}
              onChange={(e) => setDrafts((prev) => ({ ...prev, [b.passName]: e.target.value }))}
            />
            <div className="eval-background-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={!dirty || saving === b.passName}
                onClick={() => void save(b.passName)}
              >
                {saving === b.passName ? "Saving…" : "Save brief"}
              </button>
            </div>
          </div>
        );
      })}
    </details>
  );
}
