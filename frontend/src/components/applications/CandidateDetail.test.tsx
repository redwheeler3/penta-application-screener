import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApplicationDetail, CommitteeOpening } from "../../types";
import { CandidateDetail } from "./CandidateDetail";

const application: ApplicationDetail = {
  id: 1,
  primaryEmail: "alex@example.com",
  applicantName: "Alex Chen",
  coApplicantName: null,
  status: "eligible",
  statusSource: "untouched",
  stale: false,
  hardFilterReasons: [],
  childCount: 0,
  householdIncome: 80_000,
  flagCount: 0,
  flagCategories: [],
  starredByMe: false,
  shortlisted: false,
  selected: false,
  openingIds: [1],
  autoStatus: "eligible",
  autoStatusSource: "untouched",
  firstSubmittedAt: "2026-09-01T12:00:00Z",
  lastSubmittedAt: "2026-09-01T12:00:00Z",
  submissionVersionCount: 1,
  normalized: { applicant_age: 36, household_income: 80_000 },
  essays: [{ label: "Why a co-op", question: "why", answer: "Community." }],
  flags: [],
  rawRow: {
    applicant: {
      first_name: "Alex",
      last_name: "Chen",
      birth_date: "1990-01-02",
      email: "alex@example.com",
    },
    current_address: {},
  },
  dimensionScores: [{
    dimensionKey: "community",
    name: "Community contribution",
    score: 0.5,
    weight: 1,
    impact: 0.5,
    confidence: "high",
    rationale: "Clear examples.",
    evidence: "Organized neighbourhood events.",
  }],
  privateNote: "",
  committeeNotes: [],
};

const openings: CommitteeOpening[] = [{
  id: 1,
  unitSizeBedrooms: 2,
  housingChargeCents: 150_000,
  applicationOpenDate: "2026-08-01",
  applicationCloseDate: "2026-09-01",
  moveInDate: "2026-09-30",
  phase: "closed",
}];

describe("CandidateDetail", () => {
  it("presents applicant data before essays and styles AI scoring as a peer heading", () => {
    render(
      <CandidateDetail
        app={application}
        openings={openings}
        onBack={vi.fn()}
        onOverrideStatus={vi.fn()}
        onClearOverride={vi.fn()}
        onSavePrivateNote={vi.fn().mockResolvedValue(true)}
        onAddCommitteeNote={vi.fn().mockResolvedValue(true)}
        onUpdateCommitteeNote={vi.fn().mockResolvedValue(true)}
        onDeleteCommitteeNote={vi.fn().mockResolvedValue(true)}
        onToggleStar={vi.fn()}
        onToggleShortlist={vi.fn()}
      />,
    );

    const applicantData = screen.getByRole("heading", { name: "Applicant data" });
    const essayResponses = screen.getByRole("heading", { name: "Essay responses" });
    const aiScoring = screen.getByRole("heading", { name: "AI scoring" });
    expect(applicantData.compareDocumentPosition(essayResponses))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(essayResponses.compareDocumentPosition(aiScoring))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(applicantData).toHaveClass("detail-content-heading");
    expect(essayResponses).toHaveClass("detail-content-heading");
    expect(aiScoring).toHaveClass("detail-content-heading");
    expect(screen.getByRole("button", { name: /View AI scoring/ })).toBeInTheDocument();
  });
});
