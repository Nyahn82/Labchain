import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { SafeReportAnchoring, StaffReportAnchoring } from "../components/BlockchainAnchoring";
import type { BlockchainAnchoringStatus, BlockchainStatusResponse, BlockchainWorkerHealth, SafeAnchoringStatus } from "../types/blockchain";
import { timestamp } from "../utils/display";
import { admin, mockFetch, page, renderAuth, report, respond } from "./helpers";
import { detail, patientFetch, portal, summary } from "./patient.helpers";

const confirmedAt = "2026-09-29T12:34:40.408596";
const transaction = "a123".repeat(16);
const hidden = {
  canonical_payload: "PRIVATE-PAYLOAD",
  lease_token: "PRIVATE-LEASE",
  last_error: "PRIVATE-WORKER-ERROR",
  last_error_code: "PRIVATE-ERROR-CODE",
  event_id: 987601,
  entity_id: 987602,
  origin_node_id: 987603,
  event_uuid: "PRIVATE-EVENT-UUID",
  source_msp: "PRIVATE-MSP",
  source_node: "PRIVATE-NODE",
  attempt_count: 987604,
};
const privateReceipt = {
  ...hidden,
  transaction_id: "PRIVATE-TRANSACTION",
  block_number: 987605,
  report_id: 987606,
};
const queue: BlockchainStatusResponse = {
  delivery_enabled: null,
  counts: { pending: 2, processing: 3, confirmed: 5, failed: 7, dead: 11 },
  last_confirmed_at: confirmedAt,
  last_confirmed_transaction_id: transaction,
  oldest_pending_at: null,
  worker_health: "IDLE",
};
const statuses: [BlockchainAnchoringStatus, string][] = [
  ["NOT_ANCHORED", "Not anchored"],
  ["PENDING", "Anchoring pending"],
  ["PROCESSING", "Anchoring in progress"],
  ["RETRYING", "Anchoring retry scheduled"],
  ["CONFIRMED", "Anchored"],
  ["FAILED", "Anchoring failed"],
];
const safeStatuses: [SafeAnchoringStatus, string, string][] = [
  ["NOT_ANCHORED", "Not anchored", "No blockchain anchor is available for this report."],
  ["PENDING", "Anchoring pending", "Blockchain anchoring is pending."],
  ["RETRYING", "Anchoring retry scheduled", "The laboratory is retrying blockchain anchoring."],
  ["CONFIRMED", "Anchored", "Tamper-evident evidence for this report has been anchored."],
  ["FAILED", "Anchoring failed", "Blockchain anchoring requires laboratory attention. This does not by itself mean the report is invalid."],
];
function expectPrivateFieldsHidden() {
  expect(document.body).not.toHaveTextContent(/PRIVATE-|98760[1-6]/);
  expect(document.querySelector("script[data-private]")).toBeNull();
}

