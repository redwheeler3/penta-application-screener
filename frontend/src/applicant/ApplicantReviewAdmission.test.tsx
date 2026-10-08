import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { deferred } from "../testSupport";
import { ApplicantApp } from "./ApplicantApp";
import { ApplicationReview } from "./ApplicantReview";
import { canonicalAnswers, emptyApplicantDraft, workingAnswers } from "./applicationDraft";
import { loadApplicationDraft, saveApplicationDraft, setRememberDevice } from "./draftStorage";
import type { PendingCopy } from "./applicantPersistence";

vi.mock("../hooks/useEmailDeliveryStatus", () => ({ useEmailDeliveryStatus: () => false }));
beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { callback(0); return 0; });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function completeDraft() {
  const draft = emptyApplicantDraft();
  draft.applicant = { firstName: "Synthetic", lastName: "Applicant", email: "synthetic@example.com", phone: "604-555-0100", birthDate: "1990-01-01" };
  draft.hasCoApplicant = false;
  draft.currentAddress = { street: "1 Synthetic Street", street2: "", city: "Vancouver", provinceOrState: "BC", postalOrZipCode: "V6R 1A1", country: "Canada" };
  draft.currentAddressMoveInDate = "2020-01-01";
  draft.ownsCurrentHome = "yes"; draft.ownsOtherRealEstate = "no";
  draft.applicantEmployment.status = "unemployed"; draft.applicantIncome = "80000";
  draft.essays = { householdIntroduction: "Synthetic answer", skillsToContribute: "Synthetic answer", previousCoopExperience: "Synthetic answer", whyCoop: "Synthetic answer", additionalInformation: "" };
  return draft;
}

const opening = { id: 1, unitSizeBedrooms: 2, housingChargeCents: 100000,
  applicationOpenDate: "2026-01-01", applicationCloseDate: "2027-01-01", moveInDate: "2027-02-01",
  phase: "open", selected: true, participating: true, hasParticipated: true, canSelect: true, canWithdraw: true };

function fixture(mode: "authenticated" | "guest" | "link", draft = completeDraft(), pendingCopy: PendingCopy | null = null) {
  const saving = deferred<Response>();
  const checking = deferred<Response>();
  let body = { applicationId: 7, primaryEmail: draft.applicant.email, googleSignInLinked: false,
    pendingEmailChange: null, answers: workingAnswers(draft), workingSavedAt: null,
    workingRevision: 1, submitted: true, canEdit: true, openings: [opening], pendingCopy };
  const savedRequests: unknown[] = [];
  const checkedRequests: unknown[] = [];
  if (mode === "link") window.history.replaceState(null, "", "/#applicant-link=synthetic-token");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname;
    if (path === "/applicant/access-links/inspect") return Response.json({ state: "valid", purpose: "applicant_access",
      linkEmail: body.primaryEmail, applicationId: null, switchRequired: false });
    if (path === "/applicant/access-links/open") return Response.json({ state: "valid", purpose: "applicant_access",
      applicationId: 7, pendingIntent: "submit", pendingCopy });
    if (path === "/applicant/application" && init.method === "PUT") {
      savedRequests.push(JSON.parse(String(init.body))); return saving.promise;
    }
    if (path === "/applicant/application") return mode === "guest"
      ? new Response(null, { status: 401 }) : Response.json(body);
    if (path === "/applicant/openings") return Response.json({ canStartApplication: true, canSignIn: true,
      openings: [{ ...opening, selected: false, participating: false, hasParticipated: false }] });
    if (path === "/applicant/submissions/check") {
      checkedRequests.push(JSON.parse(String(init.body))); return checking.promise;
    }
    if (path === "/applicant/application/pending-copy" && init.method === "POST") {
      const choice = JSON.parse(String(init.body)).choice;
      body = { ...body, answers: choice === "guest" ? pendingCopy!.guestAnswers : pendingCopy!.savedAnswers,
        workingRevision: 2, pendingCopy: null };
      return Response.json(body);
    }
    if (path === "/applicant/application/pending-copy") return Response.json({ pendingCopy: body.pendingCopy });
    throw new Error(`Unexpected synthetic request ${path}`);
  }));
  render(<ApplicantApp />);
  return { saving, checking, savedRequests, checkedRequests, acknowledgement: () => Response.json({ ...body, workingRevision: 2 }) };
}

