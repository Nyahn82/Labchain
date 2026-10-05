import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { AppRoutes } from "../App";
import { presetRange } from "../pages/Analytics";
import { analyticsValue } from "../components/AnalyticsCharts";
import { admin, mockFetch, renderAuth, respond } from "./helpers";
import type { AnalyticsData, AnalyticsMetric } from "../types/analytics";

const base: AnalyticsData = {
  range: { date_from: "2026-10-01", date_to: "2026-10-07", previous_date_from: "2026-09-24", previous_date_to: "2026-09-30", timezone: "UTC", grain: "day", week_starts_on: "Monday" },
  metrics: [], series: [], breakdowns: [], turnaround: [], notes: [],
};
const metric = (key: string, label: string, value: number | null): AnalyticsMetric => ({ key, label, value, unit: "count", definition: "Test definition", previous_value: 0, absolute_change: value, percent_change: null, compared: false });
const trend = (key: string, label: string) => ({ key, label, definition: "UTC event counts", points: [{ bucket: "2026-10-01", value: 2 }, { bucket: "2026-10-02", value: 3 }] });
const group = (key: string, label: string, category: string) => ({ key, label, definition: "Current state", total: 5, other_count: 0, items: [{ key: "1", label: category, count: 5, share: 100, code: null, department: null, drafted: null, reviewed: null, verified: null }] });
const data: Record<string, AnalyticsData> = {
  overview: { ...base, metrics: [{ ...metric("orders", "Orders created", 5), compared: true }, { ...metric("patients_served", "Patients served", 2), compared: true, previous_value: 1, absolute_change: 1, percent_change: 100 }, { ...metric("tat", "Average TAT", null), unit: "seconds", compared: true, previous_value: null }] },
  patients: { ...base, series: [trend("new", "New patient registrations"), trend("served", "Patients served"), trend("returning", "Returning patients")] },
  orders: { ...base, series: [trend("orders", "Orders created")], breakdowns: [group("order_status", "Current order status", "COMPLETED")] },
  tests: { ...base, breakdowns: [group("top_tests", "Top requested tests", "Synthetic test"), { ...group("departments", "Department workload", "Chemistry"), items: [{ ...group("x","x","x").items[0], label: "Chemistry", drafted: 2, reviewed: 1, verified: 2 }] }] },
  specimens: { ...base, metrics: [metric("registered", "Specimens registered", 4)], breakdowns: [group("rejection_reasons", "Top rejection reasons", "Clotted")] },
  reports: { ...base, metrics: [metric("released", "Report versions released", 3)], turnaround: [{ key: "tat", label: "Order created → report released", definition: "Valid stages only", average_seconds: 86400, sample_count: 2, excluded_count: 1, candidate_count: 3 }] },
  operations: { ...base, breakdowns: [group("facilities", "Top referring facilities", "Referral Alpha"), group("weekday", "Order arrival pattern by weekday", "Monday")], metrics: [{ ...metric("amount", "Latest recorded amount", 150), unit: "amount" }] },
  system: { ...base, metrics: [metric("logins", "Successful logins", 3)], breakdowns: [group("anchors", "Current anchor status", "CONFIRMED")] },
};
function route(p: string) { return p.split("/analytics/")[1]?.split("?")[0]; }
function standard(p: string) { const name = route(p); if (name && data[name]) return respond(data[name]); }
function open() { renderAuth(<AppRoutes />, "/administration/analytics"); }

