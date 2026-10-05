import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/Auth";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { Action, Pagination, State, Table, Title } from "../components/UI";
import type { Page, Row } from "../types/domain";

const activityTypes = ["LOGIN_SUCCESS", "LOGIN_FAILED", "LOGOUT", "SESSION_REVOKED", "ACCOUNT_SUSPENDED", "ACCOUNT_REACTIVATED", "ACCOUNT_LOCKED", "ACCOUNT_DISABLED", "ACCOUNT_STATUS_UPDATED", "PASSWORD_CHANGED", "MFA_SUCCESS", "MFA_FAILED", "MFA_RESET"];
const userColumn = { key: "username", label: "User", render: (r: Row) => <>{String(r.username || "Unknown account")}{r.display_name ? <small> · {String(r.display_name)}</small> : null}</> };
const agentColumn = { key: "user_agent", label: "Browser information", render: (r: Row) => r.user_agent ? <details><summary>User-agent details</summary><span className="auth-user-agent">{String(r.user_agent)}</span></details> : "Not recorded" };

export function AuthenticationActivity() {
  const { can } = useAuth();
  const readable = can("AUTH_ACTIVITY_VIEW");
  const sessionAccess = readable || can("SESSION_MANAGE");
  const [tab, setTab] = useState(readable ? "All" : "Active Sessions");
  if (!sessionAccess) return <section className="card"><h1>Permission required</h1><p>You do not have access to this section.</p></section>;
  return <>
    <Title title="Authentication Activity" />
    <nav className="actions" aria-label="Authentication activity views">
      {(readable ? ["All", "Staff", "Patients", "Failed Logins", "Active Sessions"] : ["Active Sessions"]).map(value =>
        <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{value}</button>)}
    </nav>
    {tab === "Active Sessions" ? <SessionList /> : <ActivityList key={tab} accountType={tab === "Staff" ? "STAFF" : tab === "Patients" ? "PATIENT" : ""} failed={tab === "Failed Logins"} />}
  </>;
}

export function ActivityList({ userId, accountType = "", failed = false }: { userId?: number; accountType?: string; failed?: boolean }) {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ search: "", activity_type: failed ? "LOGIN_FAILED" : "", status: "", date_from: "", date_to: "", ip_address: "", account_type: accountType });
  const [applied, setApplied] = useState(filters);
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  if (userId) params.set("user_id", String(userId));
  Object.entries(applied).forEach(([key, value]) => { if (value) params.set(key, value); });
  const state = useResource<Page>(`/admin/auth-activity?${params}`);
  return <section className="card">
    <h2>{userId ? "Recent authentication activity" : "Authentication events"}</h2>
    {!userId && <form className="toolbar" onSubmit={e => { e.preventDefault(); setApplied(filters); setPage(1); }}>
      <label>Search user<input maxLength={100} value={filters.search} onChange={e => setFilters({ ...filters, search: e.target.value })} /></label>
      <label>Account type<select value={filters.account_type} onChange={e => setFilters({ ...filters, account_type: e.target.value })}><option value="">All</option><option value="STAFF">Staff</option><option value="PATIENT">Patients</option></select></label>
      <label>Activity<select disabled={failed} value={filters.activity_type} onChange={e => setFilters({ ...filters, activity_type: e.target.value })}><option value="">All</option>{activityTypes.map(v => <option key={v}>{v}</option>)}</select></label>
      <label>Outcome<select value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">All</option>{["SUCCESS", "FAILED", "RECORDED"].map(v => <option key={v}>{v}</option>)}</select></label>
      <label>From (UTC)<input type="datetime-local" value={filters.date_from} onChange={e => setFilters({ ...filters, date_from: e.target.value })} /></label>
      <label>To (UTC)<input type="datetime-local" value={filters.date_to} onChange={e => setFilters({ ...filters, date_to: e.target.value })} /></label>
      <label>IP address<input maxLength={45} value={filters.ip_address} onChange={e => setFilters({ ...filters, ip_address: e.target.value })} /></label>
      <button type="submit">Apply filters</button>
    </form>}
    <State {...state} empty={!state.data?.items.length} />
    {state.data && <><Table rows={state.data.items} columns={[userColumn,
      { key: "account_type", label: "Account Type" }, { key: "activity_type", label: "Activity", badge: true },
      { key: "occurred_at", label: "Timestamp", date: true }, { key: "ip_address", label: "IP Address" }, agentColumn,
      { key: "status", label: "Status", badge: true }]} />
      <Pagination page={page} total={state.data.total} onPage={setPage} /></>}
  </section>;
}

