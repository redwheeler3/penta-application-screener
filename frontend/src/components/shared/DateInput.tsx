import { createContext, useContext, type InputHTMLAttributes } from "react";

export const ApplicantToday = createContext<string | null>(null);

type Props = {
  value: string;
  onChange?: (value: string) => void;
  notFuture?: boolean;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "max">;

export function DateInput({ value, onChange, notFuture, ...rest }: Props) {
  const today = useContext(ApplicantToday);
  return <input
    {...rest}
    type="date"
    value={value}
    max={notFuture && today ? today : "9999-12-31"}
    data-date="true"
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
