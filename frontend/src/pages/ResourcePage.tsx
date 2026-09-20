import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { Form } from "../components/Form";
import { Dialog, Pagination, State, Table, Title } from "../components/UI";
import type { Page, Row } from "../types/domain";
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
  const { can } = useAuth();
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
              columns={r.columns}
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
          <Form
            fields={r.fields}
            initial={editing || {}}
            onSubmit={async (body) => {
              await api(
                editing ? `${r.editPath || r.path}/${editing[r.key]}` : r.path,
                { method: editing ? "PATCH" : "POST", body },
              );
              setEditing(undefined);
              setSuccess(`${r.singular} saved.`);
              reload();
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
