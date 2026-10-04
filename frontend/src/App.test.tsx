import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { App } from "./App";
import type { CurrentUser } from "./types";
import { useSession } from "./hooks/useSession";

vi.mock("./hooks/useSession", () => ({ useSession: vi.fn() }));
vi.mock("./hooks/useEmailDeliveryStatus", () => ({ useEmailDeliveryStatus: () => false }));
vi.mock("./components/auth/CommitteeSignIn", () => ({ CommitteeSignIn: () => <p>Signed out</p> }));
vi.mock("./CommitteeWorkspace", () => ({
  CommitteeWorkspace: ({ user }: { user: CurrentUser }) => {
    const [privateNote, setPrivateNote] = useState("");
    return <label>{user.email}<input aria-label="Private note" value={privateNote} onChange={(event) => setPrivateNote(event.target.value)} /></label>;
  },
}));

const user = (id: number): CurrentUser => ({ id, email: `synthetic${id}@example.com`, displayName: "Synthetic",
  avatarUrl: null, role: "member" });

function session(current: CurrentUser | null) {
  return { user: current, emailSignInEnabled: false, linkConflict: null, linkedEmail: null, isAdmin: false,
    isLoadingUser: false, userLoadRecovery: null, signInState: "idle" as const, requestMagicLink: vi.fn(),
    keepCurrentSession: vi.fn(), openLinkedSession: vi.fn(), emailNewLinkedSession: vi.fn(), retryLinkedSession: vi.fn(),
    resetSignIn: vi.fn(), logout: vi.fn() };
}

beforeEach(() => vi.resetAllMocks());

it.each(["another account", "sign-out and return"])("drops private workspace state after %s", (transition) => {
  vi.mocked(useSession).mockReturnValue(session(user(1)));
  const element = <App authRedirect={{ magicLinkToken: null, googleAccessDenied: false }} />;
  const { rerender } = render(element);
  fireEvent.change(screen.getByRole("textbox", { name: "Private note" }), { target: { value: "Private synthetic draft" } });
  if (transition === "sign-out and return") {
    vi.mocked(useSession).mockReturnValue(session(null));
    rerender(<App authRedirect={{ magicLinkToken: null, googleAccessDenied: false }} />);
    expect(screen.queryByRole("textbox", { name: "Private note" })).toBeNull();
    expect(screen.getByText("Signed out")).toBeInTheDocument();
  }
  vi.mocked(useSession).mockReturnValue(session(user(transition === "another account" ? 2 : 1)));
  rerender(<App authRedirect={{ magicLinkToken: null, googleAccessDenied: false }} />);
  expect(screen.getByRole("textbox", { name: "Private note" })).toHaveValue("");
});
