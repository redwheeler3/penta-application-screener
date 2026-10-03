import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { CommitteeSignIn } from "./CommitteeSignIn";

it("offers a link check after a connection failure without switching the account", () => {
  const onRetryLink = vi.fn().mockResolvedValue(undefined);
  const onOpenLinked = vi.fn();
  render(<CommitteeSignIn emailSignInEnabled isLoadingUser={false} userLoadRecovery={null}
    signInState="connectionFailed" linkedEmail="linked@example.com"
    linkConflict={{ currentEmail: "current@example.com", linkEmail: "linked@example.com", linkIsValid: true }}
    onRequestLink={vi.fn()} onKeepCurrent={vi.fn()} onOpenLinked={onOpenLinked} onEmailNew={vi.fn()}
    onReset={vi.fn()} onRetryLink={onRetryLink} />);
  expect(screen.getByText("We couldn’t check your sign-in link")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(onRetryLink).toHaveBeenCalledOnce();
  expect(onOpenLinked).not.toHaveBeenCalled();
});
