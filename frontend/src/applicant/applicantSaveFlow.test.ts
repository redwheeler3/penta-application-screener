import { afterEach, expect, it, vi } from "vitest";
import { deferred } from "../testSupport";
import { createApplicantSaveFlow } from "./applicantSaveFlow";
import { INITIAL_APPLICANT_PERSISTENCE_STATE, type ApplicantPersistenceState } from "./applicantPersistenceState";
import { emptyApplicantDraft } from "./applicationDraft";
import { loadApplicationDraft, saveApplicationDraft, setRememberDevice } from "./draftStorage";
import type * as applicantApi from "./api";

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

it.each(["during submission", "before submission"])("preserves another tab's remembered draft written %s", async (timing) => {
  localStorage.clear();
  vi.stubGlobal("navigator", { locks: { request: async (_name: string, operation: () => unknown) => operation() } });
  const consent = (await setRememberDevice(true))!;
  const submitted = emptyApplicantDraft();
  submitted.applicant.email = "synthetic@example.test";
  const newer = { ...submitted, pets: "Newer synthetic answer" };
  await saveApplicationDraft(7, timing === "before submission" ? newer : submitted, [], 1, consent);
  const stateRef = { current: { ...INITIAL_APPLICANT_PERSISTENCE_STATE, applicationId: 7,
    workingRevision: 1, openingIds: [], openings: [], canEdit: true } as ApplicantPersistenceState };
  const acknowledgement = deferred<Response>();
  const api = { submitApplication: vi.fn().mockReturnValue(acknowledgement.promise) } as unknown as ReturnType<typeof applicantApi.createApi>;
  const flow = createApplicantSaveFlow({ api, stateRef, draftRef: { current: submitted }, invalidateReads: vi.fn(),
    captureSession: () => () => true, fail: vi.fn(), updatePersistence: (patch) => {
      stateRef.current = { ...stateRef.current, ...(typeof patch === "function" ? patch(stateRef.current) : patch) };
    } });
  const saving = flow.start("submit");
  if (timing === "during submission") await saveApplicationDraft(7, newer, [], 2, consent);
  acknowledgement.resolve(Response.json({ workingRevision: 2, openings: [], canEdit: true }));
  await saving;
  expect(stateRef.current.phase).toBe("submitted");
  expect(loadApplicationDraft(7)?.draft.pets).toBe(newer.pets);
});