const essay = () => screen.getByRole("textbox", { name: /Why does your household want to live in a co-op/ });

it.each(["focus", "visibilitychange"])("a passive %s refresh preserves another tab's newer remembered answers", async (trigger) => {
  vi.useFakeTimers();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  let tail = Promise.resolve();
  vi.stubGlobal("navigator", { locks: { request: (_name: string, operation: () => unknown) => {
    const result = tail.then(operation);
    tail = result.then(() => {}, () => {});
    return result;
  } } });
  const consent = (await setRememberDevice(true))!;
  const older = completeDraft();
  older.pets = "Older tab B answers";
  await act(async () => { fixture("authenticated", older); });
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(loadApplicationDraft(7)?.draft.pets).toBe(older.pets);
  await act(async () => { await saveApplicationDraft(7, { ...older, pets: "Newer tab A answers" }, [1], 1, consent); });
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: "penta-application-drafts-v5", storageArea: localStorage })));
  await act(async () => (trigger === "focus" ? window : document).dispatchEvent(new Event(trigger)));
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(loadApplicationDraft(7)?.draft.pets).toBe("Newer tab A answers");
  // An explicit edit still persists this tab's answers, with no cross-tab merge.
  fireEvent.change(screen.getByRole("textbox", { name: /What pets/ }), { target: { value: "Edited in B" } });
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(loadApplicationDraft(7)?.draft.pets).toBe("Edited in B");
  fireEvent.click(screen.getByRole("checkbox", { name: /Move-in/ }));
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(loadApplicationDraft(7)?.openingIds).toEqual([]);
});

it("omits an inapplicable landlord after the applicant changes from renter to owner", () => {
  const draft = completeDraft();
  draft.ownsCurrentHome = "no";
  draft.currentLandlord = { name: "Synthetic rental contact", phone: "604-555-0199", email: "landlord@example.com" };
  const props = { draft, openings: [], selectedOpeningIds: [], declarationAccepted: false,
    persistencePhase: "idle", persistenceMessage: "", onRetry: vi.fn(), onReload: vi.fn(),
    onDeclarationChange: vi.fn(), onSubmit: vi.fn(), onEdit: vi.fn() };
  const { rerender } = render(<ApplicationReview {...props} />);
  expect(screen.getByText(draft.currentLandlord.name)).toBeInTheDocument();
  const owner = { ...draft, ownsCurrentHome: "yes" as const };
  rerender(<ApplicationReview {...props} draft={owner} />);
  expect(canonicalAnswers(owner).currentLandlord).toBeNull();
  expect(screen.queryByText("Current landlord")).toBeNull();
  expect(screen.queryByText(draft.currentLandlord.name)).toBeNull();
  expect(screen.getByRole("heading", { name: "Current housing" })).toBeInTheDocument();
});

it.each(["answer", "opening"])("keeps editing when the validated %s changes during a save", async (change) => {
  const { saving, savedRequests, acknowledgement } = fixture("authenticated");
  const review = await screen.findByRole("button", { name: "Save and review" });
  fireEvent.submit(review.closest("form")!);
  await waitFor(() => expect(savedRequests).toHaveLength(1));
  if (change === "answer") fireEvent.change(essay(), { target: { value: "" } });
  else fireEvent.click(screen.getByRole("checkbox", { name: /Move-in/ }));
  await act(async () => saving.resolve(acknowledgement()));
  expect(screen.queryByRole("button", { name: "Submit application" })).toBeNull();
  expect(screen.getByRole("button", { name: "Save and review" })).toBeEnabled();
  if (change === "answer") expect(essay()).toHaveValue("");
});

