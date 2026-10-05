import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { RankingResponse } from "../../types";
import { RankingView } from "./RankingView";

const props: Omit<ComponentProps<typeof RankingView>, "ranking"> = {
  rankingRun: null, tiers: null, proposedDimensions: [],
  onSaveTiers: vi.fn(), onAcknowledgeNew: vi.fn(), onDismissRequested: vi.fn(),
  onAddProposal: vi.fn(), onRemoveProposal: vi.fn(), onSelectApplication: vi.fn(),
  onToggleStar: vi.fn(), onToggleShortlist: vi.fn(),
};

const unranked: RankingResponse = {
  analysisId: 1, weights: { contribution: 0 }, scoredCount: 1,
  candidates: [{
    applicationId: 1, name: "Synthetic applicant", rank: null, fit: null, band: null,
    contributions: [], starredByMe: false, shortlisted: false,
  }],
  newDimensionKeys: [], revivedDimensionKeys: [], requestedDimensionKeys: [],
  keptKeys: [], proposedDimensions: [],
};

describe("RankingView priorities", () => {
  it("shows ranks only while a member has weighted criteria", () => {
    const { rerender, container } = render(<RankingView {...props} ranking={unranked} />);
    expect(screen.getByText("Synthetic applicant")).toBeInTheDocument();
    expect(screen.getByText(/Applicants are unranked/)).toBeInTheDocument();
    expect(container.querySelector(".ranking-rank")).toBeNull();
    expect(container.querySelector(".fit-band")).toBeNull();

    const weighted: RankingResponse = {
      ...unranked, weights: { contribution: 1 },
      candidates: [{ ...unranked.candidates[0], rank: 1, fit: 0.8, band: "Strong fit" }],
    };
    rerender(<RankingView {...props} ranking={weighted} />);
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Strong fit")).toBeInTheDocument();
    expect(screen.queryByText(/Applicants are unranked/)).toBeNull();

    rerender(<RankingView {...props} ranking={unranked} />);
    expect(container.querySelector(".ranking-rank")).toBeNull();
    expect(container.querySelector(".fit-band")).toBeNull();
  });
});
