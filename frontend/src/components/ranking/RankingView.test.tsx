import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { type ComponentProps, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { deferred } from "../../testSupport";
import type { RankingResponse, Tier } from "../../types";
import { RankingView } from "./RankingView";

const props: Omit<ComponentProps<typeof RankingView>, "ranking"> = {
  rankingRun: null, tiers: null, acceptedTiers: null, proposedDimensions: [],
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

it("renders accepted priorities for both app and native printing while the editor is ahead", () => {
  const accepted = [{ id: "priority", label: "Accepted priority", dimensionKeys: ["contribution"] }];
  const { container } = render(<RankingView {...props} ranking={{ ...unranked, weights: { contribution: 1 } }}
    tiers={[{ ...accepted[0], label: "Unsaved priority" }]} acceptedTiers={accepted}
    rankingRun={{ analysisId: 1, proposedDimensions: [], dimensions: [{
      key: "contribution", name: "Contribution", definition: "Synthetic criterion", highEnd: "High", lowEnd: "Low", whyItDifferentiates: "", fromCommitteeRequest: false,
    }] }} />);
  expect(screen.getByRole("textbox", { name: "Tier name" })).toHaveValue("Unsaved priority");
  const print = container.querySelector(".tier-summary-print")!;
  expect(print).toHaveTextContent("Accepted priority");
  expect(print).not.toHaveTextContent("Unsaved priority");
  const printWindow = vi.spyOn(window, "print").mockImplementation(() => {});
  fireEvent.click(screen.getByRole("button", { name: "Print ranking" }));
  expect(printWindow).toHaveBeenCalledOnce();
  // Native printing reads this same print-only DOM without invoking an app button.
  window.dispatchEvent(new Event("beforeprint"));
  expect(print).toHaveTextContent("Accepted priority");
  printWindow.mockRestore();
});

it("keeps custom tiers independent through add, remove, add, rename and remove", () => {
  function Editor() {
    const [tiers, setTiers] = useState<Tier[]>([
      { id: "base", label: "Base", dimensionKeys: [] },
      { id: "ignore", label: "Ignore", dimensionKeys: [], ignore: true },
    ]);
    return <RankingView {...props} ranking={unranked} rankingRun={{ analysisId: 1, dimensions: [], proposedDimensions: [] }}
      tiers={tiers} acceptedTiers={tiers} onSaveTiers={setTiers} />;
  }
  render(<Editor />);
  const add = screen.getByRole("button", { name: "Add tier" });
  fireEvent.click(add);
  fireEvent.click(add);
  const firstCustom = screen.getByDisplayValue("Tier 2").closest(".tier-row")!;
  fireEvent.click(within(firstCustom as HTMLElement).getByRole("button", { name: "Remove tier" }));
  fireEvent.click(add);
  const custom = screen.getAllByDisplayValue("Tier 3");
  expect(custom).toHaveLength(2);
  fireEvent.change(custom[0], { target: { value: "Independent" } });
  expect(screen.getAllByDisplayValue("Tier 3")).toHaveLength(1);
  const renamed = screen.getByDisplayValue("Independent").closest(".tier-row")!;
  fireEvent.click(within(renamed as HTMLElement).getByRole("button", { name: "Remove tier" }));
  expect(screen.getByDisplayValue("Tier 3")).toBeInTheDocument();
});

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
