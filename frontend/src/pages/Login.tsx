import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Activity, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/Auth";
import { landingFor } from "../auth/PatientAccess";
import { Alert } from "../components/UI";
export function Login({
  patient = false,
  challenge = false,
}: {
  patient?: boolean;
  challenge?: boolean;
}) {
  const { user, refresh, clear, notice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mfa, setMfa] = useState(challenge);
  const [recovery, setRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  if (user && !location.state?.reauthenticate)
    return <Navigate to={landingFor(user)} replace />;
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    form.reset();
    setBusy(true);
    setError(undefined);
    try {
      const response = await api<{ mfa_required?: boolean }>(
        mfa
          ? recovery
            ? "/auth/mfa/recovery"
            : "/auth/mfa/verify"
          : "/auth/login",
        {
          method: "POST",
          public: true,
          body: mfa
            ? recovery
              ? { recovery_code: data.get("code") }
              : { code: data.get("code") }
            : {
                username: data.get("username"),
                password: data.get("password"),
              },
        },
      );
      form.reset();
      if (response?.mfa_required) {
        clear();
        if (patient) {
          navigate("/patient/mfa", { replace: true });
          return;
        }
        setMfa(true);
        return;
      }
      const current = await refresh();
      navigate(landingFor(current), { replace: true });
    } catch (e) {
      setError(e as Error);
      form.reset();
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand">
          <Activity size={32} /> RHU LabChain
        </div>
        <p className="eyebrow">
          {patient ? "PATIENT PORTAL" : "STAFF WEB PORTAL"}
        </p>
        <h1>
          Care starts with
          <br />
          clear results.
        </h1>
        <p>
          {patient
            ? "Your laboratory reports, securely in one place."
            : "A connected workspace for your laboratory."}
          <br />
          {patient
            ? "Access your reports and manage your account."
            : "From patient registration to released reports."}
        </p>
        <div className="security-note">
          <ShieldCheck />{" "}
          {patient
            ? "Private access to your own reports"
            : "Secure access for authorized staff"}
        </div>
      </section>
      <section className="login-card card">
        <p className="eyebrow">
          {patient ? "YOUR PATIENT ACCOUNT" : "YOUR LABORATORY WORKSPACE"}
        </p>
        <h2>{mfa ? "Verify your sign-in" : "Welcome back"}</h2>
        <p className="muted">
          {mfa
            ? recovery
              ? "Enter an unused recovery code."
              : "Enter the code from your authenticator."
            : patient
              ? "Sign in to view your released reports."
              : "Sign in with your staff account to continue."}
        </p>
        {(notice || location.state?.message) && (
          <p role="status" className="success">
            {notice || String(location.state.message)}
          </p>
        )}
        <Alert error={error} />
        <form onSubmit={submit}>
          <fieldset disabled={busy}>
            {!mfa ? (
              <>
                <label>
                  Username
                  <input
                    name="username"
                    autoComplete="username"
                    required
                    maxLength={60}
                  />
                </label>
                <label>
                  Password
                  <input
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    required
                  />
                </label>
              </>
            ) : (
              <label>
                {recovery ? "Recovery code" : "Authenticator code"}
                <input
                  key={String(recovery)}
                  name="code"
                  autoComplete="one-time-code"
                  inputMode={recovery ? "text" : "numeric"}
                  required
                  maxLength={recovery ? 128 : 6}
                  pattern={recovery ? undefined : "[0-9]{6}"}
                />
              </label>
            )}
            <button className="primary full">
              {busy ? "Signing in…" : mfa ? "Verify and continue" : "Sign in"}
            </button>
            {mfa && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    setRecovery(!recovery);
                    setError(undefined);
                  }}
                >
                  {recovery ? "Use authenticator" : "Use recovery code"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (patient) navigate("/patient/login", { replace: true });
                    setMfa(false);
                    setError(undefined);
                  }}
                >
                  Back to sign in
                </button>
              </>
            )}
          </fieldset>
        </form>
        <p className="small muted">
          {patient ? (
            <>
              <Link to="/patient/activate">Activate your account</Link> ·{" "}
              <Link to="/login">Staff sign in</Link>
            </>
          ) : (
            <Link to="/patient/login">Patient sign in or activation</Link>
          )}
          <br />
          <Link to="/verify">Verify a report</Link>
        </p>
      </section>
    </main>
  );
}
