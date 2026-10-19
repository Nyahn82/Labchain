import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Users, ClipboardList, FileText, FlaskConical, RefreshCw, Activity } from "lucide-react";
import { BlockchainQueue } from "../components/BlockchainQueue";
import { useAuth } from "../auth/Auth";
import { useResource } from "../api/useResource";
import type { Page } from "../types/domain";
import type { Overview, WorkflowCounts } from "../types/dashboard";
import type { NetworkOverview } from "../types/monitor";
import { Badge, State, Table, Title } from "../components/UI";
import { timestamp } from "../utils/display";

const workflows = [
  { key: "orders", permission: "LAB_ORDER_READ", title: "Orders", to: "/orders", icon: ClipboardList,
    states: ["REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"], note: "Current status of all laboratory orders." },
  { key: "specimens", permission: "SPECIMEN_READ", title: "Specimens", to: "/specimens", icon: FlaskConical,
    states: ["PENDING", "COLLECTED", "RECEIVED", "PROCESSED", "REJECTED"], note: "Current status of all registered specimens." },
  { key: "results", permission: "LAB_RESULT_READ", title: "Results", to: "/results", icon: Activity,
    states: ["DRAFT", "REVIEWED", "VERIFIED"], note: "Result items, not individual patients or orders." },
  { key: "reports", permission: "REPORT_READ", title: "Reports", to: "/reports", icon: FileText,
    states: ["GENERATED", "APPROVED", "RELEASED", "REVOKED"], note: "All report versions, including superseded versions." },
] as const;

function validCounts(group: WorkflowCounts | undefined, states: readonly string[]): group is WorkflowCounts {
  return !!group && Number.isSafeInteger(group.total) && group.total >= 0 && !!group.statuses &&
    states.every(key => Number.isSafeInteger(group.statuses[key]) && group.statuses[key] >= 0) &&
    Object.values(group.statuses).reduce((sum, count) => sum + count, 0) === group.total;
}
const label = (state: string) => state.toLowerCase().replaceAll("_", " ");

function useObservationClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}
function observationStatus(status: string, checkedAt: string | undefined, now: number) {
  const age = now - Date.parse(checkedAt || "");
  return !Number.isFinite(age) || age < -60000 ? "UNKNOWN" : age > 300000 ? "STALE" : status;
}

