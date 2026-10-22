import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  QrCode,
  X,
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
  { to: "/administration/analytics", label: "Analytics", icon: Activity, permission: "ANALYTICS_VIEW" },
  { to: "/administration/report-setup", label: "Report setup", icon: FileText, permission: "FACILITY_PROFILE_READ" },
  { to: "/administration/activity", label: "Authentication Activity", icon: Shield, permission: "AUTH_ACTIVITY_VIEW" },
  {
    to: "/administration/blockchain",
    label: "Blockchain Monitor",
    icon: Activity,
    permission: "BLOCKCHAIN_EXPLORER_VIEW",
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
    label: "Accounts and roles",
    icon: Shield,
    permission: "ACCOUNT_READ",
  },
];
const byRoute = (...routes: string[]) => routes.map(to => navigation.find(item => item.to === to)!);
export const navigationSections = [
  { label: "Overview", items: byRoute("/dashboard", "/administration/analytics") },
  { label: "Patients", items: byRoute("/patients", "/physicians", "/facilities") },
  { label: "Laboratory", items: byRoute("/orders", "/specimens", "/results") },
  { label: "Reports", items: [...byRoute("/reports"), { to: "/reports/scan", label: "Scan report QR", icon: QrCode, permission: "REPORT_READ" }] },
  { label: "Configuration", items: byRoute("/laboratory", "/administration/report-setup") },
  { label: "Administration", items: byRoute("/staff", "/administration", "/administration/activity", "/administration/blockchain") },
];
export function Shell() {
  const { user, can, clear } = useAuth();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [mobile, setMobile] = useState(() => window.matchMedia?.("(max-width: 760px)").matches ?? false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const location = useLocation();
  useEffect(() => {
    const media = window.matchMedia?.("(max-width: 760px)");
    if (!media) return;
    const change = () => { setMobile(media.matches); setOpen(false); };
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (!open || !mobile) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarRef.current?.querySelector<HTMLButtonElement>(".close-navigation")?.focus();
    return () => { document.body.style.overflow = prior; };
  }, [open, mobile]);
  useEffect(() => {
    if (wasOpen.current && !open) menuRef.current?.focus();
    wasOpen.current = open;
  }, [open]);
  const closeNavigation = () => { setOpen(false); };
  const title =
    [...navigation].sort((a, b) => b.to.length - a.to.length).find((n) => location.pathname.startsWith(n.to))
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
    n.to === "/reports/scan" ? !!user && !user.patient && !user.roles.includes("PATIENT") &&
      (user.roles.includes("SYSTEM_ADMIN") || (!!user.staff && user.roles.some(r => ["LAB_STAFF", "LAB_SUPERVISOR", "DOCTOR", "LAB_SIGNER"].includes(r)))) && can("REPORT_READ") && can("REPORT_DOWNLOAD") :
    !n.permission ||
    can(n.permission) ||
    (n.to === "/administration/report-setup" && (can("REPORT_TEMPLATE_READ") || can("SIGNATORY_READ"))) ||
    (n.to === "/administration/activity" && can("SESSION_MANAGE")) ||
    (n.to === "/administration" && can("ROLE_READ")) ||
    (n.to === "/laboratory" && can("REJECTION_REASON_MANAGE"));
  const staffAccess = navigation.some((n) => n.permission && visible(n));
  return (
    <div className={"app-shell" + (collapsed ? " sidebar-collapsed" : "")}>
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
        ref={sidebarRef}
        className={"sidebar " + (open ? "open" : "")}
        role={mobile && open ? "dialog" : undefined}
        aria-modal={mobile && open ? true : undefined}
        aria-label="Staff navigation"
        onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); closeNavigation(); }
          if (event.key === "Tab" && mobile && open) {
            const focusable = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled)') || []).filter(el => el.getClientRects().length > 0);
            const first = focusable[0], last = focusable.at(-1);
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
          }
        }}
      >
        <div className="brand">
          <Activity aria-hidden="true" /><span className="nav-label">RHU LabChain</span>
          <button type="button" className="close-navigation" aria-label="Close navigation" onClick={closeNavigation}><X size={20} /></button>
        </div>
        <nav aria-label="Main navigation" id="staff-navigation">
          {navigationSections.map(section => {
            const items = section.items.filter(visible);
            const active = items.some(n => location.pathname === n.to || (n.to !== "/administration" && location.pathname.startsWith(n.to + "/")));
            const expanded = groups[section.label] ?? (active || !["Configuration", "Administration"].includes(section.label));
            const groupId = `navigation-${section.label.toLowerCase()}`;
            return items.length > 0 && <section className="nav-section" key={section.label} aria-label={section.label}>
              <h2 className="nav-section-title"><button type="button" aria-expanded={collapsed && !mobile ? true : expanded}
                aria-controls={groupId} onClick={() => setGroups({ ...groups, [section.label]: !expanded })}>
                <span>{section.label}</span><ChevronDown size={14} aria-hidden="true" />
              </button></h2>
              <div id={groupId} hidden={!expanded && !(collapsed && !mobile)}>
                {items.map(n => <NavLink key={n.to} to={n.to}
                  end={n.to === "/administration" || n.to === "/reports"}
                  title={collapsed && !mobile ? n.label : undefined}
                  onClick={() => { setOpen(false); }}>
                  <n.icon size={19} aria-hidden="true" /><span className="nav-label">{n.label}</span>
                </NavLink>)}
              </div>
            </section>;
          })}
        </nav>
        <div className="sidebar-footer">
          <Shield size={16} aria-hidden="true" /><span className="nav-label">Staff portal</span>
        </div>
      </aside>
      {open && (
        <button
          className="nav-backdrop"
          aria-label="Dismiss navigation overlay"
          onClick={closeNavigation}
        />
      )}
      <div className="workspace" inert={mobile && open ? true : undefined}>
        <header className="topbar">
          <button
            ref={menuRef}
            className="mobile-menu"
            aria-label="Toggle navigation"
            aria-expanded={open}
            aria-controls="staff-navigation"
            onClick={() => setOpen(!open)}
          >
            <Menu />
          </button>
          <button type="button" className="desktop-menu" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed} aria-controls="staff-navigation" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
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
