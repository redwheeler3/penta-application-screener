import { expect, it } from "vitest";
import { canonicalAnswers, draftFromWorking, emptyApplicantDraft, workingAnswers } from "./applicationDraft";

it("private saves preserve known references while prerequisite answers remain incomplete", () => {
  const reference = { name: "Synthetic reference", email: "reference@example.com", phone: "604-555-0101" };
  const wire = workingAnswers(emptyApplicantDraft());
  wire.applicantEmployment = { ...wire.applicantEmployment, status: null, manager: reference };
  wire.coApplicant = { firstName: "Synthetic", lastName: "Coapplicant", birthDate: "", email: "", phone: "", relationship: "" };
  wire.coApplicantEmployment = { ...wire.applicantEmployment };
  wire.currentLandlord = reference;
  wire.previousLandlord = reference;
  const draft = draftFromWorking(wire);
  const saved = workingAnswers(draft);
  expect(saved.applicantEmployment.manager).toEqual(reference);
  expect(saved.coApplicantEmployment?.manager).toEqual(reference);
  expect(saved.currentLandlord).toEqual(reference);
  expect(saved.previousLandlord).toEqual(reference);
  const restored = draftFromWorking(saved);
  expect(restored.previousLandlord).toEqual(reference);
  draft.applicantEmployment.status = "unemployed";
  draft.ownsCurrentHome = "yes";
  draft.applicantIncome = "0";
  draft.coApplicantIncome = "0";
  expect(canonicalAnswers(draft).applicantEmployment.manager).toBeNull();
  expect(canonicalAnswers(draft).currentLandlord).toBeNull();
  expect(canonicalAnswers(draft).previousLandlord).toBeNull();
});

it("preserves unfinished income for editing and never serializes an ambiguous amount as zero", () => {
  const draft = emptyApplicantDraft();
  draft.hasCoApplicant = false;
  draft.applicantIncome = "60,000–65,000";
  expect(workingAnswers(draft).applicantIncome).toBeNull();
  expect(() => canonicalAnswers(draft)).toThrow("income");
  for (const [value, expected] of [["0", 0], ["65,000.00", 65000]] as const) {
    draft.applicantIncome = value;
    expect(workingAnswers(draft).applicantIncome).toBe(expected);
    expect(canonicalAnswers(draft).applicantIncome).toBe(expected);
  }
});
