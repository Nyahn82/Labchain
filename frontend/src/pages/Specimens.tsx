import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import {
  Action,
  Alert,
  Badge,
  Dialog,
  State,
  Table,
  Title,
} from "../components/UI";
import { Lookup } from "../components/Form";
import { Details } from "../components/Details";
import type { Order, Row, Specimen } from "../types/domain";
import { lookup, sampleLookup } from "./resources";
export function Specimens({
  order,
  reload,
}: {
  order: Order;
  reload: () => void;
}) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <section className="card">
      <div className="section-heading">
        <h2>Order specimens</h2>
        {can("SPECIMEN_REGISTER") &&
          ["REQUESTED", "IN_PROGRESS"].includes(order.status) && (
            <button onClick={() => setOpen(true)}>Register specimen</button>
          )}
      </div>
      <p className="muted">
        Rejected specimens remain in this history. Register a new specimen for
        recollection.
      </p>
      <State empty={!order.specimens.length} />
      <Table
        rows={order.specimens}
        columns={[
          { key: "specimen_code", label: "Specimen" },
          { key: "sample_type.sample_name", label: "Sample type" },
          { key: "specimen_status", label: "Status", badge: true },
          { key: "collected_at", label: "Collected", date: true },
          { key: "received_at", label: "Received", date: true },
        ]}
        actions={(r) => (
          <Link to={`/specimens/${r.specimen_id}`}>Open specimen</Link>
        )}
      />
      {open && (
        <Dialog title="Register specimen" onClose={() => setOpen(false)}>
          <RegisterSpecimen
            order={order}
            done={() => {
              setOpen(false);
              reload();
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
export function RegisterSpecimen({
  order,
  done,
}: {
  order: Order;
  done: () => void;
}) {
  const [sample, setSample] = useState<unknown>(null);
  const [ids, setIds] = useState<number[]>([]);
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const items = order.items.filter(
    (i) => !["CANCELLED", "COMPLETED"].includes(String(i.status)),
  );
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(undefined);
        try {
          await api(`/lab-orders/${order.order_id}/specimens`, {
            method: "POST",
            body: {
              sample_type_id: sample,
              order_item_ids: ids,
              remarks: remarks || null,
            },
          });
          done();
        } catch (e) {
          setError(e as Error);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Alert error={error} />
      <fieldset disabled={busy}>
        <Lookup
          spec={sampleLookup}
          label="Sample type"
          required
          value={sample}
          onChange={setSample}
        />
        <fieldset>
          <legend>Map order items</legend>
          <p className="muted">
            Choose items from this order. Sample compatibility is validated by
            the server.
          </p>
          {items.map((item) => (
            <label className="check" key={String(item.order_item_id)}>
              <input
                type="checkbox"
                checked={ids.includes(Number(item.order_item_id))}
                onChange={(e) =>
                  setIds(
                    e.target.checked
                      ? [...ids, Number(item.order_item_id)]
                      : ids.filter((id) => id !== item.order_item_id),
                  )
                }
              />
              {String((item.test as Row).test_name)} · Item #
              {String(item.order_item_id)}{" "}
              {item.order_panel_id ? "(panel request)" : "(individual)"}
            </label>
          ))}
        </fieldset>
        <label>
          Remarks
          <textarea
            value={remarks}
            maxLength={16000}
            onChange={(e) => setRemarks(e.target.value)}
          />
        </label>
        <button className="primary" disabled={!sample || !ids.length || busy}>
          {busy ? "Registering…" : "Register specimen"}
        </button>
      </fieldset>
    </form>
  );
}
export function SpecimenDetail() {
  return (
    <PermissionGuard permission="SPECIMEN_READ">
      <SpecimenContent />
    </PermissionGuard>
  );
}
function SpecimenContent() {
  const { id } = useParams();
  const { can } = useAuth();
  const state = useResource<Specimen>(`/specimens/${id}`);
  const order = useResource<Order>(
    state.data && can("LAB_ORDER_READ")
      ? `/lab-orders/${state.data.order_id}`
      : null,
  );
  return (
    <>
      <Title title={state.data?.specimen_code || "Specimen details"}>
        {state.data && (
          <Link to={`/orders/${state.data.order_id}/specimens`}>
            Order specimens
          </Link>
        )}
      </Title>
      <State {...state} />
      {state.data && (
        <>
          <section className="card">
            <Badge>{state.data.specimen_status}</Badge>
            <Details
              row={state.data}
              fields={[
                "sample_type.sample_name",
                "collected_at",
                "received_at",
                "created_at",
                "remarks",
              ]}
            />
            <State loading={order.loading} error={order.error} />
            <SpecimenActions
              specimen={state.data}
              orderOpen={
                !!order.data &&
                ["REQUESTED", "IN_PROGRESS"].includes(order.data.status)
              }
              done={state.reload}
            />
            <h2>Mapped order items</h2>
            <Table
              rows={state.data.mappings}
              columns={[
                { key: "order_item_id", label: "Item" },
                { key: "order_item.test.test_name", label: "Test" },
                { key: "order_item.status", label: "Status", badge: true },
              ]}
            />
          </section>
          <section className="card">
            <h2>Rejection & recollection history</h2>
            <State empty={!state.data.rejections.length} />
            <Table
              rows={state.data.rejections}
              columns={[
                { key: "reason.reason_name", label: "Reason" },
                { key: "details", label: "Details" },
                {
                  key: "recollection_required",
                  label: "Recollection",
                  render: (r) =>
                    r.recollection_required ? "Required" : "Not required",
                },
                { key: "rejected_at", label: "Rejected", date: true },
              ]}
            />
            {state.data.specimen_status === "REJECTED" && (
              <Link to={`/orders/${state.data.order_id}/specimens`}>
                View all specimens and register recollection →
              </Link>
            )}
          </section>
        </>
      )}
    </>
  );
}
export function SpecimenActions({
  specimen,
  orderOpen,
  done,
}: {
  specimen: Specimen;
  orderOpen: boolean;
  done: () => void;
}) {
  const { can } = useAuth();
  const [reason, setReason] = useState<unknown>(null);
  const [details, setDetails] = useState("");
  const [recollection, setRecollection] = useState(true);
  const path = `/specimens/${specimen.specimen_id}`;
  return (
    <div className="actions">
      {orderOpen &&
        specimen.specimen_status === "PENDING" &&
        can("SPECIMEN_COLLECT") && (
          <Action
            label="Collect specimen"
            description="Record that this specimen has been collected."
            run={() => api(path + "/collect", { method: "POST" })}
            onDone={done}
          />
        )}{" "}
      {orderOpen &&
        specimen.specimen_status === "COLLECTED" &&
        can("SPECIMEN_RECEIVE") && (
          <Action
            label="Receive specimen"
            description="Record receipt of this specimen in the laboratory."
            run={() => api(path + "/receive", { method: "POST" })}
            onDone={done}
          />
        )}{" "}
      {["COLLECTED", "RECEIVED"].includes(specimen.specimen_status) &&
        can("SPECIMEN_REJECT") && (
          <Action
            label="Reject specimen"
            danger
            description="Record a specimen rejection. This specimen remains in the order history."
            valid={!!reason}
            run={() =>
              api(path + "/reject", {
                method: "POST",
                body: {
                  rejection_reason_id: reason,
                  details: details || null,
                  recollection_required: recollection,
                },
              })
            }
            onDone={done}
          >
            <Lookup
              spec={lookup(
                "/lab/rejection-reasons",
                "rejection_reason_id",
                "reason_name",
                "REJECTION_REASON_MANAGE",
              )}
              label="Rejection reason"
              required
              value={reason}
              onChange={setReason}
            />
            <label>
              Rejection details
              <textarea
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                maxLength={16000}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={recollection}
                onChange={(e) => setRecollection(e.target.checked)}
              />
              Recollection required
            </label>
          </Action>
        )}
    </div>
  );
}
