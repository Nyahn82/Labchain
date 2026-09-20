import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText, ArrowUpRight, ShieldCheck } from "lucide-react";
import { useResource } from "../../api/useResource";
import { usePatientSecurity } from "../../auth/PatientAccess";
import { Details } from "../../components/Details";
import { Pagination, Title, Table } from "../../components/UI";
import { PatientMessage } from "./Shared";
import { person, timestamp } from "../../utils/display";
import type { Page, Row } from "../../types/domain";
import type { PatientReportSummary } from "../../types/patient";
export function PatientHome() {
  const profile = useResource<Row>("/patient/me");
  const reports = useResource<Page<PatientReportSummary>>(
    "/patient/reports?page=1&page_size=3",
  );
  const { security } = usePatientSecurity();
  return (
    <>
      <Title title="Your patient portal" eyebrow="WELCOME" />
      <section className="welcome">
        <div>
          <h2>
            {profile.data
              ? `Hello, ${String(profile.data.first_name)}.`
              : "Welcome."}
          </h2>
          <p>
            View reports released by your laboratory and keep your account
            secure.
          </p>
          <Link className="button primary" to="/patient/reports">
            View reports <ArrowUpRight size={16} />
          </Link>
        </div>
        <FileText size={60} aria-hidden="true" />
      </section>
      <PatientMessage error={profile.error} />
      {profile.loading && <p role="status">Loading your profile…</p>}
      <section className="card">
        <div className="section-heading">
          <h2>Recent reports</h2>
          <Link to="/patient/reports">See all reports</Link>
        </div>
        <PatientMessage error={reports.error} />
        {reports.loading ? (
          <p role="status">Loading your reports…</p>
        ) : (
          reports.data && <ReportCards reports={reports.data.items} />
        )}
      </section>
      <section className="card">
        <div className="section-heading">
          <h2>
            <ShieldCheck size={20} aria-hidden="true" /> Account security
          </h2>
          <Link to="/patient/security">Security settings</Link>
        </div>
        <p>
          {security.totp_enabled
            ? "Your authenticator is enabled."
            : "Your authenticator is not enabled."}{" "}
          {security.totp_enabled
            ? `${security.unused_recovery_codes} unused recovery codes available.`
            : ""}
        </p>
      </section>
    </>
  );
}
export function PatientProfile() {
  const state = useResource<Row>("/patient/me");
  return (
    <>
      <Title title="Your profile" eyebrow="PERSONAL INFORMATION" />
      <section className="card">
        <p>Contact your laboratory if any of these details need updating.</p>
        <PatientMessage error={state.error} />
        {state.loading ? (
          <p role="status">Loading your profile…</p>
        ) : state.data ? (
          <>
            <h2>{person(state.data)}</h2>
            <Details
              row={state.data}
              fields={[
                "patient_code",
                "birth_date",
                "sex",
                "civil_status",
                "nationality",
                "contact_number",
                "email",
                "address",
              ]}
            />
          </>
        ) : (
          !state.error && (
            <p>Your profile is not available. Please contact the laboratory.</p>
          )
        )}
      </section>
    </>
  );
}
export function ReportCards({ reports }: { reports: PatientReportSummary[] }) {
  if (!reports.length)
    return (
      <p className="empty">
        No released reports are available yet. Reports will appear here when
        your laboratory releases them.
      </p>
    );
  return (
    <div className="patient-report-cards">
      {reports.map((r) => (
        <article className="patient-report-card" key={r.report_id}>
          <div className="report-card-icon">
            <FileText aria-hidden="true" />
          </div>
          <div>
            <h3>
              <Link to={`/patient/reports/${r.report_id}`}>
                {r.report_code}
              </Link>
            </h3>
            <p>{r.issuing_facility}</p>
            <small>
              Released {timestamp(r.released_at)} · Version {r.version_no}
            </small>
            <p className="small">
              Integrity status:{" "}
              {r.verification_status === "AUTHENTIC"
                ? "Verified"
                : r.verification_status === "REVOKED"
                  ? "No longer current"
                  : "Not available"}
            </p>
          </div>
          <Link
            className="button"
            to={`/patient/reports/${r.report_id}`}
            aria-label={`Open report ${r.report_code}`}
          >
            View report <ArrowUpRight size={16} aria-hidden="true" />
          </Link>
        </article>
      ))}
    </div>
  );
}
export function PatientReports() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    search: "",
    date_from: "",
    date_to: "",
  });
  const params = new URLSearchParams({
    page: String(page),
    page_size: "12",
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
  });
  const state = useResource<Page<PatientReportSummary>>(
    "/patient/reports?" + params,
  );
  return (
    <>
      <Title title="Your reports" eyebrow="RELEASED BY YOUR LABORATORY" />
      <section className="card">
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            setFilters({
              search: String(data.get("search") || "").trim(),
              date_from: String(data.get("date_from") || ""),
              date_to: String(data.get("date_to") || ""),
            });
            setPage(1);
          }}
        >
          <label>
            Search reports
            <input
              name="search"
              type="search"
              maxLength={200}
              placeholder="Report or request reference"
            />
          </label>
          <label>
            Released from
            <input name="date_from" type="date" />
          </label>
          <label>
            Released through
            <input name="date_to" type="date" />
          </label>
          <button className="primary">Apply filters</button>
        </form>
        <PatientMessage error={state.error} />
        {state.loading ? (
          <p role="status">Loading your reports…</p>
        ) : (
          state.data && (
            <>
              <ReportCards reports={state.data.items} />
              <Pagination
                page={page}
                size={12}
                total={state.data.total}
                onPage={setPage}
              />
            </>
          )
        )}
      </section>
    </>
  );
}
export function AccessHistory() {
  const [page, setPage] = useState(1);
  const state = useResource<Page>(
    "/patient/access-history?page=" + page + "&page_size=20",
  );
  return (
    <>
      <Title title="Access history" eyebrow="YOUR ACCOUNT ACTIVITY" />
      <section className="card">
        <p>See when reports were viewed or downloaded through your account.</p>
        <PatientMessage error={state.error} />
        {state.loading ? (
          <p role="status">Loading access history…</p>
        ) : (
          state.data && (
            <>
              {!state.data.items.length ? (
                <p className="empty">No report access activity yet.</p>
              ) : (
                <Table
                  caption="Your report access history"
                  rows={state.data.items}
                  columns={[
                    { key: "timestamp", label: "Date and time", date: true },
                    {
                      key: "action",
                      label: "Activity",
                      render: (r) =>
                        r.action === "PATIENT_REPORT_VIEW"
                          ? "Viewed report"
                          : r.action === "PATIENT_REPORT_DOWNLOAD"
                            ? "Downloaded report"
                            : "Report access",
                    },
                    { key: "report_code", label: "Report reference" },
                  ]}
                />
              )}
              <Pagination
                page={page}
                total={state.data.total}
                onPage={setPage}
              />
            </>
          )
        )}
      </section>
    </>
  );
}
