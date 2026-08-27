type HouseIconProps = {
  size?: number;
};

// Penta's brand house mark: a softened silhouette with a rounded arched door
// and a window, both knocked out via the even-odd fill rule so the icon works
// on any background. Uses currentColor so callers control the color. The same
// artwork backs the favicon (see public/favicon.ico).
export function HouseIcon({ size = 24 }: HouseIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M16 3.2 1.8 14.8a1 1 0 0 0 .65 1.77H5V27a1.5 1.5 0 0 0 1.5 1.5h19A1.5 1.5 0 0 0 27 27V16.57h2.55a1 1 0 0 0 .65-1.77L16 3.2ZM13 28.5v-7a3 3 0 0 1 6 0v7H13ZM19.4 13.2a.8.8 0 0 0-.8.8v2.6a.8.8 0 0 0 .8.8h3.4a.8.8 0 0 0 .8-.8V14a.8.8 0 0 0-.8-.8h-3.4Z"
      />
    </svg>
  );
}
