import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { admin, mockFetch, page, renderAuth, respond } from "./helpers";

const account = { user_id: 2, username: "portal-user", account_status: "ACTIVE", roles: ["PATIENT"], staff: null,
  patient: { patient_id: 1, first_name: "Synthetic", last_name: "Patient" }, last_login_at: "2026-10-01T00:00:00", created_at: "2026-09-01T00:00:00" };
const activity = { activity_id: "login:1", user_id: 2, username: "portal-user", account_type: "PATIENT", display_name: "Synthetic Patient", activity_type: "LOGIN_SUCCESS", occurred_at: "2026-10-01T00:00:00", status: "SUCCESS", ip_address: "192.0.2.1", user_agent: null, token_hash: "NEVER-RENDER" };
const session = { session_id: 5, user_id: 2, username: "portal-user", account_type: "PATIENT", display_name: "Synthetic Patient", created_at: "2026-10-01T00:00:00", expires_at: "2026-10-02T00:00:00", state: "ACTIVE", is_current: false, user_agent: "Synthetic UA <script>text</script>", token_hash: "NEVER-RENDER" };
function standard(p: string) {
  if (p === "/api/v1/roles") return respond([]);
  if (p === "/api/v1/users/2") return respond(account);
  if (p.includes("/auth-activity?")) return respond(page([activity]));
  if (p.includes("/sessions?")) return respond(page([session]));
}
function open(route = "/administration/activity") { renderAuth(<AppRoutes />, route); }

