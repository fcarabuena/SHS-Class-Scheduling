"use client";

import { useEffect, useId } from "react";

const BUTTON_STYLES = {
  primary: "bg-emerald-800 text-white hover:bg-emerald-900 disabled:bg-emerald-800/50",
  secondary: "border border-stone-500 bg-white text-stone-900 hover:bg-stone-100 disabled:border-stone-300 disabled:text-stone-400",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50 disabled:text-red-300",
  ghost: "text-stone-700 hover:bg-stone-200/70 disabled:text-stone-400",
};

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_STYLES;
  small?: boolean;
};

export function Button({ variant = "primary", small, className = "", type = "button", ...rest }: ButtonProps) {
  const size = small ? "px-2.5 py-1 text-sm" : "px-4 py-2 text-sm";
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 font-normal transition-colors disabled:cursor-not-allowed ${size} ${BUTTON_STYLES[variant]} ${className}`}
      {...rest}
    />
  );
}

export const inputClass =
  "block w-full border border-stone-300 border-b-stone-500 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 disabled:bg-stone-100 disabled:text-stone-500";

type FieldProps = {
  label: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: (id: string) => React.ReactNode;
};

export function Field({ label, hint, required, className = "", children }: FieldProps) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-stone-800">
        {label}
        {required && <span className="text-red-700"> *</span>}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-stone-500">{hint}</p>}
    </div>
  );
}

type TextFieldProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  label: string;
  hint?: string;
  value: string | number;
  onChange: (value: string) => void;
  wrapperClassName?: string;
};

export function TextField({ label, hint, value, onChange, wrapperClassName, required, ...rest }: TextFieldProps) {
  return (
    <Field label={label} hint={hint} required={required} className={wrapperClassName}>
      {(id) => (
        <input
          id={id}
          className={inputClass}
          value={value}
          required={required}
          onChange={(event) => onChange(event.target.value)}
          {...rest}
        />
      )}
    </Field>
  );
}

const ALERT_STYLES = {
  error: "border-red-200 border-l-red-600 bg-red-50 text-stone-900",
  success: "border-emerald-200 border-l-emerald-600 bg-emerald-100 text-stone-900",
  info: "border-sky-200 border-l-sky-700 bg-sky-50 text-stone-900",
  warning: "border-amber-200 border-l-amber-300 bg-amber-50 text-stone-900",
};

export function Alert({ kind = "error", children }: { kind?: keyof typeof ALERT_STYLES; children: React.ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`border border-l-4 px-3 py-2 text-sm ${ALERT_STYLES[kind]}`}>
      {children}
    </div>
  );
}

export function Badge({ children, tone = "stone" }: { children: React.ReactNode; tone?: "stone" | "emerald" | "amber" | "sky" }) {
  const tones = {
    stone: "bg-stone-200 text-stone-900",
    emerald: "bg-emerald-100 text-emerald-900",
    amber: "bg-amber-100 text-amber-900",
    sky: "bg-sky-100 text-sky-900",
  };
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

type ModalProps = { title: string; onClose: () => void; wide?: boolean; children: React.ReactNode };

export function Modal({ title, onClose, wide, children }: ModalProps) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/60 sm:items-center sm:p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`flex max-h-[92vh] w-full flex-col border border-stone-300 bg-white ${wide ? "sm:max-w-3xl" : "sm:max-w-lg"}`}
      >
        <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3">
          <h2 id={titleId} className="text-base font-semibold text-stone-900">
            {title}
          </h2>
          <Button variant="ghost" small onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <p className="py-10 text-center text-sm text-stone-500">{label}</p>;
}
