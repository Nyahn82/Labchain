import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import {
  Action,
  Dialog,
  Pagination,
  State,
  Table,
  Title,
} from "../components/UI";
import { Form, choices } from "../components/Form";
import { Details } from "../components/Details";
import type { Row, Page } from "../types/domain";
import { field, resources } from "./resources";
import { person } from "../utils/display";
export function PersonDetail({ kind }: { kind: "patients" | "staff" }) {
  return (
    <PermissionGuard permission={resources[kind].read}>
      <PersonContent kind={kind} />
    </PermissionGuard>
  );
}
function PersonContent({ kind }: { kind: "patients" | "staff" }) {
  const { id } = useParams();
  const { can } = useAuth();
  const r = resources[kind];
  const state = useResource<Row>(`${r.path}/${id}`);
  const [edit, setEdit] = useState(false);
  return (
    <>
      <Title title={state.data ? person(state.data) : r.title}>
        <Link to={`/${kind}`}>All {kind}</Link>
        {state.data && can(r.update) && (
          <button onClick={() => setEdit(true)}>Edit details</button>
        )}
      </Title>
      <State {...state} />
      {state.data && (
        <>
          <section className="card">
            <Details
              row={state.data}
              fields={r.fields.map((f) => [f.name, f.label])}
            />
          </section>
          {kind === "patients" &&
            (can("PATIENT_ACCOUNT_ACTIVATE") || can("ACCOUNT_READ")) && (
              <Activation id={id!} />
            )}{" "}
          {kind === "staff" && <StaffAccounts id={id!} />}
        </>
      )}
      {edit && state.data && (
        <Dialog title={`Edit ${r.singular}`} onClose={() => setEdit(false)}>
          <Form
            fields={r.fields}
            initial={state.data}
            onSubmit={async (body) => {
              await api(`${r.path}/${id}`, { method: "PATCH", body });
              setEdit(false);
              state.reload();
            }}
          />
        </Dialog>
      )}
    </>
  );
}
function Activation({ id }: { id: string }) {
  const state = useResource<Row>(`/patients/${id}/activation-status`);
  return (
    <section className="card">
      <h2>Patient activation</h2>
      <State {...state} />
      {state.data && (
        <Details
          row={state.data}
          fields={Object.keys(state.data).filter((k) => !k.endsWith("_id"))}
        />
      )}
    </section>
  );
}
function StaffAccounts({ id }: { id: string }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);
  return (
    <section className="card">
      <div className="section-heading">
        <h2>Account association</h2>
        {can("ACCOUNT_CREATE") && (
          <button onClick={() => setOpen(true)}>Create account</button>
        )}
      </div>
      <p>The server permits one account association for each staff member.</p>
      {can("ACCOUNT_READ") && <StaffAccountAssociation key={version} id={id} />}
      {open && (
        <Dialog title="Create staff account" onClose={() => setOpen(false)}>
          <AccountCreate
            id={id}
            done={() => {
              setOpen(false);
              setVersion((v) => v + 1);
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
function StaffAccountAssociation({ id }: { id: string }) {
  const [account, setAccount] = useState<Row>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error>();
  useEffect(() => {
    const controller = new AbortController();
    async function find() {
      try {
        let pageNumber = 1;
        while (!controller.signal.aborted) {
          const records = await api<Page>(
            `/users?page=${pageNumber}&page_size=100`,
            { signal: controller.signal },
          );
          if (controller.signal.aborted) return;
          const match = records.items.find(
            (r) => (r.staff as Row | null)?.staff_id === Number(id),
          );
          if (match) {
            setAccount(match);
            break;
          }
          if (pageNumber * 100 >= records.total) break;
          pageNumber++;
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(e as Error);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void find();
    return () => controller.abort();
  }, [id]);
  return (
    <>
      <State loading={loading} error={error} />
      {account ? (
        <>
          <Details row={account} fields={["username", "account_status"]} />
          <Link to={`/administration/${account.user_id}`}>
            Manage account and roles →
          </Link>
        </>
      ) : (
        !loading && !error && <p>No associated account.</p>
      )}
    </>
  );
}
function AccountCreate({ id, done }: { id: string; done: () => void }) {
  const { can } = useAuth();
  const roles = useResource<Row[]>(can("ROLE_READ") ? "/roles" : null);
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <>
      <State {...roles} />
      <Form
        fields={[
          field("username", "Username", { required: true, max: 60 }),
          field("password", "Initial password", {
            type: "password",
            required: true,
            help: "At least 12 characters. Share through your approved secure process.",
          }),
        ]}
        onSubmit={async (body) => {
          await api(`/staff/${id}/account`, {
            method: "POST",
            body: { ...body, role_codes: selected },
          });
          done();
        }}
      >
        {can("ROLE_ASSIGN") && roles.data && (
          <RoleChoices
            roles={roles.data}
            selected={selected}
            change={setSelected}
          />
        )}
      </Form>
    </>
  );
}
export function RoleChoices({
  roles,
  selected,
  change,
}: {
  roles: Row[];
  selected: string[];
  change: (v: string[]) => void;
}) {
  return (
    <fieldset className="wide">
      <legend>Assigned roles</legend>
      {roles
        .filter((r) => r.is_active || selected.includes(String(r.role_code)))
        .map((r) => (
          <label className="check" key={String(r.role_code)}>
            <input
              type="checkbox"
              checked={selected.includes(String(r.role_code))}
              onChange={(e) =>
                change(
                  e.target.checked
                    ? [...selected, String(r.role_code)]
                    : selected.filter((v) => v !== r.role_code),
                )
              }
            />
            {String(r.role_name)} <small>{String(r.role_code)}</small>
          </label>
        ))}
    </fieldset>
  );
}
export function Administration() {
  const { can } = useAuth();
  if (!can("ACCOUNT_READ") && can("ROLE_READ"))
    return (
      <>
        <Title title="Role administration" />
        <RoleDiscovery />
      </>
    );
  return (
    <PermissionGuard permission="ACCOUNT_READ">
      <Accounts />
    </PermissionGuard>
  );
}
function Accounts() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const { can } = useAuth();
  const state = useResource<Page>(
    `/users?page=${page}&page_size=20&search=${encodeURIComponent(search)}${status ? "&account_status=" + status : ""}`,
  );
  return (
    <>
      <Title title="Account administration" />
      <section className="card">
        <div className="toolbar">
          <label>
            Search username
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label>
            Account status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All</option>
              {["ACTIVE", "INACTIVE", "LOCKED"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          Staff associations are shown with each account. Search by username or
          browse pages.
        </p>
        <State {...state} empty={!state.data?.items.length} />
        {state.data && (
          <>
            <Table
              rows={state.data.items}
              columns={[
                { key: "username", label: "Username" },
                { key: "staff", label: "Staff association" },
                { key: "account_status", label: "Status", badge: true },
                {
                  key: "roles",
                  label: "Roles",
                  render: (r) => (r.roles as string[]).join(", "),
                },
              ]}
              actions={(r) => (
                <Link to={`/administration/${r.user_id}`}>Manage account</Link>
              )}
            />
            <Pagination page={page} total={state.data.total} onPage={setPage} />
          </>
        )}
      </section>
      {can("ROLE_READ") && <RoleDiscovery />}
    </>
  );
}
function RoleDiscovery() {
  const roles = useResource<Row[]>("/roles");
  const permissions = useResource<Row[]>("/permissions");
  return (
    <section className="card">
      <h2>Roles and permissions</h2>
      <State {...roles} />
      {roles.data && (
        <Table
          rows={roles.data}
          columns={[
            { key: "role_name", label: "Role" },
            { key: "role_code", label: "Code" },
            { key: "description", label: "Description" },
            { key: "is_active", label: "Status", badge: true },
          ]}
        />
      )}
      <details>
        <summary>Permission catalog</summary>
        <State {...permissions} />
        {permissions.data && (
          <Table
            rows={permissions.data}
            columns={[
              { key: "permission_code", label: "Permission" },
              { key: "description", label: "Description" },
            ]}
          />
        )}
      </details>
    </section>
  );
}
export function AccountDetail() {
  return (
    <PermissionGuard permission="ACCOUNT_READ">
      <AccountContent />
    </PermissionGuard>
  );
}
function AccountContent() {
  const { id } = useParams();
  const { can } = useAuth();
  const state = useResource<Row>(`/users/${id}`);
  return (
    <>
      <Title title="Account details">
        <Link to="/administration">All accounts</Link>
      </Title>
      <State {...state} />
      {state.data && (
        <AccountEditor
          key={`${id}-${JSON.stringify(state.data)}`}
          account={state.data}
          done={state.reload}
          can={can}
        />
      )}
    </>
  );
}
export function AccountEditor({
  account,
  done,
  can,
}: {
  account: Row;
  done: () => void;
  can: (p: string) => boolean;
}) {
  const [status, setStatus] = useState(String(account.account_status));
  const [selected, setSelected] = useState(account.roles as string[]);
  const roles = useResource<Row[]>(can("ROLE_READ") ? "/roles" : null);
  const path = `/users/${account.user_id}`;
  return (
    <>
      <section className="card">
        <Details
          row={account}
          fields={[
            "username",
            "account_status",
            "staff",
            "created_at",
            "last_login_at",
          ]}
        />
        {can("ACCOUNT_STATUS_UPDATE") && (
          <div className="actions">
            <label>
              New account status
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {choices("ACTIVE", "INACTIVE", "LOCKED").map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <Action
              label="Update account status"
              description={`Change ${account.username} to ${status}. Disabling or locking may end access.`}
              valid={status !== account.account_status}
              run={() =>
                api(path + "/status", {
                  method: "PATCH",
                  body: { account_status: status },
                })
              }
              onDone={done}
            />
          </div>
        )}
      </section>
      {can("ROLE_ASSIGN") && (
        <section className="card">
          <h2>Role assignment</h2>
          <State {...roles} />
          {roles.data ? (
            <>
              <RoleChoices
                roles={roles.data}
                selected={selected}
                change={setSelected}
              />
              <Action
                label="Replace roles"
                description="Replace this account’s assigned roles with the selected set. This changes access immediately."
                run={() =>
                  api(path + "/roles", {
                    method: "PUT",
                    body: { role_codes: selected },
                  })
                }
                onDone={done}
              />
            </>
          ) : (
            !can("ROLE_READ") && <p>Role discovery permission is required.</p>
          )}
        </section>
      )}
      {can("ACCOUNT_MFA_RESET") && (
        <section className="card">
          <h2>Account security</h2>
          <Action
            label="Reset MFA"
            danger
            description="Remove this account’s MFA enrollment and recovery codes and revoke sessions. Verify the account holder’s identity through your approved process first."
            run={() => api(path + "/mfa/reset", { method: "POST" })}
            onDone={done}
          />
        </section>
      )}
    </>
  );
}