describe("Phase 11 analytics", () => {
  it("renders all operational sections, KPI comparisons and charts", async () => {
    mockFetch(standard); open();
    expect(await screen.findByRole("heading", { name: "Laboratory Analytics" })).toBeVisible();
    expect(await screen.findByText("Synthetic test")).toBeVisible();
    for (const text of ["Chemistry", "Clotted", "Referral Alpha", "Monday", "CONFIRMED", "Successful logins", "Latest recorded amount", "Report versions released"]) expect(screen.getByText(text)).toBeVisible();
    expect(screen.getByRole("article", { name: "Orders created" })).toHaveTextContent("No previous baseline");
    expect(screen.getByRole("article", { name: "Patients served" })).toHaveTextContent("+100%");
    expect(screen.getByRole("article", { name: "Average TAT" })).toHaveTextContent("No eligible samples");
    expect(screen.getByText("1 days")).toBeVisible();
    expect(screen.getByRole("link", { name: /^Analytics$/ })).toBeVisible();
  });
  it("provides keyboard-accessible SVG values and a data table equivalent", async () => {
    mockFetch(standard); open();
    const chart = await screen.findByRole("img", { name: "Returning patients" });
    expect(within(chart).getByLabelText("2026-10-01: 2")).toHaveAttribute("tabindex", "0");
    await userEvent.click(screen.getByText("View returning patients data table"));
    expect(screen.getByRole("region", { name: "Returning patients table" })).toBeVisible();
  });
  it("applies UTC presets and selected grain to every independent endpoint", async () => {
    const fetch = mockFetch(standard); open();
    await userEvent.selectOptions(await screen.findByLabelText("Date range"), "This Quarter");
    await userEvent.selectOptions(screen.getByLabelText("Group by"), "month");
    await userEvent.click(screen.getByRole("button", { name: "Apply range" }));
    const expected = presetRange("This Quarter");
    for (const section of Object.keys(data)) expect(fetch.mock.calls.some(([p]) => p.includes(`/analytics/${section}?date_from=${expected.date_from}&date_to=${expected.date_to}&grain=month`))).toBe(true);
  });
  it("accepts custom ranges and rejects reversed dates without refetch", async () => {
    const fetch = mockFetch(standard); open(); await screen.findByLabelText("From (UTC)");
    fireEvent.change(screen.getByLabelText("From (UTC)"), { target: { value: "2026-01-01" } });
    fireEvent.change(screen.getByLabelText("Through (UTC)"), { target: { value: "2026-03-31" } });
    await userEvent.click(screen.getByRole("button", { name: "Apply range" }));
    expect(fetch.mock.calls.some(([p]) => p.includes("date_from=2026-01-01&date_to=2026-03-31"))).toBe(true);
    fireEvent.change(screen.getByLabelText("Through (UTC)"), { target: { value: "2025-01-01" } });
    const before = fetch.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Apply range" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a valid start and end date");
    expect(fetch.mock.calls.length).toBe(before);
  });
  it("isolates partial failures and provides a retry", async () => {
    mockFetch(p => route(p) === "tests" ? respond({ detail: "Unavailable" }, 503) : standard(p)); open();
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(await screen.findByText("Clotted")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry test demand & department workload" })).toBeVisible();
  });
  it("shows loading until sections arrive", async () => {
    let resolve!: (r: Response) => void;
    mockFetch(p => route(p) === "overview" ? new Promise<Response>(r => { resolve = r; }) : standard(p)); open();
    await screen.findByRole("heading", { name: "Laboratory Analytics" });
    expect(screen.getAllByText("Loading records…").length).toBeGreaterThan(0);
    resolve(respond(data.overview)); expect(await screen.findByRole("article", { name: "Orders created" })).toBeVisible();
  });
  it("renders deliberate empty states and never NaN or Infinity", async () => {
    mockFetch(p => {
      const name = route(p); if (!name || !data[name]) return undefined;
      const source=data[name]; return respond({ ...source, metrics: source.metrics.map(m => ({ ...m, value: m.unit === "seconds" ? null : 0, percent_change: null })),
        series: source.series.map(s => ({ ...s, points: s.points.map(v => ({ ...v, value: 0 })) })),
        breakdowns: source.breakdowns.map(b => ({ ...b, total: 0, items: [] })), turnaround: [] });
    }); open();
    for (const text of ["No orders in this period", "No specimen activity in this period", "No released reports in this period"]) expect(await screen.findByText(text)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|Infinity/);
    expect(within(screen.getByRole("article", { name: "Orders created" })).getByText("0")).toBeVisible();
  });
  it("denies unauthorized staff and hides navigation before private requests", async () => {
    const fetch=mockFetch(standard, { ...admin, roles:["LAB_STAFF"], permissions:["ACCOUNT_READ"] }); open();
    expect(await screen.findByRole("heading", { name:"Permission required" })).toBeVisible();
    expect(screen.queryByRole("link", { name:"Analytics" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/analytics/"))).toBe(false);
  });
  it("permits ANALYTICS_VIEW staff but hides unrelated drilldowns", async () => {
    mockFetch(standard, { ...admin, roles:["LAB_STAFF"], permissions:["ANALYTICS_VIEW"] }); open();
    expect(await screen.findByText("Synthetic test")).toBeVisible();
    expect(screen.queryByRole("link", { name:"Blockchain Monitor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name:"Authentication Activity" })).not.toBeInTheDocument();
  });
  it("redirects patients without fetching analytics", async () => {
    const fetch=mockFetch(standard, { ...admin, roles:["PATIENT"], permissions:["ANALYTICS_VIEW"] }); open();
    await screen.findAllByText(/patient|Patient/);
    expect(fetch.mock.calls.some(([p]) => p.includes("/analytics/"))).toBe(false);
  });
  it.each([
    ["Today","2026-10-07"],["Last 7 Days","2026-10-01"],["This Week","2026-10-05"],
    ["Last 30 Days","2026-09-08"],["This Month","2026-10-01"],["This Quarter","2026-10-01"],["This Year","2026-01-01"],
  ])("%s uses UTC calendar semantics", (preset, expected) => {
    expect(presetRange(preset,new Date("2026-10-07T23:30:00Z"))).toEqual({date_from:expected,date_to:"2026-10-07"});
  });
  it("formats durations and guards nonfinite numbers", () => {
    expect(analyticsValue(120,"seconds")).toBe("2 min");
    expect(analyticsValue(7200,"seconds")).toBe("2 hours");
    expect(analyticsValue(null)).toBe("—");
    expect(analyticsValue(Number.POSITIVE_INFINITY)).toBe("—");
  });
});
