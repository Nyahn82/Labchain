import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { LaboratoryProgress } from "../components/LaboratoryProgress";
import { ReportActions } from "../pages/Reports";
import { Results } from "../pages/Results";
import { admin, mockFetch, order, page, renderAuth, report, respond, result } from "./helpers";
const staff = (permissions: string[]) => ({ ...admin, roles: ["LAB_STAFF"], permissions });
const released = { ...report, report_status: "RELEASED" };

describe("laboratory workspace", () => {
  it("combines search, status, priority and date filters and clears them", async () => {
    const fetch = mockFetch(() => respond(page([order])));
    renderAuth(<AppRoutes />, "/orders");
    await screen.findByText(order.order_code);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search orders" }), "PAT-000123");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "IN_PROGRESS");
    await userEvent.selectOptions(screen.getByLabelText("Priority"), "STAT");
    await userEvent.type(screen.getByLabelText("Requested from"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("Requested to"), "2026-10-17");
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p.includes("search=PAT-000123") && p.includes("status=IN_PROGRESS") && p.includes("priority=STAT") && p.includes("date_from=2026-10-01") && p.includes("date_to=2026-10-17"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByLabelText("Requested from")).toHaveValue("");
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(fetch.mock.calls.at(-1)?.[0]).toBe("/api/v1/lab-orders?page=1&page_size=20&search=");
  });
  it("connects order tabs while keeping testing completion distinct from release", async () => {
    mockFetch(p => p === "/api/v1/lab-orders/1" ? respond({ ...order, status: "COMPLETED", items: order.items.map(i => ({ ...i, status: "COMPLETED" })) }) : undefined);
    renderAuth(<AppRoutes />, "/orders/1");
    const progress = await screen.findByRole("region", { name: "Laboratory workflow" });
    expect(within(progress).getByText("1 completed · 0 remaining")).toBeVisible();
    expect(within(progress).getByText(/signing, approval and release are separate/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(within(progress).getByRole("link", { name: "Result workbench" }));
    expect(await screen.findByRole("heading", { name: "Laboratory results" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Results", current: "page" })).toBeVisible();
  });
  it("does not expose unauthorized stages or make their requests", async () => {
    const fetch = mockFetch(p => p === "/api/v1/lab-orders/1" ? respond(order) : undefined, staff(["LAB_ORDER_READ"]));
    renderAuth(<AppRoutes />, "/orders/1");
    await screen.findByRole("region", { name: "Laboratory workflow" });
    for (const label of ["Collection & quality", "Result workbench", "Reports & versions"]) expect(screen.queryByText(label)).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => /\/results|\/reports|\/specimens/.test(p))).toBe(false);
  });
  it("offers a separate patient request without mutating verified results", async () => {
    const fetch = mockFetch();
    renderAuth(<LaboratoryProgress order={order} />);
    await userEvent.click(await screen.findByText("Repeat investigations and follow-up"));
    expect(screen.getByRole("link", { name: "New request for this patient" })).toHaveAttribute("href", "/orders/new?patient_id=1");
    expect(screen.getByText(/not an amendment or an external referral/)).toBeVisible();
    expect(fetch.mock.calls.every(([, o]) => !o || o.method === "GET")).toBe(true);
  });
  it("preselects the actual patient on a follow-up request", async () => {
    mockFetch();
    renderAuth(<AppRoutes />, "/orders/new?patient_id=42");
    expect(await screen.findByRole("combobox", { name: "Patient *" })).toHaveValue("42");
  });
  it("uses the selected reference unit and shows immutable result provenance", async () => {
    mockFetch(() => respond(page([{ ...result, status: "VERIFIED", reference_range: { normal_low: "1", normal_high: "10", unit: "mg/L" }, remarks: "Synthetic authorized remark", verified_at: "2026-10-17T09:00:00" }])));
    renderAuth(<Results order={order} reload={() => {}} />);
    expect(await screen.findByText("mg/L")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit draft" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Details & remarks"));
    expect(screen.getByText("Synthetic authorized remark")).toBeVisible();
    expect(screen.getByText("Verified · read only")).toBeVisible();
  });
  it("handles list errors and empty results with refresh", async () => {
    let fails = true;
    mockFetch(() => fails ? respond({ detail: "PRIVATE_SQL" }, 503) : respond(page([])));
    renderAuth(<AppRoutes />, "/orders");
    expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE_SQL");
    fails = false;
    await userEvent.click(screen.getByRole("button", { name: "Refresh orders" }));
    expect(await screen.findByText("No records found.")).toBeVisible();
  });
});

describe("official PDF preview", () => {
  it.each(["RELEASED", "REVOKED"])("previews stored %s bytes and releases its object URL", async status => {
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-pdf");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch(p => p === "/api/v1/reports/1/pdf" ? new Response("%PDF-synthetic", { headers: { "Content-Type": "application/pdf" } }) : undefined);
    renderAuth(<ReportActions report={{ ...released, report_status: status }} done={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview PDF" }));
    expect(await screen.findByTitle("Official laboratory report PDF")).toHaveAttribute("src", "blob:synthetic-pdf");
    expect(createUrl).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith("/api/v1/reports/1/pdf", expect.objectContaining({ credentials: "include", cache: "no-store", method: "GET" }));
    await userEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(revoke).toHaveBeenCalledWith("blob:synthetic-pdf");
  });
  it.each(["GENERATED", "APPROVED"])("does not offer final PDF actions for %s", async status => {
    mockFetch();
    renderAuth(<ReportActions report={{ ...report, report_status: status }} done={() => {}} />);
    await screen.findByText(/official snapshot|Approved for release/);
    expect(screen.queryByRole("button", { name: "Preview PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download PDF" })).not.toBeInTheDocument();
  });
  it("requires download permission independently of report read", async () => {
    mockFetch(undefined, staff(["REPORT_READ"]));
    renderAuth(<ReportActions report={released} done={() => {}} />);
    await screen.findByText(/Released report/);
    expect(screen.queryByRole("button", { name: "Preview PDF" })).not.toBeInTheDocument();
  });
  it("handles integrity rejection without exposing details", async () => {
    mockFetch(() => respond({ detail: "PRIVATE_HASH_AND_PATH" }, 409));
    renderAuth(<ReportActions report={released} done={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview PDF" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).not.toHaveTextContent("PRIVATE_HASH_AND_PATH");
    expect(screen.queryByTitle("Official laboratory report PDF")).not.toBeInTheDocument();
  });
  it("cancels a pending preview on close", async () => {
    let resolve!: (value: Response) => void;
    let signal: AbortSignal | null | undefined;
    const createUrl = vi.spyOn(URL, "createObjectURL");
    mockFetch((_, o) => { signal = o.signal; return new Promise<Response>(r => { resolve = r; }); });
    renderAuth(<ReportActions report={released} done={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview PDF" }));
    expect(within(screen.getByRole("dialog")).getByRole("status")).toHaveTextContent("Loading");
    await userEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => resolve(new Response("%PDF-synthetic")));
    expect(createUrl).not.toHaveBeenCalled();
  });
});