function Summary() {
  const { can } = useAuth();
  const state = useResource<Overview>("/dashboard/overview");
  const valid = state.data && typeof state.data.generated_at === "string" && !Number.isNaN(Date.parse(state.data.generated_at));
  const data = valid ? state.data : undefined;
  const available = workflows.filter(item => can(item.permission));
  const validGroups = available.filter(item => validCounts(data?.[item.key], item.states));
  const patients = can("PATIENT_READ") && Number.isSafeInteger(data?.patients) && data!.patients! >= 0 ? data!.patients : undefined;
  const pending = [
    ["orders", "REQUESTED", "Requested orders"],
    ["specimens", "PENDING", "Specimens awaiting collection"],
    ["specimens", "COLLECTED", "Specimens awaiting receipt"],
    ["results", "DRAFT", "Draft results to review"],
    ["results", "REVIEWED", "Reviewed results to verify"],
    ["reports", "GENERATED", "Generated reports to review"],
    ["reports", "APPROVED", "Approved reports awaiting release"],
  ] as const;
  return <section aria-labelledby="overview-summary-heading">
    <div className="section-heading overview-section-heading">
      <div><h2 id="overview-summary-heading">Workflow at a glance</h2>
        <p className="muted">Current states across all records. Counts are not limited to today.</p></div>
      <button onClick={state.reload} disabled={state.loading} aria-label="Refresh workflow summary"><RefreshCw size={16} aria-hidden="true" /> Refresh summary</button>
    </div>
    {state.loading ? <p role="status" className="empty">Loading workflow summary…</p> :
      state.error || !data ? <div role="alert" className="empty">Workflow summary unavailable. Refresh to try again.</div> : <>
        <p className="small muted">Snapshot: <time dateTime={data.generated_at}>{timestamp(data.generated_at)}</time></p>
        <div className="overview-metrics">
          {can("PATIENT_READ") && <article className="card overview-metric" aria-label="Registered patients">
            <Users size={22} aria-hidden="true" /><h3>Registered patients</h3><strong>{patients === undefined ? "Unavailable" : patients.toLocaleString()}</strong><Link to="/patients">View patients <ArrowUpRight size={14} aria-hidden="true" /></Link>
          </article>}
          {available.map(item => {
            const group = data[item.key];
            const allowedLink = !["specimens", "results"].includes(item.key) || can("LAB_ORDER_READ");
            return <article key={item.key} className="card overview-metric" aria-label={`${item.title} total`}>
              <item.icon size={22} aria-hidden="true" /><h3>{item.title}</h3>
              <strong>{validCounts(group, item.states) ? group.total.toLocaleString() : "Unavailable"}</strong>
              {allowedLink && <Link to={item.to}>View {item.title.toLowerCase()} <ArrowUpRight size={14} aria-hidden="true" /></Link>}
            </article>;
          })}
        </div>
        <MonitoringMetrics data={data} />
        {!available.length && !can("PATIENT_READ") && <p className="empty">No workflow summaries are available for your permissions.</p>}
        {validGroups.length > 0 && <section className="card overview-pending" aria-labelledby="pending-work-heading">
          <div><p className="eyebrow">NEXT STEPS</p><h2 id="pending-work-heading">Pending work</h2>
            <p className="muted">Work awaiting the next stage. Existing signing, approval and release requirements still apply.</p></div>
          <dl>{pending.filter(([key]) => validGroups.some(group => group.key === key)).map(([key, status, title]) =>
            <div key={title}><dt>{["orders", "reports"].includes(key) ? <Link to={`/${key}?status=${status}`}>{title}</Link> : title}</dt><dd>{data[key]!.statuses[status].toLocaleString()}</dd></div>)}</dl>
          {pending.filter(([key]) => validGroups.some(group => group.key === key)).every(([key, status]) => data[key]!.statuses[status] === 0) &&
            <p className="overview-clear">No pending work in the stages you can view.</p>}
        </section>}
        <div className="overview-workflows">{validGroups.map(item => <WorkflowPanel key={item.key} title={item.title} group={data[item.key]!} states={item.states} note={item.note} to={["orders", "reports"].includes(item.key) ? item.to : undefined} />)}</div>
      </>}
  </section>;
}

function WorkflowPanel({ title, group, states, note, to }: { title: string; group: WorkflowCounts; states: readonly string[]; note: string; to?: string }) {
  return <section className="card overview-workflow" aria-label={`${title} status breakdown`}>
    <h3>{title} by status</h3><p className="small muted">{note}</p>
    {group.total === 0 ? <p className="empty">No {title.toLowerCase()} recorded.</p> : <dl>{states.map(status => <div key={status}>
      <dt>{to ? <Link to={`${to}?status=${status}`}><Badge>{status}</Badge></Link> : <Badge>{status}</Badge>}</dt><dd>{group.statuses[status].toLocaleString()}<span className="sr-only"> {label(status)} {title.toLowerCase()}</span></dd>
      <div className="overview-bar" aria-hidden="true"><span style={{ width: `${100 * group.statuses[status] / group.total}%` }} /></div>
    </div>)}</dl>}
  </section>;
}

function Metric({ title, value, to, note }: { title: string; value?: number; to?: string; note?: string }) {
  return <article className="card overview-metric" aria-label={title}><h3>{title}</h3>
    <strong>{Number.isSafeInteger(value) && value! >= 0 ? value!.toLocaleString() : "Unavailable"}</strong>
    {note && <p className="small muted">{note}</p>}{to && <Link to={to}>View details →</Link>}</article>;
}

