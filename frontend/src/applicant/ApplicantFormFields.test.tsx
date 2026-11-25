import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DateField, MoneyField, validateFormFields } from "./ApplicantFormFields";

it("keeps income blank or zero and validates whole dollars through the shared control", () => {
  function Form() { const [value, setValue] = useState(""); return <form><MoneyField label="Income" value={value} required onChange={setValue} /></form>; }
  const { container } = render(<Form />);
  const input = screen.getByRole("textbox", { name: /Income/ }) as HTMLInputElement;
  expect(input.type).toBe("text");
  expect(input.checkValidity()).toBe(false);
  for (const [value, valid] of [["0", true], ["80000", true], ["-1", false], ["1.5", false]] as const) {
    fireEvent.change(input, { target: { value } }); validateFormFields(container.querySelector("form"));
    expect(input.checkValidity()).toBe(valid);
  }
  fireEvent.change(input, { target: { value: "" } });
  expect(input).toHaveValue("");
});

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
