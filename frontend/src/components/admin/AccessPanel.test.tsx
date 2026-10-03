import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/access";
import { deferred } from "../../testSupport";
import { AccessPanel } from "./AccessPanel";

vi.mock("../../api/access", () => ({
  fetchAllowlist: vi.fn(), fetchDeniedSignInAttempts: vi.fn(),
  upsertAllowlistEntry: vi.fn(), removeAllowlistEntry: vi.fn(),
}));

const entries = [{ email: "existing@example.com", role: "member" as const, isSeedAdmin: false,
  displayName: "Synthetic member", firstActiveAt: null, lastActiveAt: null }];
function setup() {
  const onError = vi.fn();
  render(<AccessPanel currentUser={{ id: 1, email: "admin@example.com", displayName: "Synthetic admin", role: "admin", avatarUrl: null }} onError={onError} />);
  return { onError };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchAllowlist).mockResolvedValue(entries);
  vi.mocked(api.fetchDeniedSignInAttempts).mockResolvedValue([]);
});

it.each(["add", "remove", "role"])("releases access controls and retains drafts after a failed %s", async (action) => {
  vi.mocked(api.upsertAllowlistEntry).mockRejectedValue(new Error("Synthetic network failure"));
  vi.mocked(api.removeAllowlistEntry).mockRejectedValue(new Error("Synthetic network failure"));
  const { onError } = setup();
  const remove = await screen.findByRole("button", { name: "Remove existing@example.com" });
  const input = screen.getByPlaceholderText("name@example.com");
  fireEvent.change(input, { target: { value: "draft@example.com" } });
  await act(async () => {
    if (action === "add") fireEvent.click(screen.getByRole("button", { name: "Add and invite" }));
    else if (action === "remove") fireEvent.click(remove);
    else fireEvent.change(screen.getByRole("combobox", { name: "Role for existing@example.com" }), { target: { value: "admin" } });
  });
  expect(onError).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Add and invite" })).toBeEnabled();
  expect(remove).toBeEnabled();
  expect(input).toHaveValue("draft@example.com");
});

it("keeps a newer invitation draft when an earlier access request succeeds", async () => {
  const save = deferred<Response>();
  vi.mocked(api.upsertAllowlistEntry).mockReturnValue(save.promise);
  setup();
  await screen.findByRole("button", { name: "Remove existing@example.com" });
  const input = screen.getByPlaceholderText("name@example.com");
  fireEvent.change(input, { target: { value: "a@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Add and invite" }));
  fireEvent.change(input, { target: { value: "b@example.com" } });
  fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "admin" } });
  await act(async () => { save.resolve(Response.json({ entries, invitationEmailStatus: "sent" })); });
  expect(input).toHaveValue("b@example.com");
  expect(screen.getAllByRole("combobox")[0]).toHaveValue("admin");
  expect(screen.getByRole("button", { name: "Add and invite" })).toBeEnabled();
});

it("releases access controls when the acknowledgement body is invalid", async () => {
  vi.mocked(api.upsertAllowlistEntry).mockResolvedValue(new Response("invalid JSON"));
  const { onError } = setup();
  await screen.findByRole("button", { name: "Remove existing@example.com" });
  fireEvent.change(screen.getByPlaceholderText("name@example.com"), { target: { value: "draft@example.com" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add and invite" })); });
  expect(onError).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Add and invite" })).toBeEnabled();
});