function MonitoringMetrics({ data }: { data: Overview }) {
  const { can } = useAuth();
  const now = useObservationClock();
  return <>
    <div className="overview-metrics">
      {can("AUTH_ACTIVITY_VIEW") && <>
        <Metric title="Recently active staff" value={data.presence?.recently_active} to="/administration/activity"
          note="Distinct staff accounts with authenticated server activity in the last 5 minutes and a valid session. This does not prove physical presence." />
        <Metric title="Failed logins · last 24 hours" value={data.failed_logins?.count}
          to={data.failed_logins ? `/administration/activity?event=LOGIN_FAILED&date_from=${encodeURIComponent(data.failed_logins.since)}&date_to=${encodeURIComponent(data.failed_logins.until)}` : "/administration/activity"}
          note="Password-login failures, including unknown usernames. MFA failures are separate." />
      </>}
      {can("PATIENT_READ") && (can("ACCOUNT_READ") || can("PATIENT_ACCOUNT_ACTIVATE")) && <>
        <Metric title="Patients without activated portal accounts" value={data.activation?.not_activated} to="/patients?activation_group=NOT_ACTIVATED" />
        <Metric title="Patient accounts requiring review" value={data.activation?.review_required} to="/patients?activation_state=REVIEW_REQUIRED" note="Consumed invitations without account links require administrator review." />
      </>}
      {can("ACCOUNT_READ") && <>
        <Metric title="Active accounts" value={data.accounts?.active} to="/administration?account_status=ACTIVE" note="Enabled accounts; separate from current activity." />
        <Metric title="Suspended accounts" value={data.accounts?.suspended} to="/administration?account_status=SUSPENDED" />
      </>}
      {can("REPORT_READ") && <>
        <Metric title="Reports without signatory assignments" value={data.signing?.unassigned} to="/reports?signing_stage=unassigned" />
        <Metric title="Reports awaiting signature" value={data.signing?.awaiting_signature} to="/reports?signing_stage=awaiting_signature" />
        <Metric title="Signed reports awaiting approval" value={data.signing?.awaiting_approval} to="/reports?signing_stage=awaiting_approval" note="All assigned signatures complete. Approval still validates report prerequisites." />
      </>}
    </div>
    {can("BLOCKCHAIN_STATUS_VIEW") && <section className="card" aria-label="Service attention">
      <h2>Service attention</h2><p>Application and database reflect this request. Worker activity expires after 5 minutes; an idle queue does not prove worker health.</p>
      {data.services ? <ul>{data.services.map(service => <li key={service.name}>
        <strong>{service.name}</strong>: <Badge>{observationStatus(service.status, service.checked_at, now)}</Badge> · {service.checked_at ? timestamp(service.checked_at) : "No observation available"}
      </li>)}</ul> : <p role="alert">Service observations unavailable.</p>}
    </section>}
  </>;
}

function FabricHealth() {
  const now = useObservationClock();
  const state = useResource<NetworkOverview>("/admin/blockchain/overview");
  const data = state.data;
  const valid = data && ["ONLINE", "DEGRADED", "OFFLINE", "UNKNOWN"].includes(data.status) && Array.isArray(data.nodes);
  const observed = (status: string, checkedAt: string) => observationStatus(status, checkedAt, now);
  return <section className="card" aria-labelledby="overview-network-heading">
    <div className="section-heading"><h2 id="overview-network-heading">Fabric network</h2>
      <button onClick={state.reload} disabled={state.loading} aria-label="Refresh Fabric health"><RefreshCw size={16} aria-hidden="true" /></button></div>
    {state.loading ? <p role="status">Loading Fabric health…</p> : state.error || !valid ? <p role="alert">Fabric health unavailable. Retry with the refresh button.</p> : <>
      <p>Observed network status: <Badge>{observed(data.status, data.checked_at)}</Badge></p>
      <p>{data.nodes.filter(node => observed(node.status, node.checked_at) === "ONLINE").length} of {data.nodes.length} peers with fresh online observations</p>
      <h3>Node attention</h3><ul>{data.nodes.map(node => {
        return <li key={node.name}><strong>{node.name}</strong>: <Badge>{observed(node.status, node.checked_at)}</Badge>{node.error_code && ` · ${node.error_code}`} · {timestamp(node.checked_at)}</li>;
      })}</ul>
      <p>Orderer: <Badge>{observed(data.orderer?.status || "UNKNOWN", data.checked_at)}</Badge></p>
      <p className="small muted">Checked: {timestamp(data.checked_at)}. Observations may be cached; this is separate from the anchoring queue.</p>
    </>}
    <Link to="/administration/blockchain">Open Blockchain Monitor <ArrowUpRight size={14} aria-hidden="true" /></Link>
  </section>;
}

