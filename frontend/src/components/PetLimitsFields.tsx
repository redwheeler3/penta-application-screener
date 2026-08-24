import { ELIGIBILITY_PET_NUMERIC_FIELDS } from "../constants";
import type { EligibilityRules } from "../types";
import { NumberInput } from "./NumberInput";

export function PetLimitsFields(props: {
  value: EligibilityRules;
  onChange: (patch: Partial<EligibilityRules>) => void;
}) {
  return (
    <div className="pet-limits-row">
      {ELIGIBILITY_PET_NUMERIC_FIELDS.map((field) => (
        <label key={field.key}>
          <span>{field.label}</span>
          <NumberInput
            min={field.min}
            max={field.max}
            value={props.value[field.key] as number}
            onChange={(value) => props.onChange({ [field.key]: value ?? 0 })}
          />
        </label>
      ))}
      <label className="checkbox-label pet-limits-toggle">
        <input
          type="checkbox"
          checked={props.value.allowOtherPets}
          onChange={(event) => props.onChange({ allowOtherPets: event.target.checked })}
        />
        <span>Allow other pets</span>
      </label>
    </div>
  );
}
