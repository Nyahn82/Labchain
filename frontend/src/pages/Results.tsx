import { useState } from "react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useAuth } from "../auth/Auth";
import {
  Action,
  Badge,
  Dialog,
  Pagination,
  State,
  Table,
} from "../components/UI";
import { Form } from "../components/Form";
import { Details } from "../components/Details";
import type { Order, Page, Result, Row } from "../types/domain";
import { field } from "./resources";
export function Results({
  order,
  reload,
}: {
  order: Order;
  reload: () => void;
}) {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [edit, setEdit] = useState<{ item: Row; result?: Result }>();
  const state = useResource<Page<Result>>(
    `/lab-orders/${order.order_id}/results?page=${page}&page_size=20`,
  );
  const done = () => {
    state.reload();
    reload();
  };
  return (
    <>
      <section className="card">
        <h2>Laboratory results</h2>
        <p className="muted">
          Flags and reference context are calculated by the laboratory service.
          Reviewed and verified values cannot be edited.
        </p>
        <State {...state} empty={!state.data?.items.length} />
        {state.data && (
          <>
            <Table
              rows={state.data.items}
              columns={[
                { key: "test.test_name", label: "Test" },
                { key: "specimen.specimen_code", label: "Specimen" },
                { key: "result_value", label: "Result" },
                { key: "test.default_unit", label: "Unit" },
                {
                  key: "reference_range",
                  label: "Reference",
                  render: (r) => {
                    const range = r.reference_range as Row | null;
                    return range
                      ? String(
                          range.qualitative_normal ||
                            `${range.normal_low ?? "—"} – ${range.normal_high ?? "—"} ${range.unit || ""}`,
                        )
                      : "No matching range";
                  },
                },
                { key: "flag", label: "Flag", badge: true },
                { key: "status", label: "Status", badge: true },
              ]}
              actions={(row) =>
                order.status === "CANCELLED" ? (
                  <span>Cancelled order · read only</span>
                ) : (
                  <ResultActions
                    result={row as Result}
                    done={done}
                    onEdit={() => {
                      const item = order.items.find(
                        (i) => i.order_item_id === row.order_item_id,
                      );
                      if (item) setEdit({ item, result: row as Result });
                    }}
                  />
                )
              }
            />
            <Pagination page={page} total={state.data.total} onPage={setPage} />
          </>
        )}
      </section>
      {can("LAB_RESULT_ENTER") &&
        ["REQUESTED", "IN_PROGRESS"].includes(order.status) && (
          <section className="card">
            <h2>Enter a result</h2>
            <p>
              Select an unfinished order item. Existing drafts are edited from
              the results table above.
            </p>
            <Table
              rows={order.items.filter((i) =>
                ["REQUESTED", "IN_PROGRESS"].includes(String(i.status)),
              )}
              columns={[
                { key: "test.test_name", label: "Test" },
                { key: "order_item_id", label: "Item" },
                { key: "order_panel_id", label: "Panel request" },
                { key: "status", label: "Status", badge: true },
              ]}
              actions={(item) => (
                <button
                  disabled={
                    !!state.data?.items.some(
                      (r) => r.order_item_id === item.order_item_id,
                    )
                  }
                  onClick={() => setEdit({ item })}
                >
                  Enter result
                </button>
              )}
            />
          </section>
        )}
      {edit && (
        <Dialog
          title={edit.result ? "Edit draft result" : "Enter result"}
          onClose={() => setEdit(undefined)}
        >
          <ResultForm
            order={order}
            item={edit.item}
            result={edit.result}
            done={() => {
              setEdit(undefined);
              done();
            }}
          />
        </Dialog>
      )}
    </>
  );
}
export function ResultActions({
  result,
  done,
  onEdit,
}: {
  result: Result;
  done: () => void;
  onEdit: () => void;
}) {
  const { can } = useAuth();
  const path = `/results/${result.result_item_id}`;
  return (
    <>
      {result.status === "DRAFT" && can("LAB_RESULT_ENTER") && (
        <button onClick={onEdit}>Edit draft</button>
      )}
      {result.status === "DRAFT" && can("LAB_RESULT_REVIEW") && (
        <Action
          label="Review result"
          description={`Review ${String(result.test.test_name)}: ${result.result_value}. Reviewing makes this value immutable.`}
          run={() => api(path + "/review", { method: "POST" })}
          onDone={done}
        />
      )}{" "}
      {result.status === "REVIEWED" && can("LAB_RESULT_VERIFY") && (
        <Action
          label="Verify result"
          description={`Verify ${String(result.test.test_name)}: ${result.result_value}. Confirm the reviewed result is ready for reporting.`}
          run={() => api(path + "/verify", { method: "POST" })}
          onDone={done}
        />
      )}{" "}
      {result.status === "VERIFIED" && (
        <span className="muted">Verified · read only</span>
      )}
    </>
  );
}
export function ResultForm({
  order,
  item,
  result,
  done,
}: {
  order: Order;
  item: Row;
  result?: Result;
  done: () => void;
}) {
  const { can } = useAuth();
  const catalog = useResource<Row>(
    !result && can("LAB_MASTER_READ") ? `/lab/tests/${item.test_id}` : null,
  );
  const test = result?.test || catalog.data;
  const specimens = order.specimens.filter(
    (s) =>
      ["RECEIVED", "PROCESSED"].includes(s.specimen_status) &&
      s.mappings.some((m) => m.order_item_id === item.order_item_id),
  );
  if (!test)
    return (
      <>
        <State {...catalog} />
        {!can("LAB_MASTER_READ") && (
          <p>
            Laboratory catalog read access is required to retrieve this test’s
            result type.
          </p>
        )}
      </>
    );
  return (
    <>
      <Details
        row={test}
        fields={["test_name", "result_type", "default_unit"]}
      />
      {result && (
        <>
          <Badge>{result.flag}</Badge>
          <Details row={result} fields={["status", "encoded_at", "remarks"]} />
        </>
      )}
      <Form
        fields={[
          field("result_value", "Result value", {
            type:
              test.result_type === "NUMERIC"
                ? "decimal"
                : test.result_type === "TEXT"
                  ? "textarea"
                  : "text",
            required: true,
            max: 100,
            help:
              test.result_type === "NUMERIC"
                ? "Enter a decimal value. Precision is preserved."
                : "Enter the laboratory-approved result text.",
          }),
          field("specimen_id", "Specimen", {
            type: "select",
            options: specimens.map((s) => ({
              value: s.specimen_id,
              label: s.specimen_code,
            })),
          }),
          field("remarks", "Remarks", { type: "textarea" }),
        ]}
        initial={result || {}}
        onSubmit={async (body) => {
          await api(
            result
              ? `/results/${result.result_item_id}`
              : `/lab-order-items/${item.order_item_id}/result`,
            {
              method: result ? "PATCH" : "POST",
              body: {
                result_value: body.result_value,
                specimen_id: body.specimen_id ? Number(body.specimen_id) : null,
                remarks: body.remarks,
              },
            },
          );
          done();
        }}
      />
    </>
  );
}
