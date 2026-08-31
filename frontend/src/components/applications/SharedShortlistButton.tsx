import { ListChecks, ListPlus } from "lucide-react";

export function SharedShortlistButton(props: {
  shortlisted: boolean;
  onToggle: (next: boolean) => void;
  compact?: boolean;
  size?: "sm" | "md";
  stopPropagation?: boolean;
}) {
  const action = props.shortlisted ? "Remove from shared shortlist" : "Add to shared shortlist";
  const size = props.size ?? "sm";
  const Icon = props.shortlisted ? ListChecks : ListPlus;
  return (
    <button
      type="button"
      className={`shortlist-button no-print shortlist-${size}${props.shortlisted ? " is-shortlisted" : ""}${props.compact ? " is-compact" : ""}`}
      aria-pressed={props.shortlisted}
      aria-label={action}
      title={`${action}. Visible to everyone on the committee.`}
      onClick={(event) => {
        if (props.stopPropagation) event.stopPropagation();
        props.onToggle(!props.shortlisted);
      }}
    >
      <Icon size={size === "md" ? 21 : 16} strokeWidth={2} />
      {props.compact ? null : <span>{props.shortlisted ? "Shared shortlist" : "Add to shared shortlist"}</span>}
    </button>
  );
}
