import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { Row } from "../types/domain";
import { display, timestamp, value } from "../utils/display";
export function Alert({ error }: { error?: Error | null }) {
  return error ? (
    <div role="alert" className="alert">
      {error.message}
      {error instanceof ApiError && error.fields.length > 0 && (
        <p>Check: {error.fields.join(", ")}</p>
      )}
    </div>
  ) : null;
}
export function Badge({ children }: { children: unknown }) {
  const text = display(children);
  return (
    <span className={"badge " + text.toLowerCase().replaceAll("_", "-")}>
      {text.replaceAll("_", " ")}
    </span>
  );
}
export function Title({
  title,
  eyebrow = "STAFF WORKSPACE",
  children,
}: {
  title: string;
  eyebrow?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      <div className="actions">{children}</div>
    </div>
  );
}
export function State({
  loading,
  error,
  empty,
}: {
  loading?: boolean;
  error?: Error;
  empty?: boolean;
}) {
  return loading ? (
    <p role="status" className="empty">
      Loading records…
    </p>
  ) : error ? (
    <Alert error={error} />
  ) : empty ? (
    <p className="empty">No records found.</p>
  ) : null;
}
export interface Column {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
  date?: boolean;
  badge?: boolean;
}
export function Table({
  rows,
  columns,
  actions,
  caption,
}: {
  rows: Row[];
  columns: Column[];
  actions?: (row: Row) => ReactNode;
  caption?: string;
}) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label={caption || "Scrollable records"}
    >
      <table>
        <caption className="sr-only">{caption || "Records"}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col">
                {c.label}
              </th>
            ))}
            {actions && <th scope="col">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key}>
                  {c.render ? (
                    c.render(row)
                  ) : c.badge ? (
                    <Badge>{value(row, c.key)}</Badge>
                  ) : c.date ? (
                    timestamp(value(row, c.key))
                  ) : (
                    display(value(row, c.key))
                  )}
                </td>
              ))}
              {actions && (
                <td>
                  <div className="actions">{actions(row)}</div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Pagination({
  page,
  total,
  size = 20,
  onPage,
}: {
  page: number;
  total: number;
  size?: number;
  onPage: (n: number) => void;
}) {
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        {total} records · Page {page} of {Math.max(1, Math.ceil(total / size))}
      </span>
      <div className="actions">
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button
          disabled={page * size >= total}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
export function Dialog({
  title,
  children,
  onClose,
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement;
    const el = ref.current;
    el?.showModal();
    return () => {
      el?.close();
      prior?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy && !ref.current?.querySelector("fieldset:disabled"))
          onClose();
      }}
    >
      <div className="dialog-heading">
        <h2>{title}</h2>
        <button
          aria-label="Close dialog"
          onClick={() => {
            if (!ref.current?.querySelector("fieldset:disabled")) onClose();
          }}
          disabled={busy}
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Action({
  label,
  description,
  run,
  onDone,
  children,
  danger = false,
  valid = true,
}: {
  label: string;
  description: string;
  run: () => Promise<unknown>;
  onDone: () => void;
  children?: ReactNode;
  danger?: boolean;
  valid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  return (
    <>
      <button className={danger ? "danger" : ""} onClick={() => setOpen(true)}>
        {label}
      </button>
      {open && (
        <Dialog title={label} onClose={() => setOpen(false)} busy={busy}>
          <p>{description}</p>
          {children}
          <Alert error={error} />
          <div className="actions dialog-actions">
            <button disabled={busy} onClick={() => setOpen(false)}>
              Back
            </button>
            <button
              className={danger ? "danger" : "primary"}
              disabled={busy || !valid}
              onClick={async () => {
                setBusy(true);
                setError(undefined);
                try {
                  await run();
                  setOpen(false);
                  onDone();
                } catch (e) {
                  setError(e as Error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Working…" : "Confirm " + label.toLowerCase()}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
