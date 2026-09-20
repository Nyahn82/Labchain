import { useState } from "react";
import {
  Activity,
  FileText,
  Home,
  ShieldCheck,
  UserRound,
  History,
  LogOut,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/Auth";
import { api } from "../api/client";
import { PatientMessage } from "../pages/patient/Shared";
export function PatientLogout() {
  const { clear } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  return (
    <>
      <PatientMessage error={error} />
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(undefined);
          try {
            await api("/auth/logout", { method: "POST" });
            clear();
            navigate("/patient/login", { replace: true });
          } catch (e) {
            setError(e as Error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <LogOut size={18} aria-hidden="true" />
        {busy ? "Signing out…" : "Log out"}
      </button>
    </>
  );
}
const links = [
  { to: "/patient", label: "Home", icon: Home },
  { to: "/patient/reports", label: "Reports", icon: FileText },
  { to: "/patient/profile", label: "Profile", icon: UserRound },
  { to: "/patient/security", label: "Security", icon: ShieldCheck },
  { to: "/patient/access-history", label: "Access history", icon: History },
];
export function PatientShell() {
  return (
    <div className="patient-shell">
      <a
        className="skip-link"
        href="#patient-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("patient-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="patient-topbar">
        <div className="brand">
          <Activity aria-hidden="true" />
          RHU LabChain <span>Patient portal</span>
        </div>
        <PatientLogout />
      </header>
      <div className="patient-workspace">
        <nav className="patient-nav" aria-label="Patient navigation">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/patient"}>
              <link.icon size={20} aria-hidden="true" />
              <span>{link.label}</span>
            </NavLink>
          ))}
        </nav>
        <main id="patient-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <footer className="patient-footer">
        RHU LabChain · Your secure patient portal
      </footer>
    </div>
  );
}
