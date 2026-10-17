import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import type { Overview } from "../types/dashboard";
import { admin, mockFetch, order, page, renderAuth, respond } from "./helpers";

const path = "/api/v1/dashboard/overview";
const summary: Overview = {
  generated_at: "2026-10-17T08:00:00Z", patients: 27,
  orders: { total: 12, statuses: { REQUESTED: 3, IN_PROGRESS: 4, COMPLETED: 4, CANCELLED: 1 } },
  specimens: { total: 10, statuses: { PENDING: 2, COLLECTED: 3, RECEIVED: 1, PROCESSED: 3, REJECTED: 1 } },
  results: { total: 8, statuses: { DRAFT: 2, REVIEWED: 1, VERIFIED: 5 } },
  reports: { total: 9, statuses: { GENERATED: 3, APPROVED: 1, RELEASED: 4, REVOKED: 1 } },
};
const queue = { counts: { pending: 2, processing: 0, confirmed: 7, failed: 0, dead: 0 }, worker_health: "IDLE", last_confirmed_at: null, delivery_enabled: false };
const network = { status: "DEGRADED", checked_at: "2026-10-17T07:55:00Z", nodes: [{ status: "ONLINE" }, { status: "UNKNOWN" }] };
function normal(p: string) {
  if (p === path) return respond(summary);
  if (p.startsWith("/api/v1/lab-orders?")) return respond(page([{ ...order, patient: { first_name: "PRIVATE-PATIENT", last_name: "SECRET" } }]));
  if (p === "/api/v1/blockchain/status") return respond(queue);
  if (p === "/api/v1/admin/blockchain/overview") return respond(network);
}
const staff = (permissions: string[]) => ({ ...admin, roles: ["LAB_STAFF"], permissions });
const countFor = (region: HTMLElement, label: string) => within(region).getByText(label).parentElement?.querySelector("dd")?.textContent;

