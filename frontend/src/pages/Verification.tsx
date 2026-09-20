import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ShieldCheck, ShieldAlert, CircleHelp } from "lucide-react";
import { api, ApiError } from "../api/client";
import { PublicShell, PatientMessage } from "./patient/Shared";
import type { PublicVerification } from "../types/patient";
const states = {
  VERIFIED: {
    title: "Verified report",
    message: "The released report matches its stored integrity record.",
    icon: ShieldCheck,
  },
  REVOKED: {
    title: "Report revoked / no longer current",
    message:
      "This report has been revoked. Its contents must not be treated as a current valid report.",
    icon: ShieldAlert,
  },
  ALTERED: {
    title: "Report integrity warning",
    message: "The stored report artifact does not match its integrity record.",
    icon: ShieldAlert,
  },
  NOT_FOUND: {
    title: "Verification record not found.",
    message: "Check the verification token or contact the issuing laboratory.",
    icon: CircleHelp,
  },
};
export function Verification() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<PublicVerification>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError(undefined);
    setLoading(!!token);
    if (token)
      api<PublicVerification>("/verify/" + encodeURIComponent(token), {
        public: true,
        signal: controller.signal,
      })
        .then((result) => {
          if (!controller.signal.aborted) {
            if (!Object.hasOwn(states, result.status))
              throw new Error(
                "Verification is temporarily unavailable. Please try again.",
              );
            setData(result);
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted) {
            if (e instanceof ApiError && e.status === 404)
              setData({ status: "NOT_FOUND", message: "" });
            else setError(e);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    return () => controller.abort();
  }, [token, attempt]);
  const state = data ? states[data.status] : undefined;
  return (
    <PublicShell>
      <section className="card patient-auth-card verification-page">
        <p className="eyebrow">REPORT INTEGRITY VERIFICATION</p>
        <h1>Verify a laboratory report</h1>
        <p>
          Enter the verification token provided with the report. You do not need
          to sign in or provide personal information.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const input = e.currentTarget.elements.namedItem(
              "token",
            ) as HTMLInputElement;
            const value = input.value.trim();
            input.value = "";
            if (value === token) setAttempt((current) => current + 1);
            else if (value) navigate("/verify/" + encodeURIComponent(value));
          }}
        >
          <label>
            Verification token
            <input
              name="token"
              required
              maxLength={256}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
            />
          </label>
          <button className="primary">Check report</button>
        </form>
        <PatientMessage error={error} />
        {error && token && (
          <button onClick={() => setAttempt((current) => current + 1)}>
            Try again
          </button>
        )}
        {loading && (
          <p role="status">Checking the report’s integrity record…</p>
        )}
        {data && state && (
          <section
            className={"verification-result " + data.status.toLowerCase()}
            aria-live="polite"
          >
            <state.icon size={36} aria-hidden="true" />
            <h2>{state.title}</h2>
            <p>{state.message}</p>
            {data.status !== "NOT_FOUND" && (
              <dl className="details">
                {data.issuing_facility && (
                  <div>
                    <dt>Issuing facility</dt>
                    <dd>{data.issuing_facility}</dd>
                  </div>
                )}
                {data.report_date && (
                  <div>
                    <dt>Report date</dt>
                    <dd>{data.report_date}</dd>
                  </div>
                )}
                {data.version != null && (
                  <div>
                    <dt>Version</dt>
                    <dd>{data.version}</dd>
                  </div>
                )}
              </dl>
            )}
          </section>
        )}
        <p className="small muted">
          This page checks the laboratory’s stored report. It does not display
          patient details or laboratory results.
        </p>
        <Link to="/patient/login">Patient sign in</Link>
      </section>
    </PublicShell>
  );
}
