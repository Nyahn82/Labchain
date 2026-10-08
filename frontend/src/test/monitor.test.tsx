import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { AppRoutes } from "../App";
import { HashValue, abbreviateHash } from "../components/HashValue";
import { admin, mockFetch, renderAuth, respond } from "./helpers";
import type { NetworkOverview } from "../types/monitor";

const H = "a".repeat(64);
const WHEN = "2026-10-04T00:00:00Z";
const ROOT = "/api/v1/admin/blockchain";
const network: NetworkOverview = {
  channel: "labchain-channel", topology: "SINGLE_VPS", status: "ONLINE", ledger_height: 3, checked_at: WHEN,
  nodes: [1, 2, 3, 4].map(i => ({ name: `peer${i}`, msp: i < 3 ? "Org1MSP" : "Org2MSP", status: "ONLINE",
    height: 3, channel_member: true, current_block_hash: H, previous_block_hash: H,
    checked_at: WHEN, last_success_at: WHEN, error_code: null })),
  orderer: { name: "orderer", status: "ONLINE", signal: "TLS operations /healthz", height: null },
  chaincode: { name: "labchain-anchor", version: "1.0.0", sequence: 1, endorsement_policy: "/Channel/Application/Endorsement" },
};
const queue = { counts: { pending: 2, processing: 0, confirmed: 3, failed: 1, dead: 0 }, worker_health: "IDLE" };
const block = { number: 2, block_hash: H, previous_block_hash: H, transaction_count: 1, timestamp: WHEN };
const tx = { transaction_id: H, validation_code: 0, validation_status: "VALID", timestamp: WHEN };
const blocks = { items: [block], ledger_height: 3, next_before: 2, source_peer: "peer1", checked_at: WHEN };
const anchor = { event_id: 1, event_uuid: "11111111-1111-4111-8111-111111111111", entity_reference: "22222222-2222-4222-8222-222222222222",
  event_type: "REPORT_RELEASED", entity_type: "REPORT", status: "CONFIRMED", record_hash: H, previous_hash: null,
  occurred_at: WHEN, confirmed_at: WHEN, transaction_id: H, block_number: 2,
  canonical_payload: "PRIVATE-PAYLOAD", lease_token: "PRIVATE-LEASE" };
