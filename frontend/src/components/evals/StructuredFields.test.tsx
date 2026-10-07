import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { EvalCaseEditor } from "./EvalCaseEditor";
import { StructuredFields, type FieldObject } from "./StructuredFields";
import type { EvalFixtureKey } from "../../types";

const dimension = { key: "axis", name: "Axis", definition: "Meaning", high_end: "High", low_end: "Low" };

it("keeps the owning family fixed while adding a case", () => {
  render(<EvalCaseEditor evalKey="matching" existing={null}
    onSave={vi.fn()} onSaved={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Remove pass" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Remove metadata" })).toBeNull();
  expect(screen.queryByDisplayValue("matching")).toBeNull();
  expect(screen.getByText("matching")).toBeInTheDocument();
});
const examples: [EvalFixtureKey, FieldObject, FieldObject][] = [
  ["scoring", { applicant: { facts: { pets: "Original" } }, dimension }, { applicant: { facts: { pets: "Edited" } }, dimension }],
  ["consolidation", { pair: [{ key: "first", name: "First", definition: "Original" }, { key: "second", name: "Second", definition: "Second" }] }, { pair: [{ key: "first", name: "First", definition: "Edited" }, { key: "second", name: "Second", definition: "Second" }] }],
  ["matching", { prior: [{ key: "first", name: "First", definition: "Original" }], new: [{ key: "second", name: "Second", definition: "Second" }] }, { prior: [{ key: "first", name: "First", definition: "Edited" }], new: [{ key: "second", name: "Second", definition: "Second" }] }],
  ["decomposition", { reports: [[{ key: "first", name: "First", definition: "Original" }], [{ key: "second", name: "Second", definition: "Second" }]] }, { reports: [[{ key: "first", name: "First", definition: "Edited" }], [{ key: "second", name: "Second", definition: "Second" }]] }],
  ["screening", { fields: { name: "Original" }, essays: {} }, { fields: { name: "Edited" }, essays: {} }],
];

it.each(examples)("preserves the %s nested shape through the editor save boundary", async (family, given, edited) => {
  const onSave = vi.fn().mockResolvedValue(null);
  const expected = family === "scoring" ? { score_min: -1, score_max: 1 }
    : family === "screening" ? { fires: [], absent: [] } : family === "matching" ? "matches" : "keep";
  const metadata = { pass: family, expected };
  render(<EvalCaseEditor evalKey={family} existing={{ key: "case", metadata, given }}
    onSave={onSave} onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByDisplayValue("Original"), { target: { value: "Edited" } });
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  expect(onSave).toHaveBeenCalledWith({ key: "case", metadata, given: edited });
});

function Editor({ initial, onSave }: { initial: FieldObject; onSave: (value: FieldObject) => void }) {
  const [value, setValue] = useState(initial);
  return <><StructuredFields value={value} onChange={setValue} readOnlyKeys={["key", "metadata.pass"]} />
    <button onClick={() => onSave(value)}>Capture</button></>;
}

it("edits lists, nested alternatives, scalars and empty lists without losing their types", () => {
  const capture = vi.fn();
  render(<Editor onSave={capture} initial={{ flags: ["old"], alternatives: [["option"]], empty: [], score: 0.5, contested: false }} />);
  fireEvent.change(screen.getByDisplayValue("old"), { target: { value: "new" } });
  fireEvent.change(screen.getByDisplayValue("option"), { target: { value: "choice" } });
  fireEvent.change(screen.getByDisplayValue("0.5"), { target: { value: "0.7" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Capture" }));
  expect(capture).toHaveBeenCalledWith({ flags: ["new"], alternatives: [["choice"]], empty: [], score: 0.7, contested: true });
});

it("adds and removes array entries and can create an object in an empty array", () => {
  const capture = vi.fn();
  render(<Editor onSave={capture} initial={{ pair: [{ definition: "Keep" }, { definition: "Remove" }] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove 1" }));
  fireEvent.click(screen.getByRole("button", { name: "+ Add item" }));
  fireEvent.change(screen.getByDisplayValue(""), { target: { value: "Replacement" } });
  fireEvent.click(screen.getByRole("button", { name: "Capture" }));
  expect(capture).toHaveBeenLastCalledWith({ pair: [{ definition: "Keep" }, { definition: "Replacement" }] });
  fireEvent.click(screen.getByRole("button", { name: "Remove 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove 0" }));
  fireEvent.click(screen.getByRole("button", { name: "+ Add object" }));
  fireEvent.click(screen.getByRole("button", { name: "Capture" }));
  expect(capture).toHaveBeenLastCalledWith({ pair: [{}] });
});

it("preserves focus across the text-length boundary and protects locked descendants", () => {
  render(<Editor onSave={vi.fn()} initial={{ key: "fixed", metadata: { pass: "matching" }, note: "a".repeat(60) }} />);
  expect(screen.queryByRole("button", { name: "Remove key" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Remove pass" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Remove metadata" })).toBeNull();
  const text = screen.getByDisplayValue("a".repeat(60));
  text.focus();
  fireEvent.change(text, { target: { value: "a".repeat(61) } });
  expect(screen.getByDisplayValue("a".repeat(61))).toBe(text);
  expect(text).toHaveFocus();
});

it("creates optional Boolean, object, numeric and list assertions through the case save boundary", () => {
  const onSave = vi.fn().mockResolvedValue(null);
  const prompt = vi.spyOn(window, "prompt");
  render(<EvalCaseEditor evalKey="screening" existing={null}
    onSave={onSave} onSaved={vi.fn()} onCancel={vi.fn()} />);

  function addField(path: string, name: string, type: string) {
    const selector = screen.getByRole("combobox", { name: `${path} / New field type` });
    fireEvent.change(selector, { target: { value: type } });
    prompt.mockReturnValueOnce(name);
    fireEvent.click(within(selector.parentElement!).getByRole("button", { name: "+ add field" }));
  }

  fireEvent.change(screen.getByRole("textbox", { name: "Key" }), { target: { value: "typed_optional" } });
  addField("Metadata", "contested", "boolean");
  fireEvent.click(screen.getByRole("checkbox", { name: "Metadata / Contested" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove contested" }));
  addField("Metadata", "contested", "boolean");
  expect(screen.getByRole("checkbox", { name: "Metadata / Contested" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: "Metadata / Contested" }));

  addField("Metadata / Expected", "pets", "object");
  addField("Metadata / Expected / Pets", "dogs", "number");
  fireEvent.change(screen.getByRole("textbox", { name: "Metadata / Expected / Pets / Dogs" }), { target: { value: "2" } });
  addField("Metadata / Expected / Pets", "other_pets", "list");
  const otherPets = screen.getByRole("button", { name: "Remove other_pets" }).closest(".eval-field-row")!;
  fireEvent.click(within(otherPets as HTMLElement).getByRole("button", { name: "+ Add item" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Metadata / Expected / Pets / Other pets / 0" }), { target: { value: "bird" } });
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));

  expect(onSave).toHaveBeenCalledWith({
    key: "typed_optional",
    metadata: { pass: "screening", note: "", contested: true,
      expected: { fires: [], absent: [], pets: { dogs: 2, other_pets: ["bird"] } } },
    given: { fields: { applicant_name: "", pets_text: "", applicant_email: "" }, essays: {} },
  });
  expect(screen.queryByRole("button", { name: "Remove pass" })).toBeNull();
  prompt.mockRestore();
});
