import { useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";
import { Activity } from "lucide-react";
import { Link } from "react-router-dom";
export function patientError(
  error: Error,
  context: "general" | "report" | "pdf" | "activation" | "security" = "general",
) {
  if (!(error instanceof ApiError)) return error.message;
  if (
    context === "activation" &&
    [400, 401, 404, 409, 422].includes(error.status)
  )
    return "Activation could not be completed. Check your token and account details, or contact the laboratory.";
  if (
    (context === "report" && error.status === 404) ||
    (context === "pdf" && error.status === 404)
  )
    return "Report not available.";
  if (context === "pdf" && error.status === 409)
    return "The report could not be verified and is not available for download. Please contact the laboratory.";
  if (context === "security" && [400, 401, 422].includes(error.status))
    return "We could not verify those details. Check your password or code and try again.";
  if (error.status === 403)
    return "This part of your account is not available. Please contact the laboratory if you need help.";
  if (error.status === 409)
    return "This information has changed or is not available. Refresh the page and try again.";
  if (error.status === 422)
    return "Please check the details you entered and try again.";
  return error.message;
}
export function PatientMessage({
  error,
  context = "general",
}: {
  error?: Error;
  context?: Parameters<typeof patientError>[1];
}) {
  return error ? (
    <p className="alert" role="alert">
      {patientError(error, context)}
    </p>
  ) : null;
}
export function PublicShell({
  children,
  locked = false,
}: {
  children: ReactNode;
  locked?: boolean;
}) {
  return (
    <div className="patient-public">
      <header className="patient-public-header">
        {locked ? (
          <span className="brand">
            <Activity aria-hidden="true" />
            RHU LabChain
          </span>
        ) : (
          <>
            <Link className="brand" to="/patient/login">
              <Activity aria-hidden="true" />
              RHU LabChain
            </Link>
            <Link to="/verify">Verify a report</Link>
          </>
        )}
      </header>
      <main>{children}</main>
      <footer className="muted small">
        Your laboratory. Your information. Secure access.
      </footer>
    </div>
  );
}
export interface SecretField {
  name: string;
  label: string;
  type?: "password" | "text";
  autoComplete?: string;
  minLength?: number;
  maxLength?: number;
  numeric?: boolean;
}
export function SensitiveForm({
  fields,
  submit,
  onSubmit,
  children,
  context = "security",
}: {
  fields: SecretField[];
  submit: string;
  onSubmit: (values: Record<string, string>) => Promise<void>;
  children?: ReactNode;
  context?: Parameters<typeof patientError>[1];
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        const form = e.currentTarget;
        const data = new FormData(form);
        const values = Object.fromEntries(
          fields.map((f) => [f.name, String(data.get(f.name) || "")]),
        );
        form.reset();
        setBusy(true);
        setError(undefined);
        try {
          await onSubmit(values);
        } catch (e) {
          setError(e as Error);
        } finally {
          for (const key of Object.keys(values)) values[key] = "";
          setBusy(false);
        }
      }}
    >
      <PatientMessage error={error} context={context} />
      <fieldset disabled={busy}>
        {fields.map((f) => (
          <label key={f.name}>
            {f.label}
            <input
              name={f.name}
              type={f.type || "text"}
              required
              minLength={f.minLength}
              maxLength={f.maxLength || 1024}
              inputMode={f.numeric ? "numeric" : undefined}
              pattern={f.numeric ? "[0-9]{6}" : undefined}
              autoComplete={f.autoComplete || "off"}
            />
          </label>
        ))}
        {children}
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : submit}
        </button>
        <span className="sr-only" role="status">
          {busy ? "Submitting securely" : ""}
        </span>
      </fieldset>
    </form>
  );
}
export const passwordField: SecretField = {
  name: "password",
  label: "Current password",
  type: "password",
  autoComplete: "current-password",
  maxLength: 1024,
};
export const totpField: SecretField = {
  name: "code",
  label: "Authenticator code",
  numeric: true,
  minLength: 6,
  maxLength: 6,
  autoComplete: "one-time-code",
};