describe("Phase 10 account access administration", () => {
  it("shows navigation and safe activity data", async () => {
    mockFetch(standard); open();
    expect(await screen.findByRole("heading", { name: "Authentication Activity" })).toBeVisible();
    expect(await screen.findByText("LOGIN SUCCESS")).toBeVisible();
    expect(screen.getByRole("link", { name: "Blockchain Monitor" })).toBeVisible();
    expect(document.body).not.toHaveTextContent("NEVER-RENDER");
  });
  it("filters staff, patients and failed logins", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); open();
    await user.click(await screen.findByRole("tab", { name: /^Staff$/ }));
    expect(fetch.mock.calls.some(([p]) => p.includes("account_type=STAFF"))).toBe(true);
    await user.click(screen.getByRole("tab", { name: /^Patients$/ }));
    expect(fetch.mock.calls.some(([p]) => p.includes("account_type=PATIENT"))).toBe(true);
    await user.click(screen.getByRole("tab", { name: "Failed Logins" }));
    expect(fetch.mock.calls.some(([p]) => p.includes("activity_type=LOGIN_FAILED"))).toBe(true);
    expect(screen.getByLabelText("Activity")).toBeDisabled();
  });
  it("applies bounded search, date and outcome filters", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); open();
    await user.type(await screen.findByLabelText("Search user"), "portal");
    await user.selectOptions(screen.getByLabelText("Outcome"), "FAILED");
    fireEvent.change(screen.getByLabelText("From (UTC)"), { target: { value: "2026-10-01T00:00" } });
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(fetch.mock.calls.some(([p]) => p.includes("search=portal") && p.includes("status=FAILED") && p.includes("date_from="))).toBe(true);
  });
  it("shows sessions, escaped user-agent and a CSRF-protected revoke action", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); open();
    await user.click(await screen.findByRole("tab", { name: "Active Sessions" }));
    await user.click(await screen.findByText("User-agent details"));
    expect(screen.getByText("Synthetic UA <script>text</script>")).toBeVisible();
    expect(document.body).not.toHaveTextContent("NEVER-RENDER");
    await user.click(screen.getByRole("button", { name: "Revoke Session" }));
    await user.click(screen.getByRole("button", { name: "Confirm revoke session" }));
    expect(fetch.mock.calls.some(([p, o]) => p.endsWith("/sessions/5/revoke") && o?.method === "POST")).toBe(true);
  });
  it("requires a reason and explains patient portal isolation", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); open("/administration/2");
    await user.click(await screen.findByRole("button", { name: "Suspend Portal Account" }));
    const dialog = screen.getByRole("dialog", { name: "Suspend Portal Account" });
    expect(within(dialog).getByText(/laboratory record and history remain available/)).toBeVisible();
    const submit = within(dialog).getByRole("button", { name: "Confirm suspend portal account" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Reason *"), "   ");
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Reason *"), "Review access");
    await user.click(submit);
    const call = fetch.mock.calls.find(([p]) => p.endsWith("/users/2/suspend"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reason: "Review access" });
  });
  it("reactivates only suspended accounts and displays metadata", async () => {
    const fetch = mockFetch(p => p === "/api/v1/users/2" ? respond({ ...account, account_status: "SUSPENDED", suspension_reason: "Review access", suspended_at: "2026-10-01T00:00:00", suspended_by_user_id: 1 }) : standard(p));
    const user = userEvent.setup(); open("/administration/2");
    await user.click(await screen.findByRole("button", { name: "Reactivate Account" }));
    expect(screen.getByText("Review access")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Confirm reactivate account" }));
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/users/2/reactivate"))).toBe(true);
  });
  it("shows explicit unlock instead of temporary reactivation", async () => {
    mockFetch(p => p === "/api/v1/users/2" ? respond({ ...account, account_status: "LOCKED" }) : standard(p));
    const user = userEvent.setup(); open("/administration/2");
    await user.selectOptions(await screen.findByLabelText("New account status"), "ACTIVE");
    expect(screen.getByRole("button", { name: "Unlock Account" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reactivate Account" })).not.toBeInTheDocument();
  });
  it("shows active count and bulk revoke in account detail", async () => {
    const fetch = mockFetch(standard); const user = userEvent.setup(); open("/administration/2");
    expect(await screen.findByText("Active Session Count: 1")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Recent authentication activity" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Log Out All Sessions" }));
    await user.click(screen.getByRole("button", { name: "Confirm log out all sessions" }));
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/users/2/sessions/revoke-all"))).toBe(true);
  });
  it("blocks unprivileged staff before fetching private records", async () => {
    const fetch = mockFetch(standard, { ...admin, roles: ["LAB_STAFF"], permissions: ["ACCOUNT_READ"] }); open();
    expect(await screen.findByRole("heading", { name: "Permission required" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Authentication Activity" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/admin/auth-activity") || p.includes("/admin/sessions"))).toBe(false);
  });
  it("allows view permission without mutation controls", async () => {
    mockFetch(standard, { ...admin, roles: ["LAB_STAFF"], permissions: ["AUTH_ACTIVITY_VIEW"] }); const user = userEvent.setup(); open();
    await user.click(await screen.findByRole("tab", { name: "Active Sessions" }));
    expect(await screen.findByText("portal-user")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revoke Session" })).not.toBeInTheDocument();
  });
  it("allows session-only administrators without fetching activity", async () => {
    const fetch = mockFetch(standard, { ...admin, roles: ["LAB_STAFF"], permissions: ["SESSION_MANAGE"] }); open();
    expect(await screen.findByRole("heading", { name: "Account sessions" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Failed Logins" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/auth-activity?"))).toBe(false);
  });
  it("redirects patient routes without fetching admin data", async () => {
    const fetch = mockFetch(standard, { ...admin, roles: ["PATIENT"], permissions: [] }); open();
    await screen.findAllByText(/patient|Patient/, {}, { timeout: 2000 });
    expect(fetch.mock.calls.some(([p]) => p.includes("/admin/auth-activity"))).toBe(false);
  });
  it("handles loading, empty and error states", async () => {
    let resolve!: (value: Response) => void;
    mockFetch(p => p.includes("/auth-activity?") ? new Promise<Response>(r => { resolve = r; }) : standard(p)); open();
    expect(await screen.findByText("Loading records…")).toBeVisible();
    resolve(respond(page([])));
    expect(await screen.findByText("No records found.")).toBeVisible();
  });
  it("shows request errors", async () => {
    mockFetch(p => p.includes("/auth-activity?") ? respond({ detail: "Unavailable" }, 503) : standard(p)); open();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server could not complete the request");
  });
});
