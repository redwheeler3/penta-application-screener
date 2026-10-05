import { act, renderHook, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { emptyApplicantDraft, workingAnswers } from "./applicationDraft";
import { useApplicantPersistence } from "./useApplicantPersistence";

afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); });

function requestFixture(fragment = "") {
  let actor = 7;
  const requests: { path: string; identity: string | null }[] = [];
  const draft = emptyApplicantDraft(); draft.applicant.email = "synthetic@example.com";
  window.history.replaceState(null, "", `/${fragment}`);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname;
    const identity = new Headers(init.headers).get("X-Penta-Identity");
    requests.push({ path, identity });
    if (path === "/applicant/access-links/inspect") return Response.json({
      state: "valid", purpose: "applicant_access", currentEmail: "synthetic@example.com",
      linkEmail: "other@example.com", applicationEmail: "other@example.com", switchRequired: true,
      applicationId: actor, pendingIntent: null, pendingCopy: null, googleDisconnected: false,
    });
    const bootstrap = path === "/applicant/application" && identity === null;
    if (!bootstrap && identity !== `applicant:${actor}`) {
      return Response.json({ code: "session_changed", detail: "Your session changed." }, { status: 409 });
    }
    if (path === "/applicant/access-links/open") {
      actor = 8;
      return Response.json({ state: "valid", purpose: "applicant_access", applicationId: actor,
        currentEmail: "other@example.com", linkEmail: "other@example.com", applicationEmail: "other@example.com",
        switchRequired: false, pendingIntent: null, pendingCopy: null, googleDisconnected: false });
    }
    if (path === "/applicant/application") return Response.json({
      applicationId: actor, primaryEmail: actor === 7 ? draft.applicant.email : "other@example.com",
      googleSignInLinked: false, pendingEmailChange: null, answers: workingAnswers(draft),
      workingSavedAt: null, workingRevision: 1, submitted: true, canEdit: true, openings: [],
    });
    if (path === "/applicant/application/pending-copy") return Response.json({ pendingCopy: null });
    throw new Error(`Unexpected request: ${path}`);
  }));
  const view = renderHook(() => {
    const [answers, setAnswers] = useState(draft);
    return useApplicantPersistence(answers, setAnswers, () => {});
  });
  return { ...view, requests, setActor: (id: number) => { actor = id; } };
}

it("binds startup follow-ups to the accepted application response", async () => {
  const { result, requests } = requestFixture();
  await waitFor(() => expect(requests.some((item) => item.path.endsWith("pending-copy"))).toBe(true));
  expect(result.current.phase).toBe("idle");
  expect(requests.find((item) => item.path.endsWith("pending-copy"))?.identity).toBe("applicant:7");
});

it("binds a switched link target's follow-ups before its React render", async () => {
  const { result, requests } = requestFixture("#applicant-link=synthetic-token");
  await waitFor(() => expect(result.current.phase).toBe("link_conflict"));
  await act(() => result.current.openLinkedApplication(false));
  expect(result.current.applicationId).toBe(8);
  expect(result.current.phase).toBe("idle");
  expect(requests.find((item) => item.path.endsWith("pending-copy"))?.identity).toBe("applicant:8");
});

it("handles repeated mismatch and recovery without losing application ownership", async () => {
  const { result, setActor } = requestFixture();
  await waitFor(() => expect(result.current.applicationId).toBe(7));
  for (let cycle = 0; cycle < 2; cycle++) {
    setActor(8);
    await act(() => result.current.beginEmailChange("new@example.com"));
    expect(result.current.phase).toBe("session_expired");
    expect(result.current.applicationId).toBe(7);
    setActor(7);
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(result.current.phase).toBe("idle");
  }
});
