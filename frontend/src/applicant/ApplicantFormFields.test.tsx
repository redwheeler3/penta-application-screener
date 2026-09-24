import { describe, expect, it } from "vitest";

import { validateFormFields } from "./ApplicantFormFields";

describe("applicant form date validation", () => {
  it("rejects future dates only for fields marked as not future", () => {
    const form = document.createElement("form");
    form.innerHTML = `
      <input data-date="true" data-not-future="true" value="2999-01-01" />
      <input data-date="true" value="2999-01-01" />
    `;
    const [birthDate, unrestrictedDate] = Array.from(
      form.querySelectorAll<HTMLInputElement>("input"),
    );

    validateFormFields(form);

    expect(birthDate.validationMessage).toBe("Enter today’s date or an earlier date.");
    expect(unrestrictedDate.validationMessage).toBe("");
  });
});
