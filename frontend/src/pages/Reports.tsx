import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, pdf } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import {
  Action,
  Alert,
  Badge,
  Dialog,
  Pagination,
  State,
  Table,
  Title,
} from "../components/UI";
import { choices, Form } from "../components/Form";
import { Details } from "../components/Details";
import type { Order, Page, Report, Row } from "../types/domain";
import { safeUrl } from "../utils/display";
import { field, lookup } from "./resources";
const reportColumns = [
  { key: "report_code", label: "Report" },
  { key: "version_no", label: "Version" },
  { key: "report_status", label: "Status", badge: true },
  { key: "generated_at", label: "Generated", date: true },
];
const generateFields = [
  field("template_id", "Report template", {
    lookup: lookup(
      "/report-templates",
      "template_id",
      "template_name",
      "REPORT_TEMPLATE_READ",
    ),
    help: "Optional. The backend resolves the default template when omitted.",
  }),
  field("remarks", "Remarks", { type: "textarea" }),
];
export function Reports() {
  return (
    <PermissionGuard permission="REPORT_READ">
      <ReportList />
    </PermissionGuard>
  );
}
function ReportList() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const state = useResource<Page>(
    `/reports?page=${page}&page_size=20&search=${encodeURIComponent(search)}${status ? "&status=" + status : ""}`,
  );
  return (
    <>
      <Title title="Laboratory reports" />
      <section className="card">
        <div className="toolbar">
          <label>
            Search reports
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
            Report status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {["GENERATED", "APPROVED", "RELEASED", "REVOKED"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          Generate reports from a completed order’s Reports tab.
        </p>
        <State {...state} empty={!state.data?.items.length} />
        {state.data && (
          <>
            <Table
              rows={state.data.items}
              columns={reportColumns}
              actions={(r) => (
                <Link to={`/reports/${r.report_id}`}>Open report</Link>
              )}
            />
            <Pagination page={page} total={state.data.total} onPage={setPage} />
          </>
        )}
      </section>
    </>
  );
}
export function OrderReports({ order }: { order: Order }) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const state = useResource<Page>(
    `/lab-orders/${order.order_id}/reports?page=${page}&page_size=20`,
  );
  return (
    <section className="card">
      <div className="section-heading">
        <h2>Report versions</h2>
        {order.status === "COMPLETED" && can("REPORT_GENERATE") && (
          <button onClick={() => setOpen(true)}>Generate report</button>
        )}
      </div>
      <State {...state} empty={!state.data?.items.length} />
      {state.data && (
        <>
          <Table
            rows={state.data.items}
            columns={reportColumns}
            actions={(r) => (
              <Link to={`/reports/${r.report_id}`}>
                Open version {String(r.version_no)}
              </Link>
            )}
          />
          <Pagination page={page} total={state.data.total} onPage={setPage} />
        </>
      )}
      {open && (
        <Dialog title="Generate report" onClose={() => setOpen(false)}>
          <p>Create an official snapshot from verified results.</p>
          <Form
            fields={generateFields}
            submit="Generate report"
            onSubmit={async (body) => {
              const report = await api<Report>(
                `/lab-orders/${order.order_id}/reports`,
                { method: "POST", body },
              );
              navigate(`/reports/${report.report_id}`);
            }}
          />
        </Dialog>
      )}
    </section>
  );
}
export function ReportDetail() {
  return (
    <PermissionGuard permission="REPORT_READ">
      <ReportContent />
    </PermissionGuard>
  );
}
function ReportContent() {
  const { id } = useParams();
  const state = useResource<Report>(`/reports/${id}`);
  return (
    <>
      <Title title={state.data?.report_code || "Report details"}>
        <Link to="/reports">All reports</Link>
        {state.data && <Badge>{state.data.report_status}</Badge>}
      </Title>
      <State {...state} />
      {state.data && (
        <>
          <section className="card">
            <div className="section-heading">
              <h2>Version {state.data.version_no}</h2>
              <Link to={`/orders/${state.data.order_id}/reports`}>
                Order & version history →
              </Link>
            </div>
            {state.data.supersedes_report_id != null && (
              <p>
                Revises{" "}
                <Link to={`/reports/${state.data.supersedes_report_id}`}>
                  report #{String(state.data.supersedes_report_id)}
                </Link>
                .
              </p>
            )}
            <Details
              row={state.data}
              fields={[
                "patient_snapshot.patient_name",
                "patient_snapshot.patient_code",
                "patient_snapshot.physician_name",
                "generated_at",
                "approved_at",
                "released_at",
                "revoked_at",
                "revocation_reason",
                "remarks",
              ]}
            />
            <ReportActions report={state.data} done={state.reload} />
          </section>
          <section className="card">
            <h2>Official result snapshot</h2>
            <State empty={!state.data.result_snapshots.length} />
            <Table
              rows={state.data.result_snapshots}
              columns={[
                { key: "section_name_snapshot", label: "Section" },
                { key: "test_name_snapshot", label: "Test" },
                { key: "result_value_snapshot", label: "Result" },
                { key: "unit_snapshot", label: "Unit" },
                { key: "reference_range_snapshot", label: "Reference" },
                { key: "flag_snapshot", label: "Flag", badge: true },
              ]}
            />
          </section>
          <section className="card">
            <h2>Signatories</h2>
            <State empty={!state.data.signatories.length} />
            <Table
              rows={state.data.signatories}
              columns={[
                { key: "staff_name", label: "Staff" },
                { key: "signatory_type", label: "Capacity" },
                { key: "sort_order", label: "Order" },
                { key: "signed_at", label: "Signed", date: true },
              ]}
            />
          </section>
          {["RELEASED", "REVOKED"].includes(state.data.report_status) && (
            <Verification id={id!} />
          )}
        </>
      )}
    </>
  );
}
export function ReportActions({
  report,
  done,
}: {
  report: Report;
  done: () => void;
}) {
  const { can, user } = useAuth();
  const navigate = useNavigate();
  const [modal, setModal] = useState<"assign" | "revise" | null>(null);
  const [reason, setReason] = useState("");
  const [copies, setCopies] = useState(1);
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const path = `/reports/${report.report_id}`;
  async function download() {
    setBusy(true);
    setError(undefined);
    try {
      await pdf(
        path + "/pdf",
        `${report.report_code}-v${report.version_no}.pdf`,
      );
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Alert error={error} />
      <div className="actions">
        {report.report_status === "GENERATED" && (
          <>
            {can("SIGNATORY_MANAGE") && (
              <button onClick={() => setModal("assign")}>
                Assign signatory
              </button>
            )}
            {can("REPORT_SIGN") &&
              report.signatories
                .filter(
                  (s) =>
                    !s.signed_at &&
                    (s.profile as Row)?.staff_id === user?.staff?.staff_id,
                )
                .map((s) => (
                  <Action
                    key={String(s.report_signatory_id)}
                    label={`Sign as ${String(s.signatory_type).replaceAll("_", " ")}`}
                    description="Sign this report using your assigned staff signatory profile."
                    run={() =>
                      api(path + "/sign", {
                        method: "POST",
                        body: { report_signatory_id: s.report_signatory_id },
                      })
                    }
                    onDone={done}
                  />
                ))}
            {can("REPORT_APPROVE") &&
              report.signatories.length > 0 &&
              report.signatories.every((s) => s.signed_at) && (
                <Action
                  label="Approve report"
                  description="Approve this signed report snapshot for release."
                  run={() => api(path + "/approve", { method: "POST" })}
                  onDone={done}
                />
              )}
          </>
        )}
        {report.report_status === "APPROVED" && can("REPORT_RELEASE") && (
          <Action
            label="Release report"
            description="Release this approved report and its official PDF. Authorized patients may then access it."
            run={() => api(path + "/release", { method: "POST" })}
            onDone={done}
          />
        )}{" "}
        {["RELEASED", "REVOKED"].includes(report.report_status) && (
          <>
            {can("REPORT_DOWNLOAD") && (
              <button disabled={busy} onClick={download}>
                {busy ? "Downloading…" : "Download PDF"}
              </button>
            )}
            {can("REPORT_REVISE") && (
              <button onClick={() => setModal("revise")}>Revise report</button>
            )}
          </>
        )}
        {report.report_status === "RELEASED" && (
          <>
            {can("REPORT_PRINT") && (
              <Action
                label="Print PDF"
                description="Record the requested print copies and download the authenticated PDF. Open the downloaded PDF and print that number of copies."
                valid={Number.isInteger(copies) && copies >= 1 && copies <= 20}
                run={() =>
                  pdf(
                    path + "/print",
                    `${report.report_code}-print.pdf`,
                    true,
                    { copies },
                  )
                }
                onDone={done}
              >
                <label>
                  Copies
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={copies}
                    onChange={(e) => setCopies(Number(e.target.value))}
                  />
                </label>
              </Action>
            )}
            {can("REPORT_REVOKE") && (
              <Action
                label="Revoke report"
                danger
                valid={!!reason.trim()}
                description="Revoke this released report. Its history remains available and integrity verification will show it as revoked."
                run={() =>
                  api(path + "/revoke", { method: "POST", body: { reason } })
                }
                onDone={done}
              >
                <label>
                  Revocation reason
                  <textarea
                    required
                    value={reason}
                    maxLength={16000}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
              </Action>
            )}
          </>
        )}
      </div>
      {modal && (
        <Dialog
          title={modal === "assign" ? "Assign signatory" : "Revise report"}
          onClose={() => setModal(null)}
        >
          {modal === "assign" ? (
            <Form
              fields={[
                field("signatory_id", "Signatory profile", {
                  lookup: lookup(
                    "/signatories",
                    "signatory_id",
                    undefined,
                    "SIGNATORY_READ",
                  ),
                  required: true,
                }),
                field("signatory_type", "Signing capacity", {
                  type: "select",
                  required: true,
                  options: choices(
                    "LAB_IN_CHARGE",
                    "MEDICAL_TECHNOLOGIST",
                    "PATHOLOGIST",
                  ),
                }),
                field("sort_order", "Sort order", {
                  type: "number",
                  default: 1,
                  required: true,
                }),
              ]}
              submit="Assign signatory"
              onSubmit={async (body) => {
                await api(path + "/signatories", { method: "POST", body });
                setModal(null);
                done();
              }}
            />
          ) : (
            <>
              <p>
                Create a new report version. This preserves the existing report
                and starts a new approval cycle.
              </p>
              <Form
                fields={generateFields}
                submit="Create revised version"
                onSubmit={async (body) => {
                  const next = await api<Report>(path + "/revise", {
                    method: "POST",
                    body,
                  });
                  setModal(null);
                  navigate(`/reports/${next.report_id}`);
                }}
              />
            </>
          )}
        </Dialog>
      )}
    </>
  );
}
function Verification({ id }: { id: string }) {
  const state = useResource<Row>(`/reports/${id}/verification`);
  return (
    <section className="card">
      <h2>Report integrity verification</h2>
      <State {...state} />
      {state.data && (
        <>
          <Badge>{state.data.verification_status}</Badge>
          <Details
            row={state.data}
            fields={["report_hash", "created_at", "revoked_at"]}
          />
          {safeUrl(String(state.data.verification_url)) && (
            <a
              href={safeUrl(String(state.data.verification_url))!}
              target="_blank"
              rel="noopener noreferrer"
            >
              {String(state.data.verification_url)}
            </a>
          )}
        </>
      )}
    </section>
  );
}
