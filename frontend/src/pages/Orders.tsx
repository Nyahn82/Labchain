import { OrderedExaminations } from "../components/OrderedExaminations";
import { ClinicalCatalogBrowser, type CatalogSelection } from "../components/ClinicalCatalogBrowser";
import { useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import {
  Action,
  Badge,
  Dialog,
  Pagination,
  State,
  Table,
  Title,
} from "../components/UI";
import { choices, Form } from "../components/Form";
import { Details } from "../components/Details";
import type { Order, Page, Row } from "../types/domain";
import {
  field,
  patientLookup,
  physicianLookup,
  panelsLookup,
  testsLookup,
} from "./resources";
import { LaboratoryProgress } from "../components/LaboratoryProgress";
import { Specimens } from "./Specimens";
import { Results } from "./Results";
import { OrderReports } from "./Reports";
export function Orders({
  mode = "orders",
}: {
  mode?: "orders" | "specimens" | "results";
}) {
  return (
    <PermissionGuard
      permission={
        mode === "orders"
          ? "LAB_ORDER_READ"
          : mode === "specimens"
            ? "SPECIMEN_READ"
            : "LAB_RESULT_READ"
      }
    >
      <PermissionGuard permission="LAB_ORDER_READ">
        <OrderList mode={mode} />
      </PermissionGuard>
    </PermissionGuard>
  );
}
function OrderList({ mode }: { mode: string }) {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState(params.get("status") || "");
  const [priority, setPriority] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const state = useResource<Page>(
    `/lab-orders?page=${page}&page_size=20&search=${encodeURIComponent(search)}${status ? "&status=" + status : ""}${priority ? "&priority=" + priority : ""}${dateFrom ? "&date_from=" + dateFrom : ""}${dateTo ? "&date_to=" + dateTo : ""}`,
  );
  return (
    <>
      <Title
        eyebrow="LABORATORY WORKSPACE"
        description="Follow authorized requests through specimen handling, testing and report release."
        title={
          mode === "orders"
            ? "Laboratory orders"
            : mode === "specimens"
              ? "Specimen workspace"
              : "Result workspace"
        }
      >
        <button onClick={state.reload} disabled={state.loading}>Refresh orders</button>
        {can("LAB_ORDER_CREATE") && (
          <Link className="button primary" to="/orders/new">
            New laboratory order
          </Link>
        )}
      </Title>
      {mode !== "orders" && (
        <p className="intro">
          Choose an order to work with its {mode}. Each record remains linked to
          its original request.
        </p>
      )}
      <section className="card">
        <div className="toolbar">
          <label>
            Search orders
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Order code, patient code or name…"
            />
          </label>
          <label>
            Status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {["REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"].map(
                (v) => (
                  <option key={v}>{v}</option>
                ),
              )}
            </select>
          </label>
          <label>
            Priority
            <select
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All priorities</option>
              {["ROUTINE", "STAT", "URGENT"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>Requested from<input type="date" value={dateFrom} max={dateTo || undefined} onChange={e => { setDateFrom(e.target.value); setPage(1); }} /></label>
          <label>Requested to<input type="date" value={dateTo} min={dateFrom || undefined} onChange={e => { setDateTo(e.target.value); setPage(1); }} /></label>
          <button onClick={() => { setSearch(""); setStatus(""); setPriority(""); setDateFrom(""); setDateTo(""); setPage(1); }}>Clear filters</button>
        </div>
        <State {...state} empty={!state.data?.items.length} />
        {state.data && (
          <>
            <Table
              rows={state.data.items}
              columns={[
                { key: "order_code", label: "Order" },
                { key: "patient", label: "Patient" },
                { key: "physician", label: "Physician" },
                { key: "priority", label: "Priority", badge: true },
                { key: "status", label: "Status", badge: true },
                { key: "order_date", label: "Requested", date: true },
              ]}
              actions={(r) => (
                <Link
                  to={`/orders/${r.order_id}${mode === "orders" ? "" : "/" + mode}`}
                >
                  Open {mode === "orders" ? "order" : mode}
                </Link>
              )}
            />
            <Pagination page={page} total={state.data.total} onPage={setPage} />
          </>
        )}
      </section>
    </>
  );
}
export const orderFields = [
  field("patient_id", "Patient", { lookup: patientLookup, required: true, group: "01 · Patient and request" }),
  field("physician_id", "Requesting physician", { lookup: physicianLookup }),
  field("priority", "Priority", {
    type: "select",
    options: choices("ROUTINE", "STAT", "URGENT"),
    required: true,
    default: "ROUTINE",
  }),
  field("request_reason", "Request reason", { max: 150 }),
  field("clinical_notes", "Clinical notes", { type: "textarea" }),
  field("diagnosis", "Clinician-provided diagnosis", {
    type: "textarea",
    help: "Enter only information supplied by the clinician.",
  }),
  field("panel_ids", "Panels", { type: "multi", lookup: panelsLookup }),
  field("test_ids", "Individual tests", { type: "multi", lookup: testsLookup }),
];
export function CreateOrder() {
  return (
    <PermissionGuard permission="LAB_ORDER_CREATE">
      <OrderForm />
    </PermissionGuard>
  );
}
function OrderForm() {
  const [selection, setSelection] = useState<CatalogSelection>({test_ids: [], panel_ids: []});
  const [params] = useSearchParams();
  const candidate = params.get("patient_id") || "";
  const patientId = /^\d+$/.test(candidate) && Number.isSafeInteger(Number(candidate)) && Number(candidate) > 0 ? Number(candidate) : undefined;
  const navigate = useNavigate();
  return (
    <>
      <Title title="New laboratory order">
        <Link to="/orders">All orders</Link>
      </Title>
      <section className="card order-entry">
        <Form
          fields={orderFields.filter(f => !["panel_ids", "test_ids"].includes(f.name))}
          initial={patientId ? { patient_id: patientId } : {}}
          submit="Create order"
          onSubmit={async (body) => {
            if (
              !selection.panel_ids.length &&
              !selection.test_ids.length
            )
              throw new Error("Select at least one panel or individual test.");
            const result = await api<Row>("/lab-orders", {
              method: "POST",
              body: { ...body, ...selection },
            });
            navigate(`/orders/${result.order_id}`);
          }}
        >
          <div className="wide"><ClinicalCatalogBrowser selection={selection} onChange={setSelection} /></div>
        </Form>
      </section>
    </>
  );
}
export function OrderDetail({
  tab = "overview",
}: {
  tab?: "overview" | "specimens" | "results" | "reports";
}) {
  const { id } = useParams();
  return (
    <PermissionGuard permission="LAB_ORDER_READ">
      <OrderContent key={`${id}:${tab}`} tab={tab} />
    </PermissionGuard>
  );
}
function OrderContent({ tab }: { tab: string }) {
  const { id } = useParams();
  const { can } = useAuth();
  const state = useResource<Order>(`/lab-orders/${id}`);
  const order = state.data;
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const changed = () => { setNotice("Laboratory record saved. Workspace refreshed."); state.reload(); };
  return (
    <>
      <Title title={order?.order_code || "Order details"}>
        <Link to="/orders">All orders</Link>
        <button onClick={state.reload} disabled={state.loading}>Refresh workspace</button>
        {order && <Badge>{order.status}</Badge>}
      </Title>
      {notice && <p role="status" className="success">{notice}</p>}
      <State {...state} />
      {order && (
        <>
          <section className="card compact">
            <p><strong>Patient code: {String(order.patient.patient_code || "Unavailable")}</strong>
              {can("PATIENT_READ") && order.patient.patient_id != null && <> · <Link to={`/patients/${order.patient.patient_id}`}>Open patient record</Link></>}</p>
            <Details
              row={order}
              fields={["patient", "physician", "priority", "order_date"]}
            />
            <nav className="tabs" aria-label="Order workflow">
              <NavLink end to={`/orders/${id}`}>Overview</NavLink>
              {can("SPECIMEN_READ") && (
                <NavLink to={`/orders/${id}/specimens`}>Specimens</NavLink>
              )}
              {can("LAB_RESULT_READ") && (
                <NavLink to={`/orders/${id}/results`}>Results</NavLink>
              )}
              {can("REPORT_READ") && (
                <NavLink to={`/orders/${id}/reports`}>Reports</NavLink>
              )}
            </nav>
          </section>
          {tab === "overview" ? <LaboratoryProgress order={order} /> : <details className="workspace-reference"><summary>Workflow status and guidance</summary><LaboratoryProgress order={order} /></details>}
          {tab === "overview" && <OrderedExaminations items={order.items} />}
          {tab === "overview" ? (
            <>
              <section className="card">
                <h2>Request information</h2>
                <Details
                  row={order}
                  fields={[
                    "request_reason",
                    "clinical_notes",
                    "diagnosis",
                    "created_at",
                  ]}
                />
                {can("LAB_ORDER_CANCEL") &&
                  ["REQUESTED", "IN_PROGRESS"].includes(order.status) && (
                    <Action
                      label="Cancel order"
                      danger
                      valid={!!reason.trim()}
                      description="Cancel this laboratory order. Existing history is retained. Provide a reason."
                      run={() =>
                        api(`/lab-orders/${id}/cancel`, {
                          method: "POST",
                          body: { reason },
                        })
                      }
                      onDone={() => {
                        setReason("");
                        state.reload();
                      }}
                    >
                      <label>
                        Cancellation reason
                        <textarea
                          required
                          maxLength={500}
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                        />
                      </label>
                    </Action>
                  )}
              </section>
              <section className="card">
                <h2>Requested panels</h2>
                <State empty={!order.panels.length} />
                <Table
                  rows={order.panels}
                  columns={[
                    { key: "panel.panel_name", label: "Panel" },
                    { key: "status", label: "Status", badge: true },
                  ]}
                />
                <h2>Requested test items</h2>
                <Table
                  rows={order.items}
                  columns={[
                    { key: "test.test_name", label: "Test" },
                    {
                      key: "order_panel_id",
                      label: "Request source",
                      render: (r) =>
                        r.order_panel_id
                          ? String(
                              (
                                order.panels.find(
                                  (p) => p.order_panel_id === r.order_panel_id,
                                )?.panel as Row
                              )?.panel_name ||
                                `Panel request #${r.order_panel_id}`,
                            )
                          : "Individual request",
                    },
                    { key: "status", label: "Status", badge: true },
                  ]}
                />
              </section>
              {can("PAYMENT_READ") && <Payments order={order} />}{" "}
              {can("SPECIMEN_READ") && (
                <section className="card">
                  <h2>Specimens</h2>
                  <State empty={!order.specimens.length} />
                  <Table
                    rows={order.specimens}
                    columns={[
                      { key: "specimen_code", label: "Specimen" },
                      { key: "sample_type.sample_name", label: "Sample type" },
                      { key: "specimen_status", label: "Status", badge: true },
                    ]}
                    actions={(r) => (
                      <Link to={`/specimens/${r.specimen_id}`}>Details</Link>
                    )}
                  />
                  <Link to={`/orders/${id}/specimens`}>
                    Open specimen workflow →
                  </Link>
                </section>
              )}
            </>
          ) : tab === "specimens" ? (
            <PermissionGuard permission="SPECIMEN_READ">
              <Specimens order={order} reload={changed} />
            </PermissionGuard>
          ) : tab === "results" ? (
            <PermissionGuard permission="LAB_RESULT_READ">
              <Results order={order} reload={changed} />
            </PermissionGuard>
          ) : (
            <PermissionGuard permission="REPORT_READ">
              <OrderReports order={order} />
            </PermissionGuard>
          )}
          {tab !== "overview" && <details className="workspace-reference"><summary>Examination definitions and specimen requirements ({order.items.length})</summary><OrderedExaminations items={order.items} /></details>}
        </>
      )}
    </>
  );
}
function Payments({ order }: { order: Order }) {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const state = useResource<Page>(
    `/lab-orders/${order.order_id}/payments?page=${page}&page_size=20`,
  );
  return (
    <section className="card">
      <div className="section-heading">
        <h2>Payment history</h2>
        {can("PAYMENT_RECORD") && (
          <button onClick={() => setOpen(true)}>Record payment</button>
        )}
      </div>
      <p className="muted">
        Entries are append-only. Previous records remain visible.
      </p>
      <State {...state} empty={!state.data?.items.length} />
      {state.data && (
        <>
          <Table
            rows={state.data.items}
            columns={[
              { key: "payment_status", label: "Status", badge: true },
              { key: "amount", label: "Amount" },
              { key: "payment_method", label: "Method" },
              { key: "reference_number", label: "Reference" },
              { key: "recorded_at", label: "Recorded", date: true },
            ]}
          />
          <Pagination page={page} total={state.data.total} onPage={setPage} />
        </>
      )}
      {open && (
        <Dialog title="Record payment" onClose={() => setOpen(false)}>
          <Form
            fields={[
              field("payment_status", "Payment status", {
                type: "select",
                required: true,
                options: choices(
                  "PENDING",
                  "PAID",
                  "FREE",
                  "WAIVED",
                  "SUBSIDIZED",
                ),
              }),
              field("amount", "Amount", {
                type: "decimal",
                help: "Decimal amount, for example 125.00",
              }),
              field("payment_method", "Payment method"),
              field("reference_number", "Reference number"),
            ]}
            onSubmit={async (body) => {
              await api(`/lab-orders/${order.order_id}/payments`, {
                method: "POST",
                body,
              });
              setOpen(false);
              state.reload();
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
