import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { WorkflowBar } from "./WorkflowBar";

const baseProps: ComponentProps<typeof WorkflowBar> = {
  workflow: {
    applicationsAvailable: true,
    screened: true,
    patternsDiscovered: true,
    candidatesScored: true,
    rankingCurrent: false,
  },
  coverage: {
    screened: { cached: 0, inScope: 98 },
    candidatesScored: { cached: 88, inScope: 88 },
  },
  loadState: "ready",
  onRetryLoad: vi.fn(),
  screeningRunning: false,
  screeningEstimate: null,
  screeningEstimateLoading: false,
  screeningProgress: null,
  onRequestScreening: vi.fn(),
  onRunScreening: vi.fn(),
  onCancelScreening: vi.fn(),
  rankRunning: false,
  rankEstimate: null,
  rankEstimateLoading: false,
  scoreCurrentEstimate: null,
  hasCurrentCriteria: true,
  rankProgress: null,
  criteriaThinking: "",
  pendingProposals: [],
  onRequestRank: vi.fn(),
  onRunRank: vi.fn(),
  onCancelRank: vi.fn(),
  openings: [{
    id: 1,
    unitSizeBedrooms: 2,
    housingChargeCents: 150_000,
    applicationOpenDate: "2026-07-01",
    applicationCloseDate: "2026-08-01",
    moveInDate: "2026-09-01",
    phase: "archived",
  }],
  selectedOpeningId: 1,
  onOpeningChange: vi.fn(),
  aiActionsDisabled: true,
};

describe("WorkflowBar archived state", () => {
  it("shows completed archived steps as neutral finalized history", () => {
    render(<WorkflowBar {...baseProps} />);

    for (const name of ["Screen", "Rank"]) {
      const button = screen.getByRole("button", { name: new RegExp(`^${name}`) });
      expect(button).toBeDisabled();
      expect(button).toHaveClass("is-locked");
      expect(button).not.toHaveClass("is-stale", "is-done");
      expect(button).toHaveTextContent("Finalized");
      expect(button).toHaveAttribute(
        "title",
        "This archived opening has a final outcome. Existing results are read-only.",
      );
    }
  });

  it("keeps amber stale steps actionable before a final decision", () => {
    render(
      <WorkflowBar
        {...baseProps}
        openings={[{ ...baseProps.openings[0], phase: "closed" }]}
        aiActionsDisabled={false}
      />,
    );

    for (const name of ["Screen", "Rank"]) {
      const button = screen.getByRole("button", { name: new RegExp(`^${name}`) });
      expect(button).toBeEnabled();
      expect(button).toHaveClass("is-stale");
      expect(button).not.toHaveClass("is-locked");
      expect(button).not.toHaveTextContent("Finalized");
    }
  });
});
