import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { RankingRunConfirmation } from "./RankingRunConfirmation";

const props: ComponentProps<typeof RankingRunConfirmation> = {
  estimate: {
    eligible: 8, fanOut: 5, breakdown: { criteriaUsd: 0.5, matchUsd: 0.1, scoringUsd: 0.2 },
    estimatedUsd: 0.8, approximate: true, capUsd: 2, withinCap: true, rankingCurrent: false,
  },
  scoreCurrentEstimate: {
    eligible: 8, toAnalyze: 2, cached: 6, cachedToRefresh: 0, dimensions: 4, estimatedUsd: 0.05, capUsd: 2, withinCap: true,
  },
  hasCurrentCriteria: true,
  pendingProposals: [],
  running: false,
  onRun: vi.fn(),
  onCancel: vi.fn(),
};

describe("ranking confirmation", () => {
  it.each([
    { proposals: [], score: null, title: "Rank the candidates?" },
    { proposals: [], score: props.scoreCurrentEstimate, title: "Update the ranking?" },
    { proposals: [], score: { ...props.scoreCurrentEstimate!, toAnalyze: 0 }, title: "Ranking is up to date." },
    { proposals: ["Participation"], score: props.scoreCurrentEstimate, title: "Apply your proposed criterion?" },
    { proposals: ["Participation", "Skills"], score: props.scoreCurrentEstimate, title: "Apply your proposed criteria?" },
  ])("shows the appropriate heading: $title", ({ proposals, score, title }) => {
    render(<RankingRunConfirmation {...props} pendingProposals={proposals} scoreCurrentEstimate={score} />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover new criteria" })).toBeEnabled();
  });

  it("prioritizes missing scores until a proposal requires discovery, and preserves each action", async () => {
    const onRun = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<RankingRunConfirmation {...props} onRun={onRun} onCancel={onCancel} />);
    expect(screen.getByRole("button", { name: "Score missing applicants" })).toHaveClass("primary-button");
    expect(screen.getByRole("button", { name: "Discover new criteria" })).toHaveClass("secondary-button");
    await user.click(screen.getByRole("button", { name: "Score missing applicants" }));
    expect(onRun).toHaveBeenLastCalledWith("score-current");

    rerender(<RankingRunConfirmation {...props} onRun={onRun} onCancel={onCancel} pendingProposals={["Participation"]} />);
    expect(screen.getByRole("button", { name: "Score missing applicants" })).toHaveClass("secondary-button");
    expect(screen.getByRole("button", { name: "Discover new criteria" })).toHaveClass("primary-button");
    await user.click(screen.getByRole("button", { name: "Discover new criteria" }));
    expect(onRun).toHaveBeenLastCalledWith("discover");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("gates each action by its own cost cap and gates both actions while running", () => {
    const { rerender } = render(<RankingRunConfirmation {...props} estimate={{ ...props.estimate, withinCap: false }} />);
    expect(screen.getByRole("button", { name: "Discover new criteria" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Score missing applicants" })).toBeEnabled();
    rerender(<RankingRunConfirmation {...props} scoreCurrentEstimate={{ ...props.scoreCurrentEstimate!, withinCap: false }} />);
    expect(screen.getByRole("button", { name: "Discover new criteria" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Score missing applicants" })).toBeDisabled();
    rerender(<RankingRunConfirmation {...props} running />);
    expect(screen.getAllByRole("button", { name: "Running…" })).toHaveLength(2);
    for (const button of screen.getAllByRole("button", { name: "Running…" })) expect(button).toBeDisabled();
  });
});


it("offers a free cached refresh without claiming the ranking is already current", () => {
  render(<RankingRunConfirmation {...props} scoreCurrentEstimate={{
    ...props.scoreCurrentEstimate!, toAnalyze: 0, cachedToRefresh: 8, estimatedUsd: 0,
  }} />);
  expect(screen.getByText("Reuse saved scores?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reuse cached scores" })).toBeEnabled();
  expect(screen.getByText(/No AI calls are needed/)).toBeInTheDocument();
  expect(screen.queryByText("Ranking is up to date.")).not.toBeInTheDocument();
});