function RecentOrders() {
  const recent = useResource<Page>("/lab-orders?page=1&page_size=5");
  return <section className="card" aria-labelledby="overview-recent-heading">
    <div className="section-heading"><h2 id="overview-recent-heading">Recent orders</h2><div className="actions">
      <button onClick={recent.reload} disabled={recent.loading}>Refresh recent orders</button><Link to="/orders">View all orders →</Link></div></div>
    <p className="small muted">Open an order for authorized patient and clinical details.</p>
    <State loading={recent.loading} error={recent.error} empty={!recent.data?.items.length} />
    {recent.data && recent.data.items.length > 0 && <Table rows={recent.data.items} caption="Recent laboratory orders" columns={[
      { key: "order_code", label: "Order" }, { key: "priority", label: "Priority", badge: true },
      { key: "status", label: "Status", badge: true }, { key: "order_date", label: "Requested", date: true },
    ]} actions={row => <Link to={`/orders/${row.order_id}`}>Open order</Link>} />}
  </section>;
}

export function Dashboard() {
  const { user, can } = useAuth();
  const [refresh, setRefresh] = useState(0);
  const permissions = `${user?.user_id}:${user?.roles.join(",")}:${user?.permissions.join(",")}`;
  const actions = [
    { permissions: ["PATIENT_READ", "PATIENT_CREATE"], to: "/patients?new=1", label: "New patient" },
    { permissions: ["LAB_ORDER_CREATE"], to: "/orders/new", label: "New laboratory order" },
    { permissions: ["SPECIMEN_REGISTER", "SPECIMEN_READ", "LAB_ORDER_READ"], to: "/specimens", label: "Register specimen" },
    { permissions: ["LAB_RESULT_READ", "LAB_ORDER_READ"], to: "/results", label: "View results" },
    { permissions: ["REPORT_READ"], to: "/reports", label: "Browse reports" },
  ].filter(action => action.permissions.every(can));
  return <div className="dashboard-page page-shell">
    <Title title="Laboratory overview" eyebrow="DASHBOARD" description="Follow laboratory work from request to released report.">
      <button onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16} aria-hidden="true" /> Refresh overview</button>
    </Title>
    <section className="welcome overview-welcome"><div><p className="eyebrow">YOUR WORKSPACE</p>
      <h2>Welcome, {user?.staff?.first_name || user?.username}.</h2><p>See what needs attention and continue where your team left off.</p></div>
      {can("ANALYTICS_VIEW") && <Link className="button" to="/administration/analytics">Explore trends <ArrowUpRight size={16} aria-hidden="true" /></Link>}
    </section>
    <div key={`${permissions}:${refresh}`} className="overview-content">
      <Summary />
      <section className="card"><div className="section-heading"><h2>Quick actions</h2><span className="muted">Available for your role</span></div>
        {actions.length ? <div className="quick-actions">{actions.map(action => <Link className="button" key={action.to} to={action.to}>{action.label}<ArrowUpRight size={16} aria-hidden="true" /></Link>)}</div> :
          <p className="muted">No quick actions are available for your permissions.</p>}
      </section>
      {can("LAB_ORDER_READ") && <RecentOrders />}
      {(can("BLOCKCHAIN_STATUS_VIEW") || can("BLOCKCHAIN_EXPLORER_VIEW")) && <div className="overview-health">
        {can("BLOCKCHAIN_STATUS_VIEW") && <BlockchainQueue />}
        {can("BLOCKCHAIN_EXPLORER_VIEW") && <FabricHealth />}
      </div>}
    </div>
  </div>;
}
