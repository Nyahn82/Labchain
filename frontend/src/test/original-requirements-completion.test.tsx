import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { Dashboard } from "../pages/Dashboard";
import { Results } from "../pages/Results";
import { OrderReports } from "../pages/Reports";
import { ReportSetup } from "../pages/ReportSetup";
import { admin, mockFetch, order, page, renderAuth, report, respond, result } from "./helpers";

const staff = (permissions: string[]) => ({ ...admin, roles: ["LAB_STAFF"], permissions });
const now = new Date().toISOString();
const summary = { generated_at: now, presence: { recently_active: 2, window_seconds: 300 },
  activation: { not_activated: 4, review_required: 1 }, accounts: { active: 3, suspended: 0 },
  failed_logins: { count: 7, since: "2026-10-18T01:00:00Z", until: "2026-10-19T01:00:00Z" },
  signing: { unassigned: 1, awaiting_signature: 2, awaiting_approval: 3 },
  services: [{ name: "Application", status: "HEALTHY", checked_at: now }, { name: "Database", status: "HEALTHY", checked_at: now }, { name: "Blockchain worker", status: "UNKNOWN" }] };

describe("completed dashboard metrics", () => {
  it("shows real security and signing counts with filtered destinations and honest worker state", async () => {
    mockFetch(p => p === "/api/v1/dashboard/overview" ? respond(summary) : undefined);
    renderAuth(<Dashboard />);
    const presence = await screen.findByRole("article", { name: "Recently active staff" });
    expect(presence).toHaveTextContent("2");
    expect(presence).toHaveTextContent("last 5 minutes");
    expect(screen.getByRole("article", { name: "Suspended accounts" })).toHaveTextContent("0");
    expect(screen.getByRole("article", { name: "Failed logins · last 24 hours" })).toHaveTextContent("7");
    expect(within(screen.getByRole("article", { name: "Signed reports awaiting approval" })).getByRole("link")).toHaveAttribute("href", "/reports?signing_stage=awaiting_approval");
    expect(within(screen.getByRole("article", { name: "Patients without activated portal accounts" })).getByRole("link")).toHaveAttribute("href", "/patients?activation_group=NOT_ACTIVATED");
    expect(screen.getByRole("region", { name: "Service attention" })).toHaveTextContent("UNKNOWN");
  });
  it("omits unauthorized security, activation and service aggregates even if returned", async () => {
    mockFetch(p => p === "/api/v1/dashboard/overview" ? respond(summary) : undefined, staff(["PATIENT_READ"]));
    renderAuth(<Dashboard />);
    await screen.findByRole("article", { name: "Registered patients" });
    for (const name of ["Recently active staff", "Active accounts", "Patients without activated portal accounts", "Signed reports awaiting approval"])
      expect(screen.queryByRole("article", { name })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Service attention" })).not.toBeInTheDocument();
  });
  it("shows missing and invalid counts as unavailable instead of zero", async () => {
    mockFetch(p => p === "/api/v1/dashboard/overview" ? respond({ generated_at: now, accounts: { active: -1 } }) : undefined, staff(["ACCOUNT_READ"]));
    renderAuth(<Dashboard />);
    expect(await screen.findByRole("article", { name: "Active accounts" })).toHaveTextContent("Unavailable");
    expect(screen.getByRole("article", { name: "Suspended accounts" })).toHaveTextContent("Unavailable");
  });
  it("distinguishes failed, degraded, stale and unknown node observations", async () => {
    mockFetch(p => p === "/api/v1/dashboard/overview" ? respond({ generated_at: now }) : p === "/api/v1/admin/blockchain/overview" ? respond({
      status: "DEGRADED", checked_at: now, orderer: { status: "ONLINE" }, nodes: [
        { name: "peer1", status: "OFFLINE", checked_at: now, error_code: "UNAVAILABLE" },
        { name: "peer2", status: "DEGRADED", checked_at: now },
        { name: "peer3", status: "ONLINE", checked_at: "2020-01-01T00:00:00Z" },
        { name: "peer4", status: "UNKNOWN", checked_at: now },
      ] }) : undefined, staff(["BLOCKCHAIN_EXPLORER_VIEW"]));
    renderAuth(<Dashboard />);
    await screen.findByText("Node attention");
    for (const [name, status] of [["peer1", "OFFLINE"], ["peer2", "DEGRADED"], ["peer3", "STALE"], ["peer4", "UNKNOWN"]])
      expect(screen.getByText(name).closest("li")).toHaveTextContent(status);
    expect(screen.getByText("0 of 4 peers with fresh online observations")).toBeVisible();
  });
});

describe("patient query controls", () => {
  it("combines server filters, name/code search and stable sorting with accessible status", async () => {
    const fetch = mockFetch(() => respond(page([{ patient_id: 1, patient_code: "PAT-100", first_name: "Same", last_name: "Name", activation_status: "REVIEW_REQUIRED" }], 31)));
    renderAuth(<AppRoutes />, "/patients?activation_group=NOT_ACTIVATED");
    expect(await screen.findByLabelText("Portal activation group")).toHaveValue("NOT_ACTIVATED");
    await userEvent.selectOptions(screen.getByLabelText("Activation state"), "REVIEW_REQUIRED");
    await userEvent.selectOptions(screen.getByLabelText("Sort patients"), "name");
    await userEvent.selectOptions(screen.getByLabelText("Sort direction"), "desc");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search patients" }), "PAT-100");
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p.includes("activation_group=NOT_ACTIVATED") && p.includes("activation_state=REVIEW_REQUIRED") && p.includes("sort_by=name") && p.includes("sort_direction=desc") && p.includes("search=PAT-100"))).toBe(true));
    expect(screen.getByText("Account review required", { selector: ".activation-badge" })).toHaveClass("activation-danger");
  });
});

