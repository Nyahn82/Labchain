import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { Form } from "../components/Form";
import { Dialog, Pagination, State, Table, Title } from "../components/UI";
import type { Page, Row } from "../types/domain";
import { activationLabel } from "./PatientActivation";
import type { Resource } from "./resources";
export function ResourcePage({
  resource,
  embedded = false,
}: {
  resource: Resource;
  embedded?: boolean;
}) {
  return (
    <PermissionGuard permission={resource.read}>
      <ResourceContent
        key={resource.path}
        resource={resource}
        embedded={embedded}
      />
    </PermissionGuard>
  );
}
function ResourceContent({
  resource: r,
  embedded,
}: {
  resource: Resource;
  embedded: boolean;
}) {
  const { can, user } = useAuth();
  const [params] = useSearchParams();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Row | null | undefined>(() =>
    params.get("new") === "1" && can(r.create) ? null : undefined,
  );
  const [success, setSuccess] = useState("");
  const query = new URLSearchParams({
    page: String(page),
    page_size: "20",
    ...(search ? { search } : {}),
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
  });
  const { data, loading, error, reload } = useResource<Page>(
    r.path + "?" + query,
  );
  return (
    <section className={embedded ? "subsection" : ""}>
      <Title title={r.title} eyebrow={embedded ? "CONFIGURATION" : "DIRECTORY"}>
        {can(r.create) && (
          <button className="primary" onClick={() => setEditing(null)}>
            New {r.singular}
          </button>
        )}
      </Title>
      {success && (
        <p role="status" className="success">
          {success}
        </p>
      )}
      <div className="card">
        <div className="toolbar">
          {r.path === "/patients" && <button onClick={reload} disabled={loading}>Refresh patients</button>}
          {r.searchable !== false && (
            <label>
              Search {r.title.toLowerCase()}
              <input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search records…"
              />
            </label>
          )}
          {r.filters?.map((f) => (
            <label key={f.name}>
              {f.label}
              <select
                value={filters[f.name] || ""}
                onChange={(e) => {
                  setFilters({ ...filters, [f.name]: e.target.value });
                  setPage(1);
                }}
              >
                <option value="">All</option>
                {f.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <State
          loading={loading}
          error={error}
          empty={data?.items.length === 0}
        />
        {data && (
          <>
            <Table
              rows={data.items}
              columns={r.path === "/patients" && !user?.patient && !user?.roles.includes("PATIENT") &&
                (can("PATIENT_ACCOUNT_ACTIVATE") || can("ACCOUNT_READ"))
                ? [...r.columns, { key: "activation_status", label: "Portal activation", render: row => activationLabel(row.activation_status) }]
                : r.columns}
              actions={(row) => (
                <>
                  {r.detail && (
                    <Link
                      className="text-link"
                      to={`/${r.detail}/${row[r.key]}`}
                    >
                      Open
                    </Link>
                  )}
                  {can(r.update) && (
                    <button onClick={() => setEditing(row)}>Edit</button>
                  )}
                </>
              )}
            />
            <Pagination page={page} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
      {editing !== undefined && (
        <Dialog
          title={(editing ? "Edit " : "New ") + r.singular}
          onClose={() => setEditing(undefined)}
        >
          {editing && r.code && (
            <p>{r.code.label}: {String(editing[r.code.key] ?? "—")}</p>
          )}
          <Form
            fields={r.fields}
            initial={editing || {}}
            onSubmit={async (body) => {
              const saved = await api<Row>(
                editing ? `${r.editPath || r.path}/${editing[r.key]}` : r.path,
                { method: editing ? "PATCH" : "POST", body },
              );
              setEditing(undefined);
              const code = r.code && saved[r.code.key];
              setSuccess(`${r.singular} saved${code ? ` (${code})` : ""}.`);
              reload();
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
