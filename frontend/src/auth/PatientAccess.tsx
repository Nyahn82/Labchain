import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "./Auth";
import type { PatientSecurity } from "../types/patient";
import type { User } from "../types/domain";
import { PatientLogout } from "../layouts/PatientShell";
import { PatientMessage } from "../pages/patient/Shared";
export type AccessStage =
  | "UNKNOWN"
  | "UNAUTHENTICATED"
  | "PASSWORD_AUTHENTICATED_MFA_SETUP_REQUIRED"
  | "MFA_CHALLENGE"
  | "AUTHENTICATED_PATIENT"
  | "AUTHENTICATED_STAFF";
export const landingFor = (user: User) =>
  user.roles.includes("PATIENT") ? "/patient" : "/dashboard";
export function accessStage(
  user: User | null,
  loading: boolean,
  security?: PatientSecurity,
): AccessStage {
  if (loading) return "UNKNOWN";
  if (!user) return "UNAUTHENTICATED";
  if (!user.roles.includes("PATIENT")) return "AUTHENTICATED_STAFF";
  if (!security) return "UNKNOWN";
  if (security.mfa_required && !security.totp_enabled)
    return "PASSWORD_AUTHENTICATED_MFA_SETUP_REQUIRED";
  if (security.mfa_required && !security.mfa_verified_for_current_session)
    return "MFA_CHALLENGE";
  return "AUTHENTICATED_PATIENT";
}
const SecurityContext = createContext<{
  security: PatientSecurity;
  refresh: () => Promise<void>;
}>(null!);
export const usePatientSecurity = () => useContext(SecurityContext);
export function PatientRoute() {
  const { user, loading, error, refresh } = useAuth();
  if (loading)
    return (
      <p className="splash" role="status">
        Opening your patient portal…
      </p>
    );
  if (error)
    return (
      <div className="patient-public">
        <PatientMessage error={error} />
        <button onClick={() => refresh().catch(() => undefined)}>
          Try again
        </button>
      </div>
    );
  if (!user) return <Navigate to="/patient/login" replace />;
  if (!user.roles.includes("PATIENT"))
    return <Navigate to="/dashboard" replace />;
  return <PatientPolicy key={user.user_id} />;
}
function PatientPolicy() {
  const { user } = useAuth();
  const location = useLocation();
  const [security, setSecurity] = useState<PatientSecurity>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [required, setRequired] = useState<
    "MFA_REQUIRED" | "MFA_ENROLLMENT_REQUIRED"
  >();
  async function refresh() {
    const next = await api<PatientSecurity>("/patient/security");
    setSecurity(next);
    setRequired(undefined);
    setError(undefined);
    setLoading(false);
  }
  useEffect(() => {
    const controller = new AbortController();
    api<PatientSecurity>("/patient/security", { signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) setSecurity(next);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    const policy = (event: Event) => {
      const code = (event as CustomEvent).detail;
      setRequired(code);
      if (code === "MFA_ENROLLMENT_REQUIRED")
        setSecurity((old) =>
          old
            ? {
                ...old,
                mfa_required: true,
                totp_enabled: false,
                mfa_verified_for_current_session: false,
              }
            : old,
        );
    };
    window.addEventListener("patient-security-required", policy);
    return () => {
      controller.abort();
      window.removeEventListener("patient-security-required", policy);
    };
  }, []);
  if (loading)
    return (
      <p className="splash" role="status">
        Checking your account security…
      </p>
    );
  if (error)
    return (
      <div className="patient-public card">
        <PatientMessage error={error} />
        <button onClick={() => refresh().catch(setError)}>Try again</button>
        <PatientLogout />
      </div>
    );
  const stage = accessStage(user, false, security);
  if (required === "MFA_REQUIRED" || stage === "MFA_CHALLENGE")
    return <Reauthenticate />;
  if (
    (required === "MFA_ENROLLMENT_REQUIRED" ||
      stage === "PASSWORD_AUTHENTICATED_MFA_SETUP_REQUIRED") &&
    location.pathname !== "/patient/setup-mfa"
  )
    return <Navigate to="/patient/setup-mfa" replace />;
  return security ? (
    <SecurityContext.Provider value={{ security, refresh }}>
      <Outlet />
    </SecurityContext.Provider>
  ) : null;
}
function Reauthenticate() {
  const { clear } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    clear(
      "Please sign in again and verify your authenticator or recovery code.",
    );
    navigate("/patient/login", {
      replace: true,
      state: {
        reauthenticate: true,
        message:
          "Please sign in again and verify your authenticator or recovery code.",
      },
    });
  }, []);
  return <p role="status">Returning to sign in…</p>;
}
