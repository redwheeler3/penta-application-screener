import { act, render } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/emailDelivery";
import { deferred } from "../../testSupport";
import { CommitteeSignIn } from "./CommitteeSignIn";
import { EmailDeliveryAdvisory } from "./EmailDelayNotice";

vi.mock("../../api/emailDelivery", () => ({
  fetchCachedEmailDeliveryStatus: vi.fn(), refreshEmailDeliveryStatus: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());

it("loads advice only while the email form consumes its slot", async () => {
  const cached = deferred<{ available: boolean; delayed: boolean }>();
  vi.mocked(api.fetchCachedEmailDeliveryStatus).mockReturnValue(cached.promise);
  const props: ComponentProps<typeof CommitteeSignIn> = {
    emailSignInEnabled: true, isLoadingUser: true, userLoadRecovery: null,
    signInState: "idle", linkConflict: null, linkedEmail: null,
    onRequestLink: vi.fn(), onKeepCurrent: vi.fn(), onOpenLinked: vi.fn(),
    onEmailNew: vi.fn(), onRetryLink: vi.fn(), onReset: vi.fn(),
    emailDeliveryNotice: <EmailDeliveryAdvisory />,
  };
  const { rerender } = render(<CommitteeSignIn {...props} />);
  expect(api.fetchCachedEmailDeliveryStatus).not.toHaveBeenCalled();
  rerender(<CommitteeSignIn {...props} isLoadingUser={false} signInState="emailSent" />);
  expect(api.fetchCachedEmailDeliveryStatus).not.toHaveBeenCalled();
  rerender(<CommitteeSignIn {...props} isLoadingUser={false} />);
  expect(api.fetchCachedEmailDeliveryStatus).toHaveBeenCalledOnce();
  const signal = vi.mocked(api.fetchCachedEmailDeliveryStatus).mock.calls[0][0];
  rerender(<CommitteeSignIn {...props} isLoadingUser={false} signInState="connectionFailed" />);
  expect(signal?.aborted).toBe(true);
  await act(async () => cached.resolve({ available: true, delayed: true }));
  expect(api.refreshEmailDeliveryStatus).not.toHaveBeenCalled();
});
