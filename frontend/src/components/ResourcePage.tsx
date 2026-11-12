"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Row } from "@/lib/types";

import { ImportDialog } from "./ImportDialog";
import { Alert, Button, Field, inputClass, Modal, Spinner } from "./ui";

export type Lookups = Record<string, Row[]>;
export type Option = { value: string | number; label: string };

export type FieldDef = {
  name: string;
  label: string;
  type: "text" | "email" | "password" | "number" | "select" | "checkbox" | "multiselect" | "custom";
  required?: boolean;
  hint?: string;
  step?: string;
  /** Select/number: allow an empty value, sent as null. */
  nullable?: boolean;
  /** Only shown when creating a record. */
  createOnly?: boolean;
  /** Span both columns of the form. */
  full?: boolean;
  options?: (lookups: Lookups) => Option[];
  render?: (value: unknown, onChange: (value: unknown) => void, lookups: Lookups) => React.ReactNode;
};

export type ColumnDef = { header: string; cell: (row: Row, lookups: Lookups) => React.ReactNode };

type Props = {
  title: string;
  description: string;
  endpoint: string;
  /** Enables the CSV/Excel import button, e.g. "subjects". */
  importResource?: string;
  /** Extra lists to load, keyed by name, e.g. { tracks: "/api/tracks" }. */
  lookups?: Record<string, string>;
  columns: ColumnDef[];
  fields: FieldDef[];
  defaults: Row;
  /** Text used by the search box. */
  searchText: (row: Row, lookups: Lookups) => string;
  /** Adjust the request body before saving (editing is null when creating). */
  toPayload?: (values: Row, editing: Row | null) => Row;
  adminOnly?: boolean;
  wideForm?: boolean;
  /** Called after any record is saved, deleted or imported. */
  onChanged?: () => void;
};

function toFormValues(fields: FieldDef[], source: Row): Row {
  const values: Row = {};
  for (const field of fields) {
    const raw = source[field.name];
    if (field.type === "number" || field.type === "text" || field.type === "email" || field.type === "password") {
      values[field.name] = raw === null || raw === undefined ? "" : String(raw);
    } else if (field.type === "select") {
      values[field.name] = raw === null || raw === undefined ? "" : raw;
    } else {
      values[field.name] = raw;
    }
  }
  return values;
}

function toBody(fields: FieldDef[], values: Row, editing: boolean): Row {
  const body: Row = {};
  for (const field of fields) {
    if (field.createOnly && editing) continue;
    const raw = values[field.name];
    if (field.type === "number") body[field.name] = raw === "" ? null : Number(raw);
    else if (field.type === "select") body[field.name] = raw === "" ? null : raw;
    else if (field.type === "text") body[field.name] = raw === "" && field.nullable ? null : raw;
    else body[field.name] = raw;
  }
  return body;
}