function standard(p: string) {
  if (p === ROOT + "/overview") return respond(network);
  if (p === ROOT + "/queue") return respond(queue);
  if (p.startsWith(ROOT + "/blocks?")) return respond(blocks);
  if (p === ROOT + "/blocks/2") return respond({ ...block, transactions: [tx], source_peer: "peer1", checked_at: WHEN });
  if (p.startsWith(ROOT + "/transactions/")) return respond({ ...tx, block_number: 2, block_hash: H, source_peer: "peer1", checked_at: WHEN });
  if (p.startsWith(ROOT + "/anchors?")) return respond({ items: [anchor], next_before: null });
  if (p.endsWith("/integrity")) return respond({ report_id: 1, status: "VERIFIED", checked_at: WHEN,
    artifact_sha256: H, report_hash: H, record_hash: H, ledger_content_hash: H, source_peer: "peer1" });
}
async function open() {
  renderAuth(<AppRoutes />, "/administration/blockchain");
  await screen.findByRole("heading", { name: "Blockchain Monitor" });
}
describe("administrative blockchain monitor", () => {
  it("loads network cards, peers, channel, chaincode and distinct application queue", async () => {
    mockFetch(standard); await open();
    expect(await screen.findByText("4 / 4")).toBeVisible();
    expect(screen.getByText(/single-host fault domain/)).toBeVisible();
    expect(screen.getByRole("region", { name: "Fabric nodes" })).toHaveTextContent("peer4");
    expect(screen.getAllByText("labchain-anchor")).toHaveLength(2);
    const outbox = screen.getByRole("region", { name: "Application outbox status" });
    expect(within(outbox).getByText("IDLE")).toBeVisible();
    expect(within(outbox).getByText(/separate from Fabric ledger confirmation/)).toBeVisible();
    expect(screen.getByRole("tablist", { name: "Monitor sections" })).toBeVisible();
  });
  it("blocks normal staff without issuing monitor requests", async () => {
    const fetch = mockFetch(standard, { ...admin, roles: ["LAB_STAFF"], permissions: ["BLOCKCHAIN_STATUS_VIEW", "REPORT_READ"] });
    renderAuth(<AppRoutes />, "/administration/blockchain");
    expect(await screen.findByRole("heading", { name: "Permission required" })).toBeVisible();
    expect(fetch.mock.calls.some(([p]) => p.includes("/admin/blockchain"))).toBe(false);
  });
  it("allows explicit explorer permission but hides integrity without its separate grant", async () => {
    mockFetch(standard, { ...admin, roles: ["LAB_STAFF"], permissions: ["BLOCKCHAIN_EXPLORER_VIEW"] });
    await open(); expect(await screen.findByText("4 / 4")).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Integrity" })).not.toBeInTheDocument();
  });
  it("shows loading, then a partial network result without hiding the healthy peers", async () => {
    let resolve!: (value: Response) => void;
    mockFetch(p => p === ROOT + "/overview" ? new Promise<Response>(r => { resolve = r; }) : standard(p));
    await open(); expect(screen.getAllByText("Loading records…").length).toBeGreaterThan(0);
    resolve(respond({ ...network, status: "DEGRADED", nodes: network.nodes.map((n, i) => i === 1 ? { ...n, status: "OFFLINE", height: null } : n) }));
    expect(await screen.findByText("3 / 4")).toBeVisible();
    expect(screen.getByText("OFFLINE")).toBeVisible();
    expect(screen.getByText("DEGRADED")).toBeVisible();
  });
  it("shows safe errors while queue remains available", async () => {
    mockFetch(p => p === ROOT + "/overview" ? respond({ detail: "Network unavailable" }, 503) : standard(p));
    await open(); expect(await screen.findByRole("alert")).toHaveTextContent("The server could not complete the request");
    expect(screen.getByText("IDLE")).toBeVisible();
  });
  it("opens block details, transaction validation and bounded older pages", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); await open();
    await user.click(screen.getByRole("tab", { name: "Ledger" }));
    await user.click(await screen.findByRole("button", { name: "Block 2" }));
    expect(await screen.findByText("VALID")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "View transaction" }));
    expect(await screen.findByLabelText("Transaction detail")).toHaveTextContent("VALID");
    await user.click(screen.getByRole("button", { name: "Older blocks" }));
    expect(fetch.mock.calls.some(([p]) => p.endsWith("blocks?limit=10&before=2"))).toBe(true);
  });
  it("filters anchors and never renders extra private fields", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); await open();
    await user.click(screen.getByRole("tab", { name: "Anchors" }));
    expect(await screen.findByRole("rowheader", { name: "REPORT_RELEASED" })).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Status"), "CONFIRMED");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(fetch.mock.calls.some(([p]) => p.includes("status=CONFIRMED"))).toBe(true);
    expect(document.body).not.toHaveTextContent("PRIVATE");
  });
  it("handles empty ledger and anchors", async () => {
    mockFetch(p => p.includes("/blocks?") ? respond({ ...blocks, items: [], next_before: null })
      : p.includes("/anchors?") ? respond({ items: [], next_before: null }) : standard(p));
    const user = userEvent.setup(); await open();
    await user.click(screen.getByRole("tab", { name: "Ledger" }));
    expect(await screen.findByText("No records found.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Older blocks" })).toBeDisabled();
    await user.click(screen.getByRole("tab", { name: "Anchors" }));
    expect(await screen.findByText("No records found.")).toBeVisible();
  });
  it("performs read-only integrity lookup", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); await open();
    await user.click(screen.getByRole("tab", { name: "Integrity" }));
    await user.type(screen.getByLabelText("Report ID"), "1");
    await user.click(screen.getByRole("button", { name: "Verify integrity" }));
    expect(await screen.findByText("VERIFIED")).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(ROOT + "/reports/1/integrity", expect.objectContaining({ method: "GET" }));
  });
});
describe("Phase 12A health presentation", () => {
  it("shows every reported health state, membership, organization and separate orderer", async () => {
    const states = ["ONLINE", "DEGRADED", "OFFLINE", "UNKNOWN"] as const;
    mockFetch(p => p === ROOT + "/overview" ? respond({ ...network, nodes: network.nodes.map((peer, i) => ({ ...peer, status: states[i], channel_member: i === 3 ? null : i !== 2 })) }) : standard(p));
    await open();
    const peers = await screen.findByRole("region", { name: "Fabric nodes" });
    expect(within(peers).getAllByRole("article")).toHaveLength(4);
    for (const [index, state] of states.entries()) {
      const card = within(peers).getByRole("article", { name: `peer${index + 1}` });
      expect(within(card).getByLabelText(`peer${index + 1}: ${state}`)).toHaveTextContent(state);
      expect(card).toHaveTextContent(index < 2 ? "Org1MSP" : "Org2MSP");
      expect(card).toHaveClass("peer-card");
    }
    expect(within(peers).getByRole("article", { name: "peer3" })).toHaveTextContent("Channel memberNo");
    expect(within(peers).getByRole("article", { name: "peer4" })).toHaveTextContent("Channel memberUnknown");
    const orderer = screen.getByRole("region", { name: "Orderer health" });
    expect(orderer).toHaveTextContent("TLS operations /healthz");
    expect(orderer).not.toHaveTextContent("Ledger height");
    expect(orderer).not.toHaveTextContent("Channel member");
    expect(screen.getByRole("region", { name: "Fabric network overview" })).toHaveTextContent("Version 1.0.0");
  });
  it("supports keyboard tab navigation and associated panels", async () => {
    mockFetch(standard); const user = userEvent.setup(); await open();
    const networkTab = screen.getByRole("tab", { name: "Network" });
    networkTab.focus(); await user.keyboard("{ArrowRight}");
    const ledger = screen.getByRole("tab", { name: "Ledger" });
    expect(ledger).toHaveFocus(); expect(ledger).toHaveAttribute("aria-selected", "true");
    expect(networkTab).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tabpanel", { name: "Ledger" }).id).toBe(ledger.getAttribute("aria-controls"));
    expect(await screen.findByRole("button", { name: "Block 2" })).toBeVisible();
    await user.keyboard("{End}"); expect(screen.getByRole("tab", { name: "Integrity" })).toHaveFocus();
    await user.keyboard("{Home}"); expect(networkTab).toHaveFocus();
    await user.keyboard("{ArrowLeft}"); expect(screen.getByRole("tab", { name: "Integrity" })).toHaveFocus();
  });
  it.each(["MISMATCH", "UNKNOWN"])("labels %s integrity without relying on color", async status => {
    mockFetch(p => p.endsWith("/integrity") ? respond({ status, checked_at: WHEN }) : standard(p));
    const user = userEvent.setup(); await open();
    await user.click(screen.getByRole("tab", { name: "Integrity" }));
    await user.type(screen.getByLabelText("Report ID"), "1");
    await user.click(screen.getByRole("button", { name: "Verify integrity" }));
    expect(await screen.findByRole("status")).toHaveTextContent(status === "MISMATCH" ? "Mismatch" : "Unable to verify");
  });
  it("renders unavailable observations without invented height or chaincode", async () => {
    mockFetch(p => p === ROOT + "/overview" ? respond({ ...network, nodes: [], chaincode: null, ledger_height: null, status: "UNKNOWN" }) : standard(p));
    await open();
    expect(await screen.findByText("No peer observations available.")).toBeVisible();
    expect(screen.getByText(/Committed definition unavailable/)).toBeVisible();
    expect(screen.getByLabelText("Network: UNKNOWN")).toBeVisible();
  });
});
describe("safe hash display", () => {
  it("abbreviates, expands, wraps and copies with accessible labels", async () => {
    const user = userEvent.setup(); const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<HashValue value={H} label="transaction ID" />);
    expect(abbreviateHash(H)).toBe("aaaaaaaa…aaaaaaaa");
    expect(screen.getByText("aaaaaaaa…aaaaaaaa")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Show full transaction ID"));
    expect(screen.getByText(H)).toHaveClass("hash-full");
    await user.click(screen.getByRole("button", { name: "Copy transaction ID" }));
    expect(copy).toHaveBeenCalledWith(H); expect(screen.getByRole("status")).toHaveTextContent("Copied");
  });
  it("reports clipboard failure and handles unavailable hashes", async () => {
    const user = userEvent.setup(); vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error());
    render(<><HashValue value={H} /><HashValue value={null} label="previous hash" /></>);
    await user.click(screen.getByRole("button", { name: "Copy Hash" }));
    expect(screen.getByRole("status")).toHaveTextContent("Copy unavailable");
    expect(screen.getByLabelText("previous hash unavailable")).toBeVisible();
  });
});
