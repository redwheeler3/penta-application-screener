import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApplicationEntry } from "../../applicant/ApplicantAccessScreens";
import { CommitteeSignIn } from "./CommitteeSignIn";

const notice = "Email delivery is temporarily delayed and may take up to 48 hours. Google sign-in is immediate.";

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
    const applicantNotice = applicant.getByText(notice);
    const applicantDivider = applicant.getByText("or use email");
    const applicantForm = applicant.getByRole("textbox", { name: "Email address" }).closest("form") as HTMLElement;
    expect(applicantNotice).toBeInTheDocument();
    expect(applicantDivider.compareDocumentPosition(applicantNotice))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(applicantNotice.compareDocumentPosition(applicantForm))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
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
    const committeeNotice = screen.getByText(notice);
    const committeeDivider = screen.getByText("or use email");
    const committeeForm = screen.getByRole("textbox", { name: "Email address" }).closest("form") as HTMLElement;
    expect(committeeNotice).toBeInTheDocument();
    expect(screen.getByText(/Google sign-in is immediate/)).toBeInTheDocument();
    expect(committeeDivider.compareDocumentPosition(committeeNotice))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(committeeNotice.compareDocumentPosition(committeeForm))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
