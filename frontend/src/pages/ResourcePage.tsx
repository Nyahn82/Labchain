import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { Form, Lookup } from "../components/Form";
import { Dialog, Pagination, State, Table, Title } from "../components/UI";
import type { Page, Row } from "../types/domain";
import { ActivationBadge, activationLabels } from "./PatientActivation";
import type { Resource } from "./resources";
export function ResourcePage({
  resource,
  embedded = false,
}: {
  resource: Resource;
  embedded?: boolean;
}) {
  const { user } = useAuth();
  return (
    <PermissionGuard permission={resource.read}>
      <ResourceContent
        key={`${resource.path}:${user?.user_id}:${user?.permissions.join(',')}:${user?.roles.join(',')}`}
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
  const patientDirectory = r.path === "/patients";
  const activationAccess = patientDirectory && !user?.patient && !user?.roles.includes("PATIENT") &&
    (can("PATIENT_ACCOUNT_ACTIVATE") || can("ACCOUNT_READ"));
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>((): Record<string, string> => activationAccess ? {
    activation_group: params.get("activation_group") || "", activation_state: params.get("activation_state") || "",
  } : {});
  const [sort, setSort] = useState("patient_id");
  const [direction, setDirection] = useState("asc");
  const [editing, setEditing] = useState<Row | null | undefined>(() =>
    params.get("new") === "1" && can(r.create) ? null : undefined,
  );
  const [success, setSuccess] = useState("");
  const query = new URLSearchParams({
    page: String(page),
    page_size: "20",
    ...(search ? { search } : {}),
    ...(patientDirectory ? { sort_by: sort, sort_direction: direction } : {}),
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
          {activationAccess && <>
            <label>Portal activation group<select value={filters.activation_group || ""} onChange={e => { setFilters({ ...filters, activation_group: e.target.value }); setPage(1); }}>
              <option value="">All groups</option><option value="ACTIVATED">Activated</option><option value="NOT_ACTIVATED">Not activated</option>
            </select></label>
            <label>Activation state<select value={filters.activation_state || ""} onChange={e => { setFilters({ ...filters, activation_state: e.target.value }); setPage(1); }}>
              <option value="">All activation states</option>{Object.entries(activationLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select></label>
          </>}
          {patientDirectory && <>
            <label>Sort patients<select value={sort} onChange={e => { setSort(e.target.value); setPage(1); }}>
              <option value="patient_id">Registration order</option><option value="name">Name</option><option value="patient_code">Permanent code</option>
              {activationAccess && <option value="activation">Activation state</option>}
            </select></label>
            <label>Sort direction<select value={direction} onChange={e => { setDirection(e.target.value); setPage(1); }}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
          </>}
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
          {r.filters?.map((f) => f.lookup ? (
            <Lookup key={f.name} spec={f.lookup} label={f.label}
              value={filters[f.name] || null}
              onChange={value => { setFilters({ ...filters, [f.name]: value == null ? "" : String(value) }); setPage(1); }} />
          ) : (
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
              columns={activationAccess
                ? [...r.columns, { key: "activation_status", label: "Portal activation", render: row => <ActivationBadge value={row.activation_status} /> }]
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
