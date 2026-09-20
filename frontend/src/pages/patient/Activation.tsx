import { Link, Navigate } from "react-router-dom";
import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/Auth";
import { landingFor } from "../../auth/PatientAccess";
import { PublicShell, SensitiveForm } from "./Shared";
export function Activation() {
  const { user } = useAuth();
  const [complete, setComplete] = useState(false);
  if (user) return <Navigate to={landingFor(user)} replace />;
  return (
    <PublicShell>
      <section className="card patient-auth-card">
        <p className="eyebrow">GET STARTED</p>
        <h1>
          {complete ? "Activation complete" : "Activate your patient account"}
        </h1>
        {complete ? (
          <>
            <p role="status">
              Your account is ready. Sign in to set up your authenticator and
              access your reports.
            </p>
            <Link className="button primary" to="/patient/login">
              Go to login
            </Link>
          </>
        ) : (
          <>
            <p>
              Paste the activation token provided by your laboratory. Choose a
              username and a password with at least 12 characters.
            </p>
            <SensitiveForm
              context="activation"
              submit="Activate account"
              fields={[
                {
                  name: "activation_token",
                  label: "Activation token",
                  maxLength: 256,
                },
                {
                  name: "username",
                  label: "Username",
                  autoComplete: "username",
                  maxLength: 60,
                },
                {
                  name: "password",
                  label: "Password",
                  type: "password",
                  autoComplete: "new-password",
                  minLength: 12,
                  maxLength: 1024,
                },
                {
                  name: "confirm_password",
                  label: "Confirm password",
                  type: "password",
                  autoComplete: "new-password",
                  minLength: 12,
                  maxLength: 1024,
                },
              ]}
              onSubmit={async (values) => {
                if (values.password !== values.confirm_password)
                  throw new Error(
                    "Passwords must match. Please enter them again.",
                  );
                await api("/patient/activate", {
                  method: "POST",
                  public: true,
                  body: {
                    activation_token: values.activation_token.trim(),
                    username: values.username.trim(),
                    password: values.password,
                  },
                });
                setComplete(true);
              }}
            />
            <p className="small muted">
              Already activated? <Link to="/patient/login">Sign in</Link>.
              Contact the laboratory if you need an activation token.
            </p>
          </>
        )}
      </section>
    </PublicShell>
  );
}