describe("workflow corrections", () => {
  it("prevents new entry for a draft on a different results page", async () => {
    mockFetch(() => respond({ ...page([result], 21), occupied_item_ids: [1, 99] }));
    renderAuth(<Results order={{ ...order, items: [order.items[0], { ...order.items[0], order_item_id: 99 }] }} reload={() => {}} />);
    await screen.findByText("5.100");
    const buttons = screen.getAllByRole("button", { name: "Enter result" });
    expect(buttons).toHaveLength(2);
    buttons.forEach(button => expect(button).toBeDisabled());
  });
  it.each([undefined, []])("requires known occupancy but permits a confirmed new item (%s)", async ids => {
    mockFetch(() => respond({ ...page([]), occupied_item_ids: ids }));
    renderAuth(<Results order={order} reload={() => {}} />);
    await screen.findByText("No records found.");
    const button = screen.getByRole("button", { name: "Enter result" });
    if (ids) expect(button).toBeEnabled(); else expect(button).toBeDisabled();
  });
  it.each([0, 1])("only offers initial report generation when no report exists (%s)", async total => {
    mockFetch(() => respond(page(total ? [report] : [], total)));
    renderAuth(<OrderReports order={{ ...order, status: "COMPLETED" }} />);
    if (total) {
      await screen.findByText(/A report already exists/);
      expect(screen.queryByRole("button", { name: "Generate report" })).not.toBeInTheDocument();
    } else expect(await screen.findByRole("button", { name: "Generate report" })).toBeEnabled();
  });
  it("shows the permanent patient code and an authorized record link", async () => {
    mockFetch(p => p === "/api/v1/lab-orders/1" ? respond({ ...order, patient: { ...order.patient, patient_code: "PAT-777" } }) : undefined);
    renderAuth(<AppRoutes />, "/orders/1");
    expect(await screen.findByText("Patient code: PAT-777")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open patient record" })).toHaveAttribute("href", "/patients/1");
  });
  it("uses specimen-reject permission for active reason discovery", async () => {
    const fetch = mockFetch(p => p === "/api/v1/specimens/1" ? respond({ specimen_id: 1, specimen_code: "SPEC-1", specimen_status: "RECEIVED", order_id: 1, mappings: [], rejections: [] }) : p === "/api/v1/lab-orders/1" ? respond(order) : undefined,
      staff(["SPECIMEN_READ", "SPECIMEN_REJECT", "LAB_ORDER_READ"]));
    renderAuth(<AppRoutes />, "/specimens/1");
    await userEvent.click(await screen.findByRole("button", { name: "Reject specimen" }));
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p.startsWith("/api/v1/lab/rejection-reasons?") && p.includes("is_active=true"))).toBe(true));
    expect(screen.queryByText(/requires rejection reason manage/)).not.toBeInTheDocument();
  });
});

