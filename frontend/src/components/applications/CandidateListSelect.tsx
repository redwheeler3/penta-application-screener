import { ChevronDown } from "lucide-react";

export type CandidateListView = "all" | "favourites" | "shortlist";

export function CandidateListSelect(props: {
  value: CandidateListView;
  favourites: number;
  shortlist: number;
  onChange: (value: CandidateListView) => void;
}) {
  const current = props.value === "favourites"
    ? `Mine (${props.favourites})`
    : props.value === "shortlist"
      ? `Shared (${props.shortlist})`
      : "All";
  return (
    <label className="candidate-list-select no-print">
      <span>View</span>
      <span className="candidate-list-select-shell">
        <span className="candidate-list-current" aria-hidden="true">{current}</span>
        <ChevronDown size={14} aria-hidden="true" />
        <select
          aria-label="Choose candidate list"
          name="candidate-list-view"
          value={props.value}
          onChange={(event) => props.onChange(event.target.value as CandidateListView)}
        >
          <option value="all">All</option>
          <option value="favourites">My favourites ({props.favourites})</option>
          <option value="shortlist">Shared shortlist ({props.shortlist})</option>
        </select>
      </span>
    </label>
  );
}
