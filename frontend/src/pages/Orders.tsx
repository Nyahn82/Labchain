import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const state = useResource<Page>(
    `/lab-orders?page=${page}&page_size=20&search=${encodeURIComponent(search)}${status ? "&status=" + status : ""}${priority ? "&priority=" + priority : ""}`,
  );
  return (
    <>
      <Title
        title={
          mode === "orders"
            ? "Laboratory orders"
            : mode === "specimens"
              ? "Specimen workspace"
              : "Result workspace"
        }
      >
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
              placeholder="Order code…"
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
  field("patient_id", "Patient", { lookup: patientLookup, required: true }),
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
  const navigate = useNavigate();
  return (
    <>
      <Title title="New laboratory order">
        <Link to="/orders">All orders</Link>
      </Title>
      <section className="card">
        <p>
          Select panels, individual tests, or both. Panel expansion and request
          provenance are handled by the laboratory service.
        </p>
        <Form
          fields={orderFields}
          submit="Create order"
          onSubmit={async (body) => {
            if (
              !(body.panel_ids as number[]).length &&
              !(body.test_ids as number[]).length
            )
              throw new Error("Select at least one panel or individual test.");
            const result = await api<Row>("/lab-orders", {
              method: "POST",
              body,
            });
            navigate(`/orders/${result.order_id}`);
          }}
        />
      </section>
    </>
  );
}
export function OrderDetail({
  tab = "overview",
}: {
  tab?: "overview" | "specimens" | "results" | "reports";
}) {
  return (
    <PermissionGuard permission="LAB_ORDER_READ">
      <OrderContent tab={tab} />
    </PermissionGuard>
  );
}
function OrderContent({ tab }: { tab: string }) {
  const { id } = useParams();
  const { can } = useAuth();
  const state = useResource<Order>(`/lab-orders/${id}`);
  const order = state.data;
  const [reason, setReason] = useState("");
  return (
    <>
      <Title title={order?.order_code || "Order details"}>
        <Link to="/orders">All orders</Link>
        {order && <Badge>{order.status}</Badge>}
      </Title>
      <State {...state} />
      {order && (
        <>
          <section className="card compact">
            <Details
              row={order}
              fields={["patient", "physician", "priority", "order_date"]}
            />
            <nav className="tabs" aria-label="Order workflow">
              <Link to={`/orders/${id}`}>Overview</Link>
              {can("SPECIMEN_READ") && (
                <Link to={`/orders/${id}/specimens`}>Specimens</Link>
              )}
              {can("LAB_RESULT_READ") && (
                <Link to={`/orders/${id}/results`}>Results</Link>
              )}
              {can("REPORT_READ") && (
                <Link to={`/orders/${id}/reports`}>Reports</Link>
              )}
            </nav>
          </section>
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
              <Specimens order={order} reload={state.reload} />
            </PermissionGuard>
          ) : tab === "results" ? (
            <PermissionGuard permission="LAB_RESULT_READ">
              <Results order={order} reload={state.reload} />
            </PermissionGuard>
          ) : (
            <PermissionGuard permission="REPORT_READ">
              <OrderReports order={order} />
            </PermissionGuard>
          )}
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
