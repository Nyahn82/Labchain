import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  Menu,
  LogOut,
  LayoutDashboard,
  Users,
  ClipboardList,
  FlaskConical,
  Microscope,
  FileText,
  Settings,
  Stethoscope,
  Building2,
  UserRoundCog,
  Shield,
} from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/Auth";
import { Alert } from "../components/UI";
export const navigation = [
  {
    to: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    permission: "",
  },
  {
    to: "/patients",
    label: "Patients",
    icon: Users,
    permission: "PATIENT_READ",
  },
  {
    to: "/orders",
    label: "Laboratory orders",
    icon: ClipboardList,
    permission: "LAB_ORDER_READ",
  },
  {
    to: "/specimens",
    label: "Specimens",
    icon: FlaskConical,
    permission: "SPECIMEN_READ",
  },
  {
    to: "/results",
    label: "Results",
    icon: Microscope,
    permission: "LAB_RESULT_READ",
  },
  {
    to: "/reports",
    label: "Reports",
    icon: FileText,
    permission: "REPORT_READ",
  },
  {
    to: "/laboratory",
    label: "Laboratory setup",
    icon: Settings,
    permission: "LAB_MASTER_READ",
  },
  {
    to: "/physicians",
    label: "Physicians",
    icon: Stethoscope,
    permission: "PHYSICIAN_READ",
  },
  {
    to: "/facilities",
    label: "Referring facilities",
    icon: Building2,
    permission: "REFERRING_FACILITY_READ",
  },
  {
    to: "/staff",
    label: "Staff",
    icon: UserRoundCog,
    permission: "STAFF_READ",
  },
  {
    to: "/administration",
    label: "Administration",
    icon: Shield,
    permission: "ACCOUNT_READ",
  },
];
export function Shell() {
  const { user, can, clear } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const location = useLocation();
  const title =
    [...navigation].reverse().find((n) => location.pathname.startsWith(n.to))
      ?.label || "Staff workspace";
  async function logout() {
    setBusy(true);
    setError(undefined);
    try {
      await api("/auth/logout", { method: "POST" });
      clear();
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  const visible = (n: (typeof navigation)[number]) =>
    !n.permission ||
    can(n.permission) ||
    (n.to === "/administration" && can("ROLE_READ")) ||
    (n.to === "/laboratory" && can("REJECTION_REASON_MANAGE"));
  const staffAccess = navigation.some((n) => n.permission && visible(n));
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <aside
        className={"sidebar " + (open ? "open" : "")}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
            document.querySelector<HTMLButtonElement>(".mobile-menu")?.focus();
          }
        }}
      >
        <div className="brand">
          <Activity /> RHU LabChain
        </div>
        <p className="eyebrow">LABORATORY WORKSPACE</p>
        <nav aria-label="Main navigation">
          {navigation.filter(visible).map((n) => (
            <NavLink key={n.to} to={n.to} onClick={() => setOpen(false)}>
              <n.icon size={19} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" /> Staff portal
        </div>
      </aside>
      {open && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <button
            className="mobile-menu"
            aria-label="Toggle navigation"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <Menu />
          </button>
          <span className="breadcrumb">
            Workspace <span>/</span> <strong>{title}</strong>
          </span>
          <div className="account">
            <span className="avatar">
              {user?.username.slice(0, 2).toUpperCase()}
            </span>
            <span>
              {user?.username}
              <small>Authorized staff session</small>
            </span>
            <button aria-label="Log out" disabled={busy} onClick={logout}>
              <LogOut size={18} />
            </button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <Alert error={error} />
          {staffAccess ? (
            <Outlet key={user?.user_id} />
          ) : (
            <section className="card">
              <h1>Staff access required</h1>
              <p>
                This workspace is for laboratory staff. Contact your
                administrator.
              </p>
            </section>
          )}
        </main>
        <footer className="page-footer">
          RHU LabChain <span>Laboratory information system</span>
        </footer>
      </div>
    </div>
  );
}