export function SessionList({ userId, onChanged }: { userId?: number; onChanged?: () => void }) {
  const { can, user } = useAuth();
  const [page, setPage] = useState(1);
  const [stateFilter, setStateFilter] = useState("ACTIVE");
  const [accountType, setAccountType] = useState("");
  const params = new URLSearchParams({ page: String(page), page_size: "20", state: stateFilter });
  if (accountType) params.set("account_type", accountType);
  const state = useResource<Page>(`${userId ? `/admin/users/${userId}/sessions` : "/admin/sessions"}?${params}`);
  const count = useResource<Page>(userId ? `/admin/users/${userId}/sessions?state=ACTIVE&page_size=1` : null);
  const reload = () => { state.reload(); count.reload(); onChanged?.(); };
  return <section className="card">
    <h2>Account sessions</h2>
    {userId && <><State loading={count.loading} error={count.error} />{count.data && <p>Active Session Count: {count.data.total}</p>}</>}
    <div className="toolbar">
      <label>Session state<select value={stateFilter} onChange={e => { setStateFilter(e.target.value); setPage(1); }}>{["ACTIVE", "EXPIRED", "REVOKED"].map(v => <option key={v}>{v}</option>)}</select></label>
      {!userId && <label>Account type<select value={accountType} onChange={e => { setAccountType(e.target.value); setPage(1); }}><option value="">All</option><option value="STAFF">Staff</option><option value="PATIENT">Patients</option></select></label>}
      {userId && userId !== user?.user_id && can("SESSION_MANAGE") && <Action label="Log Out All Sessions" danger description="End all active sessions for this account. The account can sign in again if active."
        run={() => api(`/admin/users/${userId}/sessions/revoke-all`, { method: "POST" })} onDone={reload} />}
    </div>
    <State {...state} empty={!state.data?.items.length} />
    {state.data && <><Table rows={state.data.items} columns={[userColumn, { key: "account_type", label: "Account Type" },
      { key: "created_at", label: "Signed in", date: true }, { key: "expires_at", label: "Expires", date: true },
      { key: "revoked_at", label: "Revoked", date: true }, { key: "ip_address", label: "IP Address" }, agentColumn,
      { key: "state", label: "Status", badge: true }]} actions={r => <>
        {r.is_current ? <span>Current session</span> : r.state === "ACTIVE" && can("SESSION_MANAGE") && <Action label="Revoke Session" danger description={`End this session for ${r.username}.`}
          run={() => api(`/admin/sessions/${r.session_id}/revoke`, { method: "POST" })} onDone={reload} />}
        {!userId && can("ACCOUNT_READ") && <Link to={`/administration/${r.user_id}`}>Manage account</Link>}
      </>} /><Pagination page={page} total={state.data.total} onPage={setPage} /></>}
  </section>;
}

export function SuspensionActions({ account, done }: { account: Row; done: () => void }) {
  const { user } = useAuth();
  const [reason, setReason] = useState("");
  const patient = !!account.patient;
  if (user?.user_id === account.user_id) return <p>You cannot change your own account status.</p>;
  return <>
    {account.account_status === "ACTIVE" && <Action label={patient ? "Suspend Portal Account" : "Suspend Account"} danger
      description={patient ? "This immediately prevents portal sign-in and revokes active sessions. This disables portal access only. The patient's laboratory record and history remain available to authorized staff." : "This immediately prevents this account from signing in and revokes its active sessions."}
      valid={!!reason.trim() && reason.trim().length <= 500}
      run={() => api(`/users/${account.user_id}/suspend`, { method: "POST", body: { reason: reason.trim() } })} onDone={done}>
      <label>Reason *<textarea required maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label>
    </Action>}
    {account.account_status === "SUSPENDED" && <Action label="Reactivate Account" description="Restore sign-in eligibility. Previously revoked sessions stay revoked."
      run={() => api(`/users/${account.user_id}/reactivate`, { method: "POST" })} onDone={done} />}
  </>;
}