describe("authorized overview dashboard", () => {
  it("uses API totals and workflow stages without patient details", async () => {
    const fetch = mockFetch(normal);
    renderAuth(<AppRoutes />, "/dashboard");
    const pending = await screen.findByRole("region", { name: "Pending work" });
    expect(countFor(pending, "Requested orders")).toBe("3");
    expect(countFor(pending, "Specimens awaiting receipt")).toBe("3");
    expect(countFor(pending, "Reviewed results to verify")).toBe("1");
    expect(countFor(pending, "Approved reports awaiting release")).toBe("1");
    expect(within(screen.getByRole("article", { name: "Registered patients" })).getByText("27")).toBeVisible();
    expect(within(screen.getByRole("article", { name: "Reports total" })).getByText("9")).toBeVisible();
    expect(screen.getByText(/including superseded versions/)).toBeVisible();
    expect(screen.getByText(/not limited to today/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open order" })).toHaveAttribute("href", "/orders/1");
    expect(document.body).not.toHaveTextContent("PRIVATE-PATIENT");
    expect(document.body).not.toHaveTextContent("SECRET");
    expect(fetch.mock.calls.filter(([p]) => p === path)).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith(path, expect.objectContaining({ method: "GET", credentials: "include", cache: "no-store" }));
    expect(fetch.mock.calls.some(([p]) => p.startsWith("/api/v1/patients?"))).toBe(false);
  });
  it("does not fetch or show restricted workflow or health sections", async () => {
    const fetch = mockFetch(normal, staff(["PATIENT_READ"]));
    renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByRole("article", { name: "Registered patients" });
    for (const name of ["Orders total", "Reports total", "Results total", "Specimens total"]) expect(screen.queryByRole("article", { name })).not.toBeInTheDocument();
    for (const name of ["Recent orders", "Fabric network", "Blockchain anchoring"]) expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
    expect(fetch.mock.calls.map(([p]) => p)).toEqual(["/api/v1/auth/me", path]);
  });
  it("explains an account with no overview permissions", async () => {
    mockFetch(p => p === path ? respond({ generated_at: summary.generated_at }) : undefined, staff(["ANALYTICS_VIEW"]));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("No workflow summaries are available for your permissions.")).toBeVisible();
    expect(screen.getByText("No quick actions are available for your permissions.")).toBeVisible();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
  it("honors destination workspace permissions for links and quick actions", async () => {
    mockFetch(normal, staff(["SPECIMEN_READ", "SPECIMEN_REGISTER", "LAB_RESULT_READ", "PATIENT_CREATE"]));
    renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByRole("article", { name: "Specimens total" });
    const actions = screen.getByRole("heading", { name: "Quick actions" }).closest("section")!;
    expect(within(actions).queryByRole("link")).not.toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Specimens total" })).queryByRole("link")).not.toBeInTheDocument();
  });
  it("shows loading without invented zeroes then renders the response", async () => {
    let finish!: (response: Response) => void;
    mockFetch(p => p === path ? new Promise<Response>(resolve => { finish = resolve; }) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("Loading workflow summary…")).toBeVisible();
    expect(screen.queryByRole("article", { name: "Registered patients" })).not.toBeInTheDocument();
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    finish(respond(summary));
    expect(await screen.findByRole("article", { name: "Registered patients" })).toHaveTextContent("27");
  });
  it("shows known zeroes and empty states for an empty database", async () => {
    const empty = structuredClone(summary);
    empty.patients = 0;
    for (const key of ["orders", "specimens", "results", "reports"] as const) {
      empty[key]!.total = 0;
      Object.keys(empty[key]!.statuses).forEach(status => { empty[key]!.statuses[status] = 0; });
    }
    mockFetch(p => p === path ? respond(empty) : respond(page([])), staff(["PATIENT_READ", "LAB_ORDER_READ", "REPORT_READ"]));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("No orders recorded.")).toBeVisible();
    expect(screen.getByText("No reports recorded.")).toBeVisible();
    expect(screen.getByText("No pending work in the stages you can view.")).toBeVisible();
    expect(within(screen.getByRole("article", { name: "Registered patients" })).getByText("0")).toBeVisible();
  });
  it.each([403, 500, 503])("contains summary HTTP %s failures while other sections remain useful", async code => {
    mockFetch(p => p === path ? respond({ detail: "PRIVATE ERROR" }, code) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("Workflow summary unavailable. Refresh to try again.")).toBeVisible();
    expect(await screen.findByRole("link", { name: "Open order" })).toBeVisible();
    expect(await screen.findByText("Idle")).toBeVisible();
    expect(document.body).not.toHaveTextContent("PRIVATE ERROR");
    expect(screen.queryByRole("article", { name: "Orders total" })).not.toBeInTheDocument();
  });
  it("retries a failed summary", async () => {
    let attempts = 0;
    mockFetch(p => p === path ? (++attempts === 1 ? respond({}, 503) : respond(summary)) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByText("Workflow summary unavailable. Refresh to try again.");
    await userEvent.click(screen.getByRole("button", { name: "Refresh workflow summary" }));
    expect(await screen.findByRole("article", { name: "Orders total" })).toHaveTextContent("12");
    expect(attempts).toBe(2);
  });
  it("does not turn malformed counts into zero", async () => {
    mockFetch(p => p === path ? respond({ ...summary, orders: { total: 0, statuses: {} } }) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByRole("article", { name: "Orders total" })).toHaveTextContent("Unavailable");
    expect(screen.queryByRole("region", { name: "Orders status breakdown" })).not.toBeInTheDocument();
    expect(screen.queryByText("Requested orders")).not.toBeInTheDocument();
  });
  it("keeps partial Fabric observations separate from queue activity", async () => {
    mockFetch(normal); renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText("DEGRADED")).toBeVisible();
    expect(screen.getByText("1 of 2 peers reporting online")).toBeVisible();
    expect(screen.getByText(/separate from the anchoring queue/)).toBeVisible();
    expect(screen.getByText("Idle")).toBeVisible();
  });
  it("contains Fabric failure without hiding summary or queue", async () => {
    mockFetch(p => p === "/api/v1/admin/blockchain/overview" ? respond({}, 503) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByText(/Fabric health unavailable/)).toBeVisible();
    expect(await screen.findByRole("article", { name: "Orders total" })).toHaveTextContent("12");
    expect(screen.getByText("Idle")).toBeVisible();
  });
  it("refreshes all sections and aborts old requests", async () => {
    const fetch = mockFetch(normal); renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByRole("article", { name: "Orders total" });
    const first = fetch.mock.calls.find(([p]) => p === path)!;
    await userEvent.click(screen.getByRole("button", { name: "Refresh overview" }));
    await waitFor(() => expect(fetch.mock.calls.filter(([p]) => p === path)).toHaveLength(2));
    expect(first[1]?.signal?.aborted).toBe(true);
    expect(fetch.mock.calls.filter(([p]) => p === "/api/v1/blockchain/status")).toHaveLength(2);
    expect(await screen.findByRole("article", { name: "Orders total" })).toHaveTextContent("12");
  });
  it("redirects expired sessions without retaining dashboard data", async () => {
    mockFetch(p => p === path ? respond({}, 401) : normal(p));
    renderAuth(<AppRoutes />, "/dashboard");
    expect(await screen.findByLabelText("Username")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Laboratory overview" })).not.toBeInTheDocument();
  });
  it("never requests overview data before authentication", async () => {
    const fetch = mockFetch(normal, null); renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByLabelText("Username");
    expect(fetch.mock.calls.map(([p]) => p)).toEqual(["/api/v1/auth/me"]);
  });
});
