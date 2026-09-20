import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Activity, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/Auth";
import { Alert } from "../components/UI";
export function Login() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [mfa, setMfa] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  if (user) return <Navigate to="/dashboard" replace />;
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
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
        setMfa(true);
        return;
      }
      await refresh();
      navigate("/dashboard", { replace: true });
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
        <p className="eyebrow">STAFF WEB PORTAL</p>
        <h1>
          Care starts with
          <br />
          clear results.
        </h1>
        <p>
          A connected workspace for your laboratory.
          <br />
          From patient registration to released reports.
        </p>
        <div className="security-note">
          <ShieldCheck /> Secure access for authorized staff
        </div>
      </section>
      <section className="login-card card">
        <p className="eyebrow">YOUR LABORATORY WORKSPACE</p>
        <h2>{mfa ? "Verify your sign-in" : "Welcome back"}</h2>
        <p className="muted">
          {mfa
            ? recovery
              ? "Enter an unused recovery code."
              : "Enter the code from your authenticator."
            : "Sign in with your staff account to continue."}
        </p>
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
                  maxLength={recovery ? 100 : 6}
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
          Patient access is managed separately. Contact your administrator for
          account assistance.
        </p>
      </section>
    </main>
  );
}
