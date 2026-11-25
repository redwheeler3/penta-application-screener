import type { InputHTMLAttributes } from "react";
import { pacificDateToday } from "../../format";

type Props = {
  value: string;
  onChange?: (value: string) => void;
  notFuture?: boolean;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "max">;

export function DateInput({ value, onChange, notFuture, ...rest }: Props) {
  return <input
    {...rest}
    type="date"
    value={value}
    max={notFuture ? pacificDateToday() : "9999-12-31"}
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