describe("dashboard anchoring telemetry", () => {
  it.each([
    ["explicit permission", { ...admin, roles: ["LAB_STAFF"], permissions: ["REPORT_READ", "BLOCKCHAIN_STATUS_VIEW"] }],
    ["SYSTEM_ADMIN permission semantics", admin],
  ])("requests telemetry with %s", async (_, user) => {
    const fetch = mockFetch((p) => p === "/api/v1/blockchain/status" ? respond(queue) : undefined, user);
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("Idle")).toBeVisible();
    expect(fetch.mock.calls.filter(([p]) => p === "/api/v1/blockchain/status")).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/blockchain/status", expect.objectContaining({ method: "GET" }));
  });
  it("does not render or request telemetry without permission", async () => {
    const fetch = mockFetch(undefined, { ...admin, roles: ["LAB_STAFF"], permissions: ["REPORT_READ"] });
    renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByRole("heading", { name: "Laboratory overview" });
    expect(screen.queryByRole("region", { name: "Blockchain anchoring" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/blockchain/"))).toBe(false);
  });
  it.each<[BlockchainWorkerHealth, string, string]>([
    ["IDLE", "Idle", "neutral"],
    ["ACTIVE", "Active", "info"],
    ["DEGRADED", "Degraded", "warning"],
    ["ERROR", "Attention required", "danger"],
  ])("renders %s as queue state, without claiming liveness", async (worker_health, label, tone) => {
    mockFetch((p) => p === "/api/v1/blockchain/status" ? respond({ ...queue, worker_health }) : undefined);
    renderAuth(<AppRoutes />, "/dashboard");
    const badge = await screen.findByText(label);
    expect(badge.parentElement).toHaveClass(`tone-${tone}`);
    const panel = screen.getByRole("region", { name: "Blockchain anchoring" });
    expect(panel).toHaveTextContent("Anchoring queue status:");
    expect(panel).toHaveTextContent("Worker configuration: Not reported by this API");
    expect(panel).not.toHaveTextContent(/disabled|stopped|offline|service is running|network is healthy/i);
    expect(panel).not.toHaveTextContent(transaction);
    expect(panel).toHaveTextContent(timestamp(confirmedAt));
    for (const [label, value] of [["Pending", 2], ["Processing", 3], ["Confirmed", 5], ["Retrying", 7], ["Failed", 11]] as const) {
      const term = within(panel).getByText(label, { selector: "dt" });
      expect(term.nextElementSibling).toHaveTextContent(String(value));
    }
  });
  it.each([null, undefined, "not-a-date"])("handles last confirmation %s", async (last_confirmed_at) => {
    mockFetch((p) => p === "/api/v1/blockchain/status" ? respond({ ...queue, last_confirmed_at }) : undefined);
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText(`Last confirmed: ${last_confirmed_at == null ? "Never" : "—"}`)).toBeVisible();
  });
  it.each([false, true])("only reports explicit enablement %s as configuration", async (delivery_enabled) => {
    mockFetch((p) => p === "/api/v1/blockchain/status" ? respond({ ...queue, delivery_enabled }) : undefined);
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText(`Worker configuration: ${delivery_enabled ? "Enabled" : "Disabled"} (reported configuration)`)).toBeVisible();
  });
  it.each([403, 500, 503])("contains HTTP %s errors without breaking the dashboard", async (code) => {
    mockFetch((p) => p === "/api/v1/blockchain/status" ? respond({ detail: "PRIVATE-SQL-ERROR" }, code) : undefined);
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("Anchoring status unavailable")).toHaveAttribute("role", "alert");
    expect(screen.getByRole("heading", { name: "Laboratory overview" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Quick actions" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Recent orders" })).toBeVisible();
    expectPrivateFieldsHidden();
  });
  it.each([{}, { ...queue, counts: null }, { ...queue, worker_health: "PRIVATE-UNKNOWN" }, { ...queue, counts: { ...queue.counts, failed: -1 } }])("contains malformed telemetry %#", async (body) => {
    mockFetch((p) => p === "/api/v1/blockchain/status" ? respond(body) : undefined);
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("Anchoring status unavailable")).toBeVisible();
    expectPrivateFieldsHidden();
  });
});