describe("report setup", () => {
  it("creates an actual facility only after an explicit form submission", async () => {
    let saved = false;
    const fetch = mockFetch((p, o) => {
      if (p !== "/api/v1/facility-profile") return undefined;
      if (o.method === "POST") { saved = true; return respond({ facility_name: "Synthetic review facility" }, 201); }
      return saved ? respond({ facility_name: "Synthetic review facility" }) : respond({ detail: "Not found" }, 404);
    });
    renderAuth(<ReportSetup />);
    await userEvent.click(await screen.findByRole("button", { name: "Create facility profile" }));
    await userEvent.type(screen.getByLabelText("Facility name *"), "Synthetic review facility");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetch.mock.calls.some(([p, o]) => p === "/api/v1/facility-profile" && o?.method === "POST" && JSON.parse(String(o.body)).facility_name === "Synthetic review facility")).toBe(true));
  });
  it("keeps template codes out of editable fields and creates inactive profiles", async () => {
    const fetch = mockFetch((p, o) => o.method === "POST" ? respond({ template_id: 1, template_code: "TMP-001" }, 201) : undefined);
    renderAuth(<ReportSetup />);
    await userEvent.click(await screen.findByRole("button", { name: "New report template" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText(/Template code/)).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Template name *"), "Synthetic template");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetch.mock.calls.some(([p, o]) => p === "/api/v1/report-templates" && o?.method === "POST")).toBe(true));
    const body = JSON.parse(String(fetch.mock.calls.find(([p, o]) => p === "/api/v1/report-templates" && o?.method === "POST")![1]!.body));
    expect(body).not.toHaveProperty("template_code");
    expect(body.is_active).toBe(false);
  });
  it("allows read-only setup without exposing manager controls or unauthorized requests", async () => {
    const fetch = mockFetch(() => respond(page([])), staff(["SIGNATORY_READ"]));
    renderAuth(<ReportSetup />);
    await screen.findByRole("heading", { name: "Signatory profiles" });
    expect(screen.queryByRole("button", { name: /New/ })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("facility-profile") || p.includes("report-templates"))).toBe(false);
  });
  it("associates a signatory with a selected real staff record and retains server validation errors", async () => {
    const fetch = mockFetch((p, o) => p.startsWith("/api/v1/staff?") ? respond(page([{ staff_id: 7, first_name: "Synthetic", last_name: "Signatory", staff_code: "STF-007" }])) :
      p === "/api/v1/signatories" && o.method === "POST" ? respond({ detail: "An active signatory requires active staff." }, 409) : undefined);
    renderAuth(<ReportSetup />);
    await userEvent.click(await screen.findByRole("button", { name: "New signatory profile" }));
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByRole("option", { name: /Synthetic.*Signatory/ });
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Associated staff member *" }), "7");
    await userEvent.type(within(dialog).getByLabelText("Verified professional license"), "SYNTHETIC-ONLY");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Active" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toBeVisible();
    const call = fetch.mock.calls.find(([p, o]) => p === "/api/v1/signatories" && o?.method === "POST")!;
    expect(JSON.parse(String(call[1]!.body))).toMatchObject({ staff_id: 7, license_number_snapshot: "SYNTHETIC-ONLY", is_active: true });
    expect(within(dialog).getByLabelText("Verified professional license")).toHaveValue("SYNTHETIC-ONLY");
  });
});