it("admits the unchanged valid saved snapshot", async () => {
  const { saving, savedRequests, acknowledgement } = fixture("authenticated");
  fireEvent.submit((await screen.findByRole("button", { name: "Save and review" })).closest("form")!);
  await waitFor(() => expect(savedRequests).toHaveLength(1));
  await act(async () => saving.resolve(acknowledgement()));
  expect(await screen.findByRole("button", { name: "Submit application" })).toBeDisabled();
});

function enter(input: HTMLElement, value: string) {
  const event = createEvent.change(input, { target: { value } });
  Object.defineProperty(event, "inputType", { value: "insertFromPaste" });
  fireEvent(input, event);
}

async function fillGuest() {
  fireEvent.click(await screen.findByRole("button", { name: "Continue as a guest" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Include a co-applicant/ }));
  for (const [name, value] of [
    [/^Email/, "synthetic@example.com"], [/^First name/, "Synthetic"], [/^Last name/, "Applicant"],
    [/^Date of birth/, "1990-01-01"], [/^Phone/, "604-555-0100"], [/^Street address/, "1 Synthetic Street"],
    [/^City/, "Vancouver"], [/^Postal or ZIP code/, "V6R 1A1"], [/^When did you move here/, "2020-01-01"],
    [/^Who is in your household/, "Synthetic answer"], [/^What skills could/, "Synthetic answer"],
    [/^What previous co-op/, "Synthetic answer"], [/^Why does your household/, "Synthetic answer"],
  ] as const) enter(screen.getByRole("textbox", { name }), value);
  fireEvent.click(within(screen.getByRole("group", { name: /Do you own the home/ })).getByRole("radio", { name: "Yes" }));
  fireEvent.click(within(screen.getByRole("group", { name: /Do you own another/ })).getByRole("radio", { name: "No" }));
  fireEvent.change(screen.getByRole("combobox", { name: /^Employment status/ }), { target: { value: "unemployed" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: /^Primary applicant/ }), { target: { value: "80000" } });
}

it.each(["answer", "opening"])("keeps a changed guest %s out of review after an older mailbox check", async (change) => {
  const { checking, checkedRequests } = fixture("guest");
  await fillGuest();
  const form = screen.getByRole("button", { name: "Review application" }).closest("form")!;
  expect(form.checkValidity()).toBe(true);
  fireEvent.submit(form);
  await waitFor(() => expect(checkedRequests).toHaveLength(1));
  if (change === "answer") fireEvent.change(essay(), { target: { value: "" } });
  else fireEvent.click(screen.getByRole("checkbox", { name: /Move-in/ }));
  await act(async () => checking.resolve(Response.json({ canSubmit: true, emailSent: false, emailStatus: null })));
  expect(screen.queryByRole("button", { name: "Submit application" })).toBeNull();
  expect(essay()).toHaveValue(change === "answer" ? "" : "Synthetic answer");
});

it.each([true, false])("validates the restored email submit-intent copy (complete=%s)", async (complete) => {
  const draft = completeDraft();
  if (!complete) draft.essays.whyCoop = "";
  fixture("link", draft);
  fireEvent.click(await screen.findByRole("button", { name: "Open application" }));
  if (complete) expect(await screen.findByRole("button", { name: "Submit application" })).toBeDisabled();
  else {
    await screen.findByRole("button", { name: "Save and review" });
    expect(screen.queryByRole("button", { name: "Submit application" })).toBeNull();
    expect(essay()).toHaveValue("");
  }
});

it("waits for pending-copy choice and validates the incomplete chosen copy", async () => {
  const saved = completeDraft();
  saved.essays.whyCoop = "";
  const pendingCopy: PendingCopy = { baseRevision: 1, guestSavedAt: "2026-10-07T12:00:00Z",
    savedAnswers: workingAnswers(saved), savedOpeningIds: [1], guestAnswers: workingAnswers(completeDraft()), guestOpeningIds: [1] };
  fixture("link", saved, pendingCopy);
  fireEvent.click(await screen.findByRole("button", { name: "Open application" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep saved application" }));
  await screen.findByRole("button", { name: "Save and review" });
  expect(screen.queryByRole("button", { name: "Submit application" })).toBeNull();
  expect(essay()).toHaveValue("");
});