async function staffReport(anchoring?: unknown, report_status = "RELEASED") {
  const fetch = mockFetch((p) => {
    if (p === "/api/v1/reports/1") return respond({ ...report, report_status, anchoring });
    if (p === "/api/v1/reports/1/verification") return respond({ verification_status: report_status === "REVOKED" ? "REVOKED" : "AUTHENTIC" });
  });
  renderAuth(<AppRoutes />, "/reports/1");
  await screen.findByRole("region", { name: "Blockchain anchoring" });
  return fetch;
}
describe("staff report anchoring lifecycle", () => {
  it.each(statuses)("shows %s release with only confirmed staff receipts", async (status, label) => {
    await staffReport({
      status,
      release: { ...hidden, status, transaction_id: transaction, block_number: 0, confirmed_at: confirmedAt },
      revocation: null,
      supersession: null,
    });
    const release = screen.getByRole("region", { name: "Release" });
    expect(within(release).getByText(label)).toBeVisible();
    expect(screen.getAllByText("Not applicable")).toHaveLength(2);
    if (status === "CONFIRMED") {
      expect(within(release).getByText(transaction).tagName).toBe("CODE");
      expect(within(release).getByText("Block number").nextElementSibling).toHaveTextContent("0");
      expect(release).toHaveTextContent(timestamp(confirmedAt));
      expect(within(release).queryByRole("link")).not.toBeInTheDocument();
    } else {
      expect(release).not.toHaveTextContent(transaction);
      expect(release).not.toHaveTextContent("Block number");
      expect(release).not.toHaveTextContent(timestamp(confirmedAt));
    }
    expect(screen.getByText("RELEASED", { selector: ".badge" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Report integrity verification" })).toBeVisible();
    expect(screen.queryByText("Verified report")).not.toBeInTheDocument();
    expectPrivateFieldsHidden();
  });
  it.each([undefined, null])("keeps legacy reports usable when anchoring is %s", async (anchoring) => {
    await staffReport(anchoring);
    expect(screen.getByText("Not anchored")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeVisible();
    expect(screen.getByText(/does not determine the clinical validity/)).toBeVisible();
  });
  it.each(["PENDING", "CONFIRMED"] as const)("keeps REVOKED primary with release confirmed and revocation %s", async (status) => {
    await staffReport({
      status,
      release: { status: "CONFIRMED", confirmed_at: confirmedAt, transaction_id: transaction },
      revocation: { status },
    }, "REVOKED");
    expect(screen.getAllByText("REVOKED", { selector: ".badge" })[0]).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Release" })).getByText("Anchored")).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Revocation" })).getByText(status === "PENDING" ? "Anchoring pending" : "Anchored")).toBeVisible();
    expect(screen.queryByText("Verified report")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Release report" })).not.toBeInTheDocument();
  });
  it("displays supersession independently without reinterpreting the report status", async () => {
    await staffReport({
      status: "RETRYING",
      release: { status: "CONFIRMED" },
      supersession: { status: "RETRYING" },
    }, "REVOKED");
    expect(within(screen.getByRole("region", { name: "Supersession" })).getByText("Anchoring retry scheduled")).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Revocation" })).getByText("Not applicable")).toBeVisible();
    expect(screen.getAllByText("REVOKED", { selector: ".badge" })[0]).toBeVisible();
  });
  it("does not fetch global telemetry from report detail", async () => {
    const fetch = await staffReport();
    expect(fetch.mock.calls.some(([p]) => p.includes("/blockchain/"))).toBe(false);
  });
});

describe("patient safe anchoring", () => {
  it.each(safeStatuses)("renders %s without private data or extra requests", async (status, label, message) => {
    const fetch = patientFetch((p) => p === "/api/v1/patient/reports/7" ? respond({
      ...detail,
      blockchain_verification: { ...privateReceipt, status, confirmed_at: confirmedAt },
      anchoring: { release: { status: "CONFIRMED", ...privateReceipt } },
    }) : undefined);
    portal("/patient/reports/7");
    const panel = await screen.findByRole("region", { name: "Blockchain verification" });
    expect(within(panel).getByText(label)).toBeVisible();
    expect(within(panel).getByText(message)).toBeVisible();
    if (status === "CONFIRMED") expect(panel).toHaveTextContent(timestamp(confirmedAt));
    else expect(panel).not.toHaveTextContent(timestamp(confirmedAt));
    if (status === "PENDING" || status === "RETRYING") expect(panel).toHaveTextContent("Your released report remains available.");
    expect(screen.getByRole("button", { name: "View PDF" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Report integrity" })).toBeVisible();
    expect(panel).not.toHaveTextContent(/Transaction ID|Block number/);
    expectPrivateFieldsHidden();
    expect(fetch.mock.calls.some(([p]) => p.includes("/blockchain/") || p.includes("/verification"))).toBe(false);
    expect(fetch.mock.calls.filter(([p]) => p === "/api/v1/patient/reports/7")).toHaveLength(1);
  });
  it("supports legacy detail without optional blockchain fields", async () => {
    patientFetch();
    portal("/patient/reports/7");
    expect(await screen.findByText("No blockchain anchor is available for this report.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeEnabled();
  });
  it("does not add anchoring requests or badges to patient cards", async () => {
    const fetch = patientFetch((p) => p.startsWith("/api/v1/patient/reports?") ? respond(page([summary, { ...summary, report_id: 8, report_code: "RPT-008" }])) : undefined);
    portal("/patient/reports");
    await screen.findByText("RPT-008");
    expect(screen.queryByText("Blockchain verification")).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => /\/patient\/reports\/\d|\/blockchain\//.test(p))).toBe(false);
  });
});

describe("public anchoring remains secondary to official verification", () => {
  const primary = [
    ["VERIFIED", "Verified report"],
    ["REVOKED", "Report revoked / no longer current"],
    ["ALTERED", "Report integrity warning"],
  ] as const;
  for (const [status, title] of primary) {
    it.each(safeStatuses)(`${status} with %s keeps primary semantics and safe fields`, async (blockchain_status, label) => {
      const fetch = patientFetch((p) => p.startsWith("/api/v1/verify/") ? respond({
        status,
        message: '<script data-private="yes">PRIVATE-HTML</script>',
        blockchain_status,
        blockchain_confirmed_at: confirmedAt,
        ...privateReceipt,
        // Unexpected staff payload must not override the safe aggregate status.
        anchoring: { release: { status: "CONFIRMED", ...privateReceipt }, revocation: { status: "PENDING" } },
      }) : undefined, null);
      portal("/verify/TOKEN");
      expect(await screen.findByRole("heading", { name: title, level: 2 })).toBeVisible();
      const panel = screen.getByRole("region", { name: "Blockchain anchoring" });
      expect(within(panel).getByRole("heading", { level: 3 })).toBeVisible();
      expect(within(panel).getByText(label)).toBeVisible();
      expect(panel).toHaveTextContent("verification above remains based on the laboratory’s official report record");
      expect(panel).not.toHaveTextContent(/Transaction ID|Block number|Your released report remains available/);
      if (blockchain_status === "CONFIRMED") expect(panel).toHaveTextContent(timestamp(confirmedAt));
      else expect(panel).not.toHaveTextContent(timestamp(confirmedAt));
      expectPrivateFieldsHidden();
      expect(fetch.mock.calls.some(([p]) => p.includes("/blockchain/") || p.includes("/reports/"))).toBe(false);
    });
  }
  it.each([undefined, "CONFIRMED"])("keeps NOT_FOUND neutral even with unexpected safe status %s", async (blockchain_status) => {
    patientFetch((p) => p.startsWith("/api/v1/verify/") ? respond({ status: "NOT_FOUND", message: "PRIVATE-MESSAGE", blockchain_status, ...privateReceipt }) : undefined, null);
    portal("/verify/TOKEN");
    expect(await screen.findByRole("heading", { name: "Verification record not found." })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Blockchain anchoring" })).not.toBeInTheDocument();
    expectPrivateFieldsHidden();
  });
  it.each([undefined, null, "PRIVATE-UNKNOWN", "PROCESSING"])("does not invent a public state for %s", async (blockchain_status) => {
    patientFetch((p) => p.startsWith("/api/v1/verify/") ? respond({ status: "VERIFIED", message: "", blockchain_status }) : undefined, null);
    portal("/verify/TOKEN");
    expect(await screen.findByRole("heading", { name: "Verified report" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Blockchain anchoring" })).not.toBeInTheDocument();
    expectPrivateFieldsHidden();
  });
});

describe("anchoring presentation compatibility", () => {
  it.each([null, undefined, "invalid-date"])("handles confirmation timestamp %s safely", (confirmed_at) => {
    render(<><StaffReportAnchoring anchoring={{ status: "CONFIRMED", release: { status: "CONFIRMED", confirmed_at } }} /><SafeReportAnchoring audience="patient" status="CONFIRMED" confirmedAt={confirmed_at} /></>);
    expect(document.body).not.toHaveTextContent(/Invalid Date|invalid-date|undefined|null/);
    if (confirmed_at) expect(screen.getAllByText("Confirmed: —")).toHaveLength(2);
    else expect(screen.queryByText(/Confirmed:/)).not.toBeInTheDocument();
  });
  it("does not echo unknown status values from an unexpected response", async () => {
    patientFetch((p) => p === "/api/v1/patient/reports/7" ? respond({ ...detail, blockchain_verification: { status: "PRIVATE-UNKNOWN" } }) : undefined);
    portal("/patient/reports/7");
    expect(await screen.findByText("Anchoring status unavailable")).toBeVisible();
    expectPrivateFieldsHidden();
  });
});
