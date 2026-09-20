import { Link } from "react-router-dom";
import { ArrowUpRight, Users, ClipboardList, FileText } from "lucide-react";
import { useAuth } from "../auth/Auth";
import { useResource } from "../api/useResource";
import type { Page } from "../types/domain";
import { State, Table, Title } from "../components/UI";
function Metric({
  title,
  path,
  to,
  icon: Icon,
}: {
  title: string;
  path: string;
  to: string;
  icon: typeof Users;
}) {
  const { data, loading, error } = useResource<Page>(path);
  return (
    <Link className="card metric" to={to}>
      <div>
        <span className="metric-icon">
          <Icon size={22} />
        </span>
        <ArrowUpRight size={18} />
      </div>
      <p>{title}</p>
      {error ? (
        <span>Unavailable</span>
      ) : (
        <strong>{loading ? "…" : (data?.total ?? "—")}</strong>
      )}
      <small>View records</small>
    </Link>
  );
}
export function Dashboard() {
  const { user, can } = useAuth();
  const recent = useResource<Page>(
    can("LAB_ORDER_READ") ? "/lab-orders?page=1&page_size=5" : null,
  );
  return (
    <>
      <Title title="Laboratory overview" />
      <section className="welcome">
        <div>
          <p className="eyebrow">A CLEAR VIEW OF YOUR DAY</p>
          <h2>Welcome, {user?.staff?.first_name || user?.username}.</h2>
          <p>Manage requests, follow specimens, and keep results moving.</p>
        </div>
        <ClipboardList size={64} strokeWidth={1} />
      </section>
      <div className="metrics">
        {can("PATIENT_READ") && (
          <Metric
            title="Registered patients"
            path="/patients?page_size=1"
            to="/patients"
            icon={Users}
          />
        )}{" "}
        {can("LAB_ORDER_READ") && (
          <>
            <Metric
              title="Laboratory orders"
              path="/lab-orders?page_size=1"
              to="/orders"
              icon={ClipboardList}
            />
            <Metric
              title="In-progress orders"
              path="/lab-orders?page_size=1&status=IN_PROGRESS"
              to="/orders"
              icon={ClipboardList}
            />
          </>
        )}
        {can("REPORT_READ") && (
          <Metric
            title="Reports"
            path="/reports?page_size=1"
            to="/reports"
            icon={FileText}
          />
        )}
      </div>
      <section className="card">
        <div className="section-heading">
          <h2>Quick actions</h2>
          <span className="muted">Your everyday workflows</span>
        </div>
        <div className="quick-actions">
          {[
            ["PATIENT_CREATE", "/patients?new=1", "New patient"],
            ["LAB_ORDER_CREATE", "/orders/new", "New laboratory order"],
            ["SPECIMEN_REGISTER", "/specimens", "Register specimen"],
            ["LAB_RESULT_READ", "/results", "View results"],
            ["REPORT_READ", "/reports", "Browse reports"],
          ]
            .filter(([p]) => can(p))
            .map(([, to, label]) => (
              <Link className="button" key={to} to={to}>
                {label}
                <ArrowUpRight size={16} />
              </Link>
            ))}
        </div>
      </section>
      {can("LAB_ORDER_READ") && (
        <section className="card">
          <div className="section-heading">
            <h2>Recent orders</h2>
            <Link to="/orders">View all orders →</Link>
          </div>
          <State
            loading={recent.loading}
            error={recent.error}
            empty={!recent.data?.items.length}
          />
          {recent.data && (
            <Table
              rows={recent.data.items}
              columns={[
                { key: "order_code", label: "Order" },
                { key: "patient", label: "Patient" },
                { key: "priority", label: "Priority", badge: true },
                { key: "status", label: "Status", badge: true },
                { key: "order_date", label: "Requested", date: true },
              ]}
              actions={(r) => (
                <Link to={`/orders/${r.order_id}`}>Open order</Link>
              )}
            />
          )}
        </section>
      )}
    </>
  );
}
