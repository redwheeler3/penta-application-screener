import type { InputHTMLAttributes } from "react";

type Props = {
  value: string;
  onChange?: (value: string) => void;
  notFuture?: boolean;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "max">;

export function localDateToday(): string {
  const today = new Date();
  return [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0")].join("-");
}

export function DateInput({ value, onChange, notFuture, ...rest }: Props) {
  return <input
    {...rest}
    type="date"
    value={value}
    max={notFuture ? localDateToday() : "9999-12-31"}
    data-date="true"
    data-not-future={notFuture ? "true" : undefined}
    onInput={(event) => {
      event.currentTarget.setCustomValidity("");
      rest.onInput?.(event);
    }}
    onChange={(event) => {
      event.currentTarget.setCustomValidity("");
      onChange?.(event.currentTarget.value);
    }}
  />;
}
