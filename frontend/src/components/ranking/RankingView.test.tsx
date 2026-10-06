import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { deferred } from "../../testSupport";
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
};

describe("RankingView priorities", () => {
  it("shows ranks only while a member has weighted criteria", () => {
    const { rerender, container } = render(<RankingView {...props} ranking={unranked} />);
    expect(screen.queryByText("Synthetic applicant")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Choose criteria to rank applicants");
    expect(screen.queryAllByRole("button", { name: /Print/ })).toHaveLength(0);
    expect(container.querySelector(".ranking-list-toolbar")).toBeNull();
    expect(container.querySelector(".ranking-rank")).toBeNull();
    expect(container.querySelector(".fit-band")).toBeNull();

    const weighted: RankingResponse = {
      ...unranked, weights: { contribution: 1 },
      candidates: [{ ...unranked.candidates[0], rank: 1, fit: 0.8, band: "Strong fit" }],
    };
    rerender(<RankingView {...props} ranking={weighted} />);
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Synthetic applicant")).toBeInTheDocument();
    expect(screen.getByText("Strong fit")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getAllByRole("button", { name: /Print/ })).toHaveLength(2);
    expect(container.querySelector(".ranking-list-toolbar")).not.toBeNull();

    rerender(<RankingView {...props} ranking={unranked} />);
    expect(container.querySelector(".ranking-rank")).toBeNull();
    expect(container.querySelector(".fit-band")).toBeNull();
    expect(screen.queryByText("Synthetic applicant")).toBeNull();
    expect(screen.queryAllByRole("button", { name: /Print/ })).toHaveLength(0);
  });
});


it.each([false, true])("retains draft edits while proposal acknowledgement is pending (accepted=%s)", async (accepted) => {
  const acknowledgement = deferred<boolean>();
  const add = vi.fn().mockReturnValue(acknowledgement.promise);
  render(<RankingView {...props} ranking={unranked} tiers={[]} rankingRun={{
    analysisId: 1, dimensions: [], proposedDimensions: [],
  }} onAddProposal={add} />);
  fireEvent.click(screen.getByRole("button", { name: "Add criterion" }));
  const input = screen.getByPlaceholderText(/^e.g. Families/);
  fireEvent.change(input, { target: { value: "Submitted criterion" } });
  fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));
  expect(input).toHaveValue("Submitted criterion");
  expect(screen.getByRole("button", { name: /^Add$/ })).toBeDisabled();
  await act(async () => acknowledgement.resolve(accepted));
  expect(input).toHaveValue(accepted ? "" : "Submitted criterion");
});

it("keeps a newer draft after an earlier proposal is acknowledged", async () => {
  const acknowledgement = deferred<boolean>();
  render(<RankingView {...props} ranking={unranked} tiers={[]} rankingRun={{
    analysisId: 1, dimensions: [], proposedDimensions: [],
  }} onAddProposal={() => acknowledgement.promise} />);
  fireEvent.click(screen.getByRole("button", { name: "Add criterion" }));
  const input = screen.getByPlaceholderText(/^e.g. Families/);
  fireEvent.change(input, { target: { value: "Submitted criterion" } });
  fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));
  fireEvent.change(input, { target: { value: "Newer draft" } });
  await act(async () => acknowledgement.resolve(true));
  expect(input).toHaveValue("Newer draft");
});
