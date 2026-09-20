import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { Details } from "../../components/Details";
import { Dialog, Title, Table } from "../../components/UI";
import { PatientMessage } from "./Shared";
import type {
  PatientReport as Report,
  PatientResult,
} from "../../types/patient";
export const flagLabels: Record<string, string> = {
  NORMAL: "Within reference range",
  LOW: "Low",
  HIGH: "High",
  CRITICAL_LOW: "Critical low",
  CRITICAL_HIGH: "Critical high",
  ABNORMAL: "Outside reference range",
};
export function PatientFlag({ flag }: { flag: string | null }) {
  return (
    <span
      className={"badge " + (flag || "").toLowerCase().replaceAll("_", "-")}
    >
      {flag ? flagLabels[flag] || "Not available" : "Not provided"}
    </span>
  );
}
export function PatientReport() {
  const { reportId } = useParams();
  const state = useResource<Report>(
    `/patient/reports/${encodeURIComponent(reportId!)}`,
  );
  return (
    <>
      <Title
        title={state.data?.report_code || "Your report"}
        eyebrow="LABORATORY REPORT"
      >
        <Link to="/patient/reports">All reports</Link>
      </Title>
      <PatientMessage error={state.error} context="report" />
      {state.loading ? (
        <p role="status">Loading your report…</p>
      ) : (
        state.data && (
          <>
            <section className="card">
              <h2>Report information</h2>
              <Details
                row={state.data}
                fields={[
                  "issuing_facility",
                  ["version_no", "Version"],
                  ["released_at", "Released"],
                  ["generated_at", "Prepared"],
                ]}
              />
              <PatientPdf
                key={state.data.report_id}
                reportId={state.data.report_id}
                code={state.data.report_code}
              />
            </section>
            <section className="card">
              <h2>Patient & requesting physician</h2>
              <Details
                row={state.data.patient_snapshot}
                fields={[
                  "patient_name",
                  "patient_code",
                  "birth_date",
                  "age_at_report",
                  "sex",
                  "physician_name",
                ]}
              />
            </section>
            <section className="card">
              <h2>Results</h2>
              <p className="muted">
                Flags describe how a result compares with the laboratory’s
                reference ranges. A flag is not a diagnosis. These are the
                values recorded on this released report.
              </p>
              <SnapshotResults rows={state.data.result_snapshots} />
            </section>
            <section className="card">
              <h2>Signatories</h2>
              {state.data.signatories.length ? (
                <Table
                  caption="Report signatories"
                  rows={[...state.data.signatories].sort(
                    (a, b) => Number(a.sort_order) - Number(b.sort_order),
                  )}
                  columns={[
                    { key: "staff_name", label: "Name" },
                    {
                      key: "signatory_type",
                      label: "Role",
                      render: (r) =>
                        String(r.signatory_type)
                          .toLowerCase()
                          .replaceAll("_", " "),
                    },
                    { key: "license_number_snapshot", label: "License" },
                    { key: "signed_at", label: "Signed", date: true },
                  ]}
                />
              ) : (
                <p>No signatory information is available.</p>
              )}
            </section>
            <section className="card">
              <h2>Report integrity</h2>
              <p>
                {state.data.verification_status === "AUTHENTIC"
                  ? "This report has an authentic integrity record. Its PDF is checked again before it is delivered."
                  : "Integrity information is not available. Contact the laboratory if you need help."}
              </p>
            </section>
          </>
        )
      )}
    </>
  );
}
export function SnapshotResults({ rows }: { rows: PatientResult[] }) {
  const sorted = [...rows].sort((a, b) => a.sort_order - b.sort_order);
  const groups: { name: string | null; items: PatientResult[] }[] = [];
  for (const row of sorted) {
    const last = groups[groups.length - 1];
    if (last && last.name === row.section_name_snapshot) last.items.push(row);
    else groups.push({ name: row.section_name_snapshot, items: [row] });
  }
  return groups.length ? (
    <>
      {groups.map((group, index) => (
        <section key={index} className="result-section">
          {group.name && <h3>{group.name}</h3>}
          <Table
            caption={group.name || "Report results"}
            rows={group.items}
            columns={[
              { key: "test_name_snapshot", label: "Test" },
              {
                key: "flag_snapshot",
                label: "Flag",
                render: (r) => (
                  <PatientFlag flag={r.flag_snapshot as string | null} />
                ),
              },
              { key: "result_value_snapshot", label: "Result" },
              { key: "unit_snapshot", label: "Unit" },
              { key: "reference_range_snapshot", label: "Reference range" },
            ]}
          />
        </section>
      ))}
    </>
  ) : (
    <p>No result information is available.</p>
  );
}
export function PatientPdf({
  reportId,
  code,
}: {
  reportId: number;
  code: string;
}) {
  const [url, setUrl] = useState<string>();
  const currentUrl = useRef<string | undefined>(undefined);
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  function release() {
    if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    currentUrl.current = undefined;
    setUrl(undefined);
  }
  useEffect(
    () => () => {
      controller.current?.abort();
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );
  async function open(view: boolean) {
    release();
    setBusy(true);
    setError(undefined);
    const request = new AbortController();
    controller.current = request;
    try {
      const blob = await api<Blob>(`/patient/reports/${reportId}/pdf`, {
        blob: true,
        signal: request.signal,
      });
      if (request.signal.aborted) return;
      const next = URL.createObjectURL(blob);
      currentUrl.current = next;
      if (view) setUrl(next);
      else {
        const anchor = document.createElement("a");
        anchor.href = next;
        anchor.download = `${code}.pdf`;
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => {
          URL.revokeObjectURL(next);
          if (currentUrl.current === next) currentUrl.current = undefined;
        }, 1000);
      }
    } catch (e) {
      if (!request.signal.aborted) setError(e as Error);
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <PatientMessage error={error} context="pdf" />
      <div className="actions">
        <button className="primary" disabled={busy} onClick={() => open(true)}>
          View PDF
        </button>
        <button disabled={busy} onClick={() => open(false)}>
          Download PDF
        </button>
        {busy && <span role="status">Checking and opening your PDF…</span>}
      </div>
      {url && (
        <Dialog title="Report PDF" onClose={release}>
          <p>If the preview is unavailable, use Download PDF.</p>
          <iframe
            className="patient-pdf"
            src={url}
            title={`Official PDF for ${code}`}
          />
          <a className="button" href={url} download={`${code}.pdf`}>
            Download PDF
          </a>
        </Dialog>
      )}
    </>
  );
}
