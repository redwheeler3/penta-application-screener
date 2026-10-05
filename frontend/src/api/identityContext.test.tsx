import { render, renderHook } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";

import * as applications from "./applications";
import * as subscriptions from "./vacancySubscriptions";
import { RequestIdentityProvider, useCommitteeApi } from "./identity";
import { identityClient } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("refuses a protected API outside its captured workspace context", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  expect(() => renderHook(() => useCommitteeApi(applications))).toThrow("Protected API requires RequestIdentityProvider");
  expect(fetch).not.toHaveBeenCalled();
});

it("keeps a captured callback bound to its original workspace after a provider change", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json({})));
  vi.stubGlobal("fetch", fetch);
  let latest!: ReturnType<typeof applications.createApi>;
  function Capture() {
    const api = useCommitteeApi(applications);
    useEffect(() => { latest = api; }, [api]);
    return null;
  }
  const { rerender } = render(<RequestIdentityProvider identity={{ kind: "committee", id: 1 }}><Capture /></RequestIdentityProvider>);
  const earlier = latest;
  rerender(<RequestIdentityProvider identity={{ kind: "committee", id: 2 }}><Capture /></RequestIdentityProvider>);
  await Promise.all([earlier.savePrivateNote(7, 1, "Synthetic earlier note"), latest.setStar(7, 1, true)]);
  expect(new Headers(fetch.mock.calls[0][1].headers).get("X-Penta-Identity")).toBe("committee:1");
  expect(new Headers(fetch.mock.calls[1][1].headers).get("X-Penta-Identity")).toBe("committee:2");
});

it("binds vacancy support operations to the committee actor", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ subscription: null }));
  vi.stubGlobal("fetch", fetch);
  await subscriptions.createApi(identityClient({ kind: "committee", id: 7 })).deleteVacancySubscription("synthetic@example.com");
  expect(new Headers(fetch.mock.calls[0][1].headers).get("X-Penta-Identity")).toBe("committee:7");
});
