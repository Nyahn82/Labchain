import { Fragment, useState, type FormEvent } from "react";
import { useResource } from "../api/useResource";
import { useAuth } from "../auth/Auth";
import { Alert, State } from "./UI";
import type { Page, Row } from "../types/domain";
import { person } from "../utils/display";
export interface LookupSpec {
  path: string;
  key: string;
  label?: string;
  permission: string;
  params?: string;
}
export interface Choice {
  value: string | number;
  label: string;
}
export interface Field {
  name: string;
  label: string;
  type?:
    | "text"
    | "textarea"
    | "date"
    | "email"
    | "password"
    | "decimal"
    | "number"
    | "boolean"
    | "select"
    | "lookup"
    | "multi";
  required?: boolean;
  max?: number;
  default?: unknown;
  options?: Choice[];
  lookup?: LookupSpec;
  help?: string;
  group?: string;
}
export const choices = (...values: string[]): Choice[] =>
  values.map((value) => ({ value, label: value.replaceAll("_", " ") }));
export function Lookup({
  spec,
  label,
  multiple = false,
  value,
  onChange,
  required = false,
}: {
  spec: LookupSpec;
  label: string;
  multiple?: boolean;
  value: unknown;
  onChange: (v: unknown) => void;
  required?: boolean;
}) {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const { data, loading, error } = useResource<Page>(
    can(spec.permission)
      ? `${spec.path}?page=${page}&page_size=20&search=${encodeURIComponent(search)}${spec.params || ""}`
      : null,
  );
  const rows = data?.items || [];
  const ids = multiple ? (Array.isArray(value) ? (value as number[]) : []) : [];
  const name = (row: Row) =>
    spec.label
      ? String(row[spec.label])
      : spec.path === "/signatories"
        ? `Profile #${row.signatory_id} · Staff #${row.staff_id} · ${row.license_number_snapshot || "No license snapshot"}`
        : person(row);
  if (!can(spec.permission))
    return (
      <div className="field">
        <span>{label}</span>
        <p className="muted">
          Selection requires{" "}
          {spec.permission.toLowerCase().replaceAll("_", " ")} access.
        </p>
      </div>
    );
  return (
    <div className="field lookup">
      <label>
        Search {label.toLowerCase()}
        <input
          type="search"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Type to find a record"
        />
      </label>
      <State loading={loading} error={error} />
      {multiple ? (
        <fieldset>
          <legend>
            {label}
            {required ? " *" : ""}
          </legend>
          {rows.map((row) => {
            const id = Number(row[spec.key]);
            return (
              <label className="check" key={id}>
                <input
                  type="checkbox"
                  checked={ids.includes(id)}
                  onChange={(e) => {
                    setLabels({ ...labels, [id]: name(row) });
                    onChange(
                      e.target.checked
                        ? [...ids, id]
                        : ids.filter((v) => v !== id),
                    );
                  }}
                />
                {name(row)}
              </label>
            );
          })}
          {!loading && !rows.length && <p>No matching records.</p>}
          <div className="selected">
            {ids.map((id) => (
              <span className="chip" key={id}>
                {labels[id] ||
                  name(
                    rows.find((r) => r[spec.key] === id) || {
                      [spec.label || "username"]: `Record #${id}`,
                    },
                  )}
                <button
                  type="button"
                  aria-label={`Remove selection ${id}`}
                  onClick={() => onChange(ids.filter((v) => v !== id))}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </fieldset>
      ) : (
        <label>
          {label}
          {required ? " *" : ""}
          <select
            required={required}
            value={value == null ? "" : String(value)}
            onChange={(e) => {
              const row = rows.find(
                (r) => String(r[spec.key]) === e.target.value,
              );
              if (row) setLabels({ ...labels, [e.target.value]: name(row) });
              onChange(e.target.value ? Number(e.target.value) : null);
            }}
          >
            <option value="">Select…</option>
            {value != null &&
              !rows.some((r) => String(r[spec.key]) === String(value)) && (
                <option value={String(value)}>
                  {labels[String(value)] || `Record #${value}`}
                </option>
              )}
            {rows.map((row) => (
              <option key={String(row[spec.key])} value={String(row[spec.key])}>
                {name(row)}
              </option>
            ))}
          </select>
        </label>
      )}
      {data && data.total > 20 && (
        <div className="actions">
          <button
            type="button"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous choices
          </button>
          <span>Page {page}</span>
          <button
            type="button"
            disabled={page * 20 >= data.total}
            onClick={() => setPage((p) => p + 1)}
          >
            More choices
          </button>
        </div>
      )}
    </div>
  );
}
export function Form({
  fields,
  initial = {},
  onSubmit,
  submit = "Save",
  children,
}: {
  fields: Field[];
  initial?: Row;
  onSubmit: (body: Row) => Promise<unknown>;
  submit?: string;
  children?: React.ReactNode;
}) {
  const [values, setValues] = useState<Row>(() =>
    Object.fromEntries(
      fields.map((f) => [
        f.name,
        initial[f.name] ??
          f.default ??
          (f.type === "boolean" ? false : f.type === "multi" ? [] : ""),
      ]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const change = (name: string, v: unknown) =>
    setValues((old) => ({ ...old, [name]: v }));
  async function save(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(undefined);
    const body: Row = {};
    for (const f of fields) {
      const v = values[f.name];
      body[f.name] = v === "" ? null : f.type === "number" ? Number(v) : v;
    }
    try {
      await onSubmit(body);
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
      setValues((old) => ({
        ...old,
        ...Object.fromEntries(
          fields.filter((f) => f.type === "password").map((f) => [f.name, ""]),
        ),
      }));
    }
  }
  return (
    <form onSubmit={save}>
      <Alert error={error} />
      <fieldset disabled={busy} className="form-grid">
        {fields.map((f) => (
          <Fragment key={f.name}>
            {f.group && <h3 className="wide field-group">{f.group}</h3>}
            <div
              className={
                "field " +
                (f.type === "textarea" || f.type === "multi" ? "wide" : "")
              }
              key={f.name}
            >
              {f.lookup ? (
                <Lookup
                  label={f.label}
                  spec={f.lookup}
                  multiple={f.type === "multi"}
                  value={values[f.name]}
                  onChange={(v) => change(f.name, v)}
                  required={f.required}
                />
              ) : f.type === "boolean" ? (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={!!values[f.name]}
                    onChange={(e) => change(f.name, e.target.checked)}
                  />
                  {f.label}
                </label>
              ) : (
                <label>
                  {f.label}
                  {f.required ? " *" : ""}
                  {f.type === "select" ? (
                    <select
                      required={f.required}
                      value={String(values[f.name] ?? "")}
                      onChange={(e) => change(f.name, e.target.value)}
                    >
                      <option value="">Select…</option>
                      {f.options?.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : f.type === "textarea" ? (
                    <textarea
                      maxLength={f.max || 16000}
                      required={f.required}
                      value={String(values[f.name] ?? "")}
                      onChange={(e) => change(f.name, e.target.value)}
                    />
                  ) : (
                    <input
                      type={
                        ["date", "email", "password", "number"].includes(
                          f.type || "",
                        )
                          ? f.type
                          : "text"
                      }
                      inputMode={f.type === "decimal" ? "decimal" : undefined}
                      autoComplete={
                        f.type === "password" ? "new-password" : "off"
                      }
                      required={f.required}
                      maxLength={f.max || undefined}
                      step={f.type === "number" ? "1" : undefined}
                      value={String(values[f.name] ?? "")}
                      onChange={(e) => change(f.name, e.target.value)}
                    />
                  )}
                </label>
              )}
              {f.help && <small>{f.help}</small>}
            </div>
          </Fragment>
        ))}
        {children}
      </fieldset>
      <div className="form-footer">
        <span className="muted">* Required fields</span>
        <button className="primary" disabled={busy}>
          {busy ? "Saving…" : submit}
        </button>
      </div>
    </form>
  );
}
