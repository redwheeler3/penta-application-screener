import type { EligibilityRules } from "../types";

export function EmploymentRequirementField(props: {
  value: EligibilityRules["employmentRequirement"];
  onChange: (value: EligibilityRules["employmentRequirement"]) => void;
}) {
  return (
    <label className="settings-field-wide">
      <span>Employment requirement</span>
      <select
        value={props.value}
        onChange={(event) =>
          props.onChange(event.target.value as EligibilityRules["employmentRequirement"])
        }
      >
        <option value="none">No employment requirement</option>
        <option value="at_least_one">At least one adult is working</option>
        <option value="all">Every adult is working</option>
      </select>
      <small>
        Working includes employment and self-employment. With no co-applicant, “every adult”
        applies only to the primary applicant.
      </small>
    </label>
  );
}
