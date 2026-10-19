import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useResource } from "../api/useResource";
import { useAuth } from "../auth/Auth";
import { Form } from "../components/Form";
import { Details } from "../components/Details";
import { Dialog, State, Title } from "../components/UI";
import type { Row } from "../types/domain";
import { ResourcePage } from "./ResourcePage";
import { field, lookup, type Resource } from "./resources";

const active = field("is_active", "Active", { type: "boolean", default: false });
const activityFilter = [field("is_active", "Activity", { options: [{ value: "true", label: "Active" }, { value: "false", label: "Inactive" }] })];
export const templateResource: Resource = {
  title: "Report templates", singular: "report template", path: "/report-templates", key: "template_id",
  code: { key: "template_code", label: "Template code" },
  read: "REPORT_TEMPLATE_READ", create: "REPORT_TEMPLATE_MANAGE", update: "REPORT_TEMPLATE_MANAGE",
  fields: [field("template_name", "Template name", { required: true, max: 100 }),
    field("panel_id", "Panel", { lookup: lookup("/lab/panels", "panel_id", "panel_name", "LAB_MASTER_READ", "") }),
    field("header_title", "Header title", { max: 150 }), field("section_title", "Section title", { max: 150 }),
    field("clinical_note", "Clinical note", { type: "textarea", max: 16000 }),
    field("footer_note", "Footer note", { type: "textarea", max: 16000 }),
    field("medico_legal_note", "Medico-legal note", { type: "textarea", max: 16000 }), active],
  columns: [{ key: "template_code", label: "Code" }, { key: "template_name", label: "Name" },
    { key: "header_title", label: "Heading" }, { key: "is_active", label: "Active", badge: true }], filters: activityFilter,
};
const signatoryResource: Resource = {
  title: "Signatory profiles", singular: "signatory profile", path: "/signatories", key: "signatory_id",
  read: "SIGNATORY_READ", create: "SIGNATORY_MANAGE", update: "SIGNATORY_MANAGE",
  fields: [field("staff_id", "Associated staff member", { required: true, lookup: lookup("/staff", "staff_id", undefined, "STAFF_READ", "") }),
    field("license_number_snapshot", "Verified professional license", { max: 50, help: "Enter the actual facility-verified credential, when applicable. Never use a sample license for a real staff member." }),
    field("signature_image_path", "Existing private signature asset", { max: 255, help: "Optional relative path to an administrator-provisioned private asset. PDF v2 uses electronic attribution; it does not print scanned signature images." }), active],
  columns: [{ key: "signatory_id", label: "Profile" }, { key: "staff_id", label: "Staff ID" },
    { key: "license_number_snapshot", label: "License" }, { key: "is_active", label: "Active", badge: true }], filters: activityFilter,
};
const facilityFields = [field("facility_name", "Facility name", { required: true, max: 150 }),
  field("facility_type", "Facility type", { max: 80 }), field("address", "Address", { type: "textarea", max: 255 }),
  field("contact_number", "Contact number", { max: 30 }), field("email", "Email", { type: "email", max: 254 }),
  field("website", "Website", { max: 150 }), field("logo_path", "Existing private logo asset", { max: 255,
    help: "Optional relative filename under the configured private logo directory. Ask an administrator to provision the approved image; this form does not upload files." })];

function FacilitySetup() {
  const { can } = useAuth();
  const state = useResource<Row>("/facility-profile");
  const [editing, setEditing] = useState(false);
  const missing = state.error instanceof ApiError && state.error.status === 404;
  return <section className="card"><Title title="Facility profile">
    {!state.loading && (state.data || missing) && can("FACILITY_PROFILE_MANAGE") &&
      <button onClick={() => setEditing(true)}>{missing ? "Create facility profile" : "Edit facility profile"}</button>}
    <button onClick={state.reload} disabled={state.loading}>Refresh facility</button>
  </Title>
    <State loading={state.loading} error={missing ? undefined : state.error} />
    {missing && <p>No issuing facility is configured. An authorized administrator must supply the actual facility details before report generation.</p>}
    {state.data && <Details row={state.data} fields={facilityFields.map(f => [f.name, f.label] as [string, string])} />}
    {editing && <Dialog title={missing ? "Create facility profile" : "Edit facility profile"} onClose={() => setEditing(false)}>
      <Form fields={facilityFields} initial={state.data || {}} onSubmit={async body => {
        await api("/facility-profile", { method: missing ? "POST" : "PATCH", body }); setEditing(false); state.reload();
      }} />
    </Dialog>}
  </section>;
}

export function ReportSetup() {
  const { can, user } = useAuth();
  const sections = ["FACILITY_PROFILE_READ", "REPORT_TEMPLATE_READ", "SIGNATORY_READ"];
  if (user?.patient || user?.roles.includes("PATIENT") || !sections.some(can)) return <section className="card"><h1>Permission required</h1><p>Report setup requires authorized staff access.</p></section>;
  return <><Title title="Report setup" description="Configure the issuing facility, templates and real staff signatory profiles." />
    <section className="card"><p>Creating a signatory profile associates a real staff member with signing credentials. Assign that profile separately on each report; only its associated account can sign.</p>
      <p>Approved templates and signed profile details are protected. Create a new template or profile when those details need to change. Existing released PDFs retain their original content.</p>
      {can("STAFF_READ") && <Link to="/staff">Review staff and account associations →</Link>}
    </section>
    {can("FACILITY_PROFILE_READ") && <FacilitySetup />}
    {can("REPORT_TEMPLATE_READ") && <ResourcePage resource={templateResource} embedded />}
    {can("SIGNATORY_READ") && <ResourcePage resource={{ ...signatoryResource, columns: signatoryResource.columns.map(c => c.key === "staff_id" && can("STAFF_READ") ? { ...c, render: row => <Link to={`/staff/${row.staff_id}`}>Staff #{String(row.staff_id)}</Link> } : c) }} embedded />}
  </>;
}
