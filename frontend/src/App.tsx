import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthenticatedRoute, AuthProvider } from "./auth/Auth";
import { Shell } from "./layouts/Shell";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { ResourcePage } from "./pages/ResourcePage";
import { resources } from "./pages/resources";
import { AccountDetail, Administration, PersonDetail } from "./pages/People";
import { LabDetail, Laboratory } from "./pages/Laboratory";
import { CreateOrder, OrderDetail, Orders } from "./pages/Orders";
import { SpecimenDetail } from "./pages/Specimens";
import { ReportDetail, Reports } from "./pages/Reports";
import { PatientRoute } from "./auth/PatientAccess";
import { PatientShell } from "./layouts/PatientShell";
import { Activation } from "./pages/patient/Activation";
import {
  PatientHome,
  PatientProfile,
  PatientReports,
  AccessHistory,
} from "./pages/patient/Portal";
import { PatientReport } from "./pages/patient/PatientReport";
import { MfaSetup, PatientSecurityPage } from "./pages/patient/Security";
import { Verification } from "./pages/Verification";
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/patient/login"
        element={<Login key="patient-login" patient />}
      />
      <Route
        path="/patient/mfa"
        element={<Login key="patient-mfa" patient challenge />}
      />
      <Route path="/patient/activate" element={<Activation />} />
      <Route path="/verify" element={<Verification />} />
      <Route path="/verify/:token" element={<Verification />} />
      <Route element={<PatientRoute />}>
        <Route path="/patient/setup-mfa" element={<MfaSetup />} />
        <Route element={<PatientShell />}>
          <Route path="/patient" element={<PatientHome />} />
          <Route path="/patient/profile" element={<PatientProfile />} />
          <Route path="/patient/reports" element={<PatientReports />} />
          <Route
            path="/patient/reports/:reportId"
            element={<PatientReport />}
          />
          <Route path="/patient/security" element={<PatientSecurityPage />} />
          <Route path="/patient/access-history" element={<AccessHistory />} />
          <Route
            path="/patient/*"
            element={<Navigate to="/patient" replace />}
          />
        </Route>
      </Route>
      <Route element={<AuthenticatedRoute />}>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          {["patients", "physicians", "facilities", "staff"].map((k) => (
            <Route
              key={k}
              path={k}
              element={<ResourcePage resource={resources[k]} />}
            />
          ))}
          <Route
            path="patients/:id"
            element={<PersonDetail kind="patients" />}
          />
          <Route path="staff/:id" element={<PersonDetail kind="staff" />} />
          <Route path="laboratory" element={<Laboratory />} />
          {["departments", "samples", "tests", "panels", "reasons"].map((k) => (
            <Route
              key={k}
              path={`laboratory/${k}`}
              element={<ResourcePage resource={resources[k]} />}
            />
          ))}
          <Route
            path="laboratory/tests/:id"
            element={<LabDetail kind="tests" />}
          />
          <Route
            path="laboratory/panels/:id"
            element={<LabDetail kind="panels" />}
          />
          <Route path="orders" element={<Orders />} />
          <Route path="orders/new" element={<CreateOrder />} />
          <Route path="orders/:id" element={<OrderDetail />} />
          {(["specimens", "results", "reports"] as const).map((tab) => (
            <Route
              key={tab}
              path={`orders/:id/${tab}`}
              element={<OrderDetail tab={tab} />}
            />
          ))}
          <Route path="specimens" element={<Orders mode="specimens" />} />
          <Route path="specimens/:id" element={<SpecimenDetail />} />
          <Route path="results" element={<Orders mode="results" />} />
          <Route path="reports" element={<Reports />} />
          <Route path="reports/:id" element={<ReportDetail />} />
          <Route path="administration" element={<Administration />} />
          <Route path="administration/:id" element={<AccountDetail />} />
          <Route
            path="*"
            element={
              <section className="card">
                <h1>Page not found</h1>
                <p>Choose a section from the navigation.</p>
              </section>
            }
          />
        </Route>
      </Route>
    </Routes>
  );
}
export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </HashRouter>
  );
}
