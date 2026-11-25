import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { NumberInput } from "../components/shared/NumberInput";
import { ApplicantToday } from "../components/shared/DateInput";
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
  it("applies the supplied Pacific day and updates validity when that day advances", () => {
    const formAt = (day: string) => <ApplicantToday.Provider value={day}><form>
      <DateField label="Employment start" value="2026-11-25" notFuture onChange={() => {}} />
      <DateField label="Unrestricted date" value="2999-01-01" onChange={() => {}} />
    </form></ApplicantToday.Provider>;
    const view = render(formAt("2026-11-24"));
    const form = view.container.querySelector("form")!;
    validateFormFields(form);
    const [limited, unrestricted] = form.querySelectorAll("input");
    expect(limited.validity.rangeOverflow).toBe(true);
    expect(unrestricted.checkValidity()).toBe(true);
    view.rerender(formAt("2026-11-25"));
    expect(limited.max).toBe("2026-11-25");
    expect(form.checkValidity()).toBe(true);
  });
});

it("does not join ambiguous pasted digits in numeric settings and still accepts leading decimals", () => {
  const changed = vi.fn();
  const { container } = render(<NumberInput value={2} onChange={changed} />);
  const input = container.querySelector("input")!;
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "2-5" } });
  expect(changed).not.toHaveBeenCalled();
  expect(input).toHaveValue("2");
  fireEvent.change(input, { target: { value: ".7" } });
  expect(changed).toHaveBeenLastCalledWith(0.7);
});
