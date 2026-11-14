import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DateField, validateFormFields } from "./ApplicantFormFields";

describe("applicant form date validation", () => {
  it("rejects future dates only for fields marked as not future", () => {
    const { container } = render(<form>
      <DateField label="Birth date" value="2999-01-01" notFuture onChange={() => {}} />
      <DateField label="Unrestricted date" value="2999-01-01" onChange={() => {}} />
    </form>);
    const form = container.querySelector("form")!;
    const [birthDate, unrestrictedDate] = Array.from(
      form.querySelectorAll<HTMLInputElement>("input"),
    );

    validateFormFields(form);

    expect(birthDate.validationMessage).toBe("Enter today’s date or an earlier date.");
    expect(unrestrictedDate.validationMessage).toBe("");
  });
});
