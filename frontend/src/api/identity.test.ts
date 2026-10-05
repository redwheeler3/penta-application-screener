import { afterEach, expect, it, vi } from "vitest";
import { deferred } from "../testSupport";
import { credentialRequest, identityClient, type RequestIdentity } from "./client";
import { createApi } from "./applications";
import { createApi as applicantApi } from "../applicant/api";

afterEach(() => vi.unstubAllGlobals());

it("captures identity in delayed callbacks and lets independent requests run in parallel", async () => {
  const first = deferred<Response>();
  const fetch = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(Response.json({ application: {} }));
  vi.stubGlobal("fetch", fetch);
  const displayed = { kind: "committee" as const, id: 1 };
  const oldApi = createApi(identityClient(displayed));
  displayed.id = 2;
  const newApi = createApi(identityClient(displayed));
  const saving = oldApi.savePrivateNote(7, 1, "Captured draft");
  await newApi.setStar(7, 1, true);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(new Headers(fetch.mock.calls[0][1].headers).get("X-Penta-Identity")).toBe("committee:1");
  expect(new Headers(fetch.mock.calls[1][1].headers).get("X-Penta-Identity")).toBe("committee:2");
  first.resolve(new Response(null));
  await saving;
});

it("binds bodyless withdrawal to the captured application and reports mismatch once", async () => {
  const changed = vi.fn();
  window.addEventListener("penta-session-changed", changed);
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ code: "session_changed" }, { status: 409 })));
  vi.stubGlobal("fetch", fetch);
  try {
    const identity: RequestIdentity = { kind: "applicant", id: 7 };
    const captured = identityClient(identity);
    identity.kind = "committee";
    const api = applicantApi(captured);
    expect((await api.withdrawApplication()).status).toBe(409);
    await api.withdrawApplication();
    expect(new Headers(fetch.mock.calls[0][1].headers).get("X-Penta-Identity")).toBe("applicant:7");
    expect(changed).toHaveBeenCalledOnce();
    expect((changed.mock.calls[0][0] as CustomEvent).detail).toEqual({ kind: "applicant", reason: "mismatch" });
  } finally { window.removeEventListener("penta-session-changed", changed); }
});

it("coordinates credential exchanges through the browser lock", async () => {
  const request = vi.fn(async (_name, exchange) => exchange());
  vi.stubGlobal("navigator", { locks: { request } });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null)));
  await credentialRequest("committee", "/auth/magic-link/consume", { method: "POST" });
  expect(request).toHaveBeenCalledWith("penta-sign-in:committee", expect.any(Function));
});