export function ResourcePage(props: Props) {
  const { endpoint, lookups: lookupEndpoints, fields } = props;
  const { canEdit, isAdmin } = useAuth();
  const mayEdit = props.adminOnly ? isAdmin : canEdit;

  const [rows, setRows] = useState<Row[] | null>(null);
  const [lookups, setLookups] = useState<Lookups>({});
  const [loadError, setLoadError] = useState("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [values, setValues] = useState<Row>({});
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);

  const lookupKey = JSON.stringify(lookupEndpoints ?? {});

  const load = useCallback(async () => {
    try {
      const entries = Object.entries(JSON.parse(lookupKey) as Record<string, string>);
      const [list, ...extra] = await Promise.all([
        api<Row[]>(endpoint),
        ...entries.map(([, url]) => api<Row[]>(url)),
      ]);
      setLookups(Object.fromEntries(entries.map(([name], index) => [name, extra[index]])));
      setRows(list);
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load the data.");
    }
  }, [endpoint, lookupKey]);

  useEffect(() => {
    // Initial data fetch; state is only set after the request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!rows || !term) return rows ?? [];
    return rows.filter((row) => props.searchText(row, lookups).toLowerCase().includes(term));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, search, lookups]);

  const closeForm = useCallback(() => setEditing(null), []);

  function openForm(row: Row | "new") {
    setValues(toFormValues(fields, row === "new" ? props.defaults : row));
    setFormError("");
    setEditing(row);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const isEdit = editing !== "new";
    setSaving(true);
    setFormError("");
    try {
      let body = toBody(fields, values, isEdit);
      if (props.toPayload) body = props.toPayload(body, isEdit ? editing : null);
      await api(isEdit ? `${endpoint}/${editing.id}` : endpoint, { method: isEdit ? "PUT" : "POST", body });
      setEditing(null);
      await load();
      props.onChanged?.();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: Row) {
    if (!window.confirm("Delete this record? This cannot be undone.")) return;
    try {
      await api(`${endpoint}/${row.id}`, { method: "DELETE" });
      await load();
      props.onChanged?.();
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not delete.");
    }
  }

  const setValue = (name: string, value: unknown) => setValues((current) => ({ ...current, [name]: value }));
  const isEdit = editing !== null && editing !== "new";
  const singular = props.title.toLowerCase().replace(/s$/, "");

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-stone-900">{props.title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-stone-600">{props.description}</p>
        </div>
        {mayEdit && (
          <div className="flex gap-2">
            {props.importResource && (
              <Button variant="secondary" onClick={() => setImporting(true)}>
                Import CSV / Excel
              </Button>
            )}
            <Button onClick={() => openForm("new")}>Add {singular}</Button>
          </div>
        )}
      </div>

      {loadError && (
        <div className="mb-4">
          <Alert>{loadError}</Alert>
        </div>
      )}

      {rows === null ? (
        !loadError && <Spinner />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <input
              type="search"
              aria-label={`Search ${props.title.toLowerCase()}`}
              placeholder="Search…"
              className={`${inputClass} max-w-xs`}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <span className="text-sm text-stone-500">
              {visible.length} of {rows.length}
            </span>
          </div>

          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="border-b border-stone-200 bg-stone-100 text-xs uppercase tracking-wide text-stone-600">
                <tr>
                  {props.columns.map((column) => (
                    <th key={column.header} scope="col" className="px-4 py-2.5 font-semibold">
                      {column.header}
                    </th>
                  ))}
                  {mayEdit && (
                    <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {visible.map((row) => (
                  <tr key={row.id} className="hover:bg-stone-50">
                    {props.columns.map((column) => (
                      <td key={column.header} className="px-4 py-2.5 align-top text-stone-800">
                        {column.cell(row, lookups)}
                      </td>
                    ))}
                    {mayEdit && (
                      <td className="whitespace-nowrap px-4 py-2 text-right">
                        <Button variant="ghost" small onClick={() => openForm(row)}>
                          Edit
                        </Button>
                        <Button variant="ghost" small className="!text-red-700" onClick={() => remove(row)}>
                          Delete
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={props.columns.length + 1} className="px-4 py-10 text-center text-stone-500">
                      {rows.length === 0
                        ? `No ${props.title.toLowerCase()} yet.${mayEdit ? " Add one or import a file." : ""}`
                        : "Nothing matches your search."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {editing && (
        <Modal title={`${isEdit ? "Edit" : "Add"} ${singular}`} onClose={closeForm} wide={props.wideForm}>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {fields
                .filter((field) => !(field.createOnly && isEdit))
                .map((field) => (
                  <FormField
                    key={field.name}
                    field={field}
                    value={values[field.name]}
                    lookups={lookups}
                    onChange={(value) => setValue(field.name, value)}
                  />
                ))}
            </div>
            {formError && <Alert>{formError}</Alert>}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={closeForm}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {importing && props.importResource && (
        <ImportDialog
          resource={props.importResource}
          title={props.title}
          onClose={() => setImporting(false)}
          onImported={() => {
            load();
            props.onChanged?.();
          }}
        />
      )}
    </div>
  );
}

type FormFieldProps = { field: FieldDef; value: unknown; lookups: Lookups; onChange: (value: unknown) => void };

function FormField({ field, value, lookups, onChange }: FormFieldProps) {
  const span = field.full || field.type === "multiselect" || field.type === "custom" ? "sm:col-span-2" : "";
  const options = field.options?.(lookups) ?? [];

  if (field.type === "checkbox") {
    return (
      <label className={`flex items-center gap-2 self-end pb-2 text-sm text-stone-800 ${span}`}>
        <input
          type="checkbox"
          className="size-4 accent-emerald-800"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        {field.label}
      </label>
    );
  }

  if (field.type === "multiselect") {
    const selected = new Set((value as (string | number)[]) ?? []);
    return (
      <fieldset className={span}>
        <legend className="mb-1 text-sm font-medium text-stone-800">
          {field.label} <span className="font-normal text-stone-500">({selected.size} selected)</span>
        </legend>
        <div className="grid max-h-44 gap-x-4 gap-y-1 overflow-y-auto rounded-md border border-stone-300 p-3 sm:grid-cols-2">
          {options.length === 0 && <p className="text-sm text-stone-500">Nothing to choose from yet.</p>}
          {options.map((option) => (
            <label key={option.value} className="flex items-start gap-2 text-sm text-stone-800">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-emerald-800"
                checked={selected.has(option.value)}
                onChange={(event) => {
                  const next = new Set(selected);
                  if (event.target.checked) next.add(option.value);
                  else next.delete(option.value);
                  onChange([...next]);
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
        {field.hint && <p className="mt-1 text-xs text-stone-500">{field.hint}</p>}
      </fieldset>
    );
  }

  if (field.type === "custom") {
    return (
      <div className={span}>
        <p className="mb-1 text-sm font-medium text-stone-800">{field.label}</p>
        {field.render?.(value, onChange, lookups)}
        {field.hint && <p className="mt-1 text-xs text-stone-500">{field.hint}</p>}
      </div>
    );
  }

  if (field.type === "select") {
    return (
      <Field label={field.label} hint={field.hint} required={field.required} className={span}>
        {(id) => (
          <select
            id={id}
            className={inputClass}
            required={field.required}
            value={String(value ?? "")}
            onChange={(event) => {
              const match = options.find((option) => String(option.value) === event.target.value);
              onChange(match ? match.value : "");
            }}
          >
            {(field.nullable || value === "") && <option value="">{field.nullable ? "— None —" : "Choose…"}</option>}
            {options.map((option) => (
              <option key={option.value} value={String(option.value)}>
                {option.label}
              </option>
            ))}
          </select>
        )}
      </Field>
    );
  }

  return (
    <Field label={field.label} hint={field.hint} required={field.required} className={span}>
      {(id) => (
        <input
          id={id}
          className={inputClass}
          type={field.type}
          step={field.step}
          min={field.type === "number" ? 0 : undefined}
          required={field.required}
          autoComplete={field.type === "password" ? "new-password" : "off"}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}
