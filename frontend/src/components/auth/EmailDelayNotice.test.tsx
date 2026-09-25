import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApplicationEntry } from "../../applicant/ApplicantAccessScreens";
import { CommitteeSignIn } from "./CommitteeSignIn";

const notice = "Email delivery is taking longer than usual.";

describe("email delay guidance", () => {
  it("uses the same core notice for applicants and committee members", () => {
    const applicant = render(
      <ApplicationEntry
        allowGuest
        busy={false}
        emailDelayed
        googleError={null}
        googleSignInUrl="#"
        rememberDevice={false}
        onRememberDeviceChange={vi.fn()}
        onContinueGuest={vi.fn()}
        onEmailLink={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(applicant.getByText(notice)).toBeInTheDocument();
    applicant.unmount();

    render(
      <CommitteeSignIn
        emailDelayed
        emailSignInEnabled
        isLoadingUser={false}
        userLoadRecovery={null}
        signInState="idle"
        linkConflict={null}
        linkedEmail={null}
        onRequestLink={vi.fn()}
        onKeepCurrent={vi.fn()}
        onOpenLinked={vi.fn()}
        onEmailNew={vi.fn()}
        onReset={vi.fn()}
      />,
    );
    expect(screen.getByText(notice)).toBeInTheDocument();
    expect(screen.getByText(/Google sign-in is immediate/)).toBeInTheDocument();
  });
});
