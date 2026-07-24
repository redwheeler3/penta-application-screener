import { Star } from "lucide-react";

type StarButtonProps = {
  starred: boolean;
  onToggle: (next: boolean) => void;
  // "sm" for dense table rows, "md" for the detail header.
  size?: "sm" | "md";
  // Rows navigate on click, so the star must not bubble to the row handler.
  stopPropagation?: boolean;
};

// A member's private favourite toggle: a gold star, filled when starred and a
// hairline outline when not. Shared by the applicant list, the ranking list, and
// the candidate detail header so the affordance reads the same everywhere. Marked
// no-print — a star is a working aid, not part of the report.
export function StarButton({
  starred,
  onToggle,
  size = "sm",
  stopPropagation = false,
}: StarButtonProps) {
  const px = size === "md" ? 22 : 18;
  return (
    <button
      type="button"
      className={`star-button no-print${starred ? " is-starred" : ""} star-${size}`}
      aria-pressed={starred}
      aria-label={starred ? "Remove from favourites" : "Add to favourites"}
      title={starred ? "Favourited — click to remove" : "Add to favourites"}
      onClick={(event) => {
        if (stopPropagation) event.stopPropagation();
        onToggle(!starred);
      }}
    >
      <Star size={px} fill={starred ? "currentColor" : "none"} strokeWidth={2} />
    </button>
  );
}
