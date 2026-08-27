import { HouseIcon } from "./HouseIcon";

export function BrandLockup() {
  return (
    <span className="penta-brand-lockup">
      <HouseIcon size={32} />
      <span className="brand-name-full">Penta Housing Co-Op</span>
      <span className="brand-name-short">Penta Co-Op</span>
    </span>
  );
}
