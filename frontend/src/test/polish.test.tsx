import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Badge } from "../components/UI";
import { AppRoutes } from "../App";
import { admin, mockFetch, renderAuth } from "./helpers";

async function navigation(permissions?: string[]) {
  mockFetch(undefined, permissions ? { ...admin, roles: ["LAB_STAFF"], permissions } : admin);
  renderAuth(<AppRoutes />, "/dashboard");
  return await screen.findByRole("navigation", { name: "Main navigation" });
}
describe("Phase 12A workflow navigation", () => {
  it("puts Dashboard first, daily work second, and administration last", async () => {
    const nav = await navigation();
    expect(within(nav).getAllByRole("link").map(link => link.textContent)).toEqual([
      "Dashboard", "Analytics", "Patients", "Physicians", "Referring facilities",
      "Laboratory orders", "Specimens", "Results", "Reports", "Scan report QR",
    ]);
    expect(within(nav).getAllByRole("heading").map(h => h.textContent)).toEqual(["Overview", "Patients", "Laboratory", "Reports", "Configuration", "Administration"]);
    await userEvent.click(within(nav).getByRole("button", { name: "Configuration" }));
    expect(within(nav).getByRole("link", { name: "Laboratory setup" })).toBeVisible();
    await userEvent.click(within(nav).getByRole("button", { name: "Administration" }));
    expect(within(nav).getByRole("link", { name: "Accounts and roles" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Laboratory overview" })).toBeVisible();
  });
  it("omits empty administration and its restricted links", async () => {
    const nav = await navigation(["PATIENT_READ"]);
    expect(within(nav).queryByRole("heading", { name: "Administration" })).not.toBeInTheDocument();
    for (const name of ["Analytics", "Authentication Activity", "Blockchain Monitor"]) {
      expect(within(nav).queryByRole("link", { name })).not.toBeInTheDocument();
    }
    expect(within(nav).getAllByRole("link")).toHaveLength(2);
  });
  it.each([
    ["ANALYTICS_VIEW", "Analytics", "Overview"], ["AUTH_ACTIVITY_VIEW", "Authentication Activity", "Administration"],
    ["SESSION_MANAGE", "Authentication Activity", "Administration"], ["BLOCKCHAIN_EXPLORER_VIEW", "Blockchain Monitor", "Administration"],
    ["ROLE_READ", "Accounts and roles", "Administration"], ["REJECTION_REASON_MANAGE", "Laboratory setup", "Configuration"],
  ])("preserves %s visibility without an empty laboratory heading", async (permission, label, group) => {
    const nav = await navigation([permission]);
    const toggle = within(nav).getByRole("button", { name: group });
    if (toggle.getAttribute("aria-expanded") === "false") await userEvent.click(toggle);
    expect(within(nav).getAllByRole("link").map(l => l.textContent)).toEqual(["Dashboard", label]);
    expect(within(nav).queryByRole("heading", { name: "Laboratory" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("heading", { name: group })).toBeVisible();
  });
  it("supports the mobile toggle, Escape and focus return", async () => {
    const nav = await navigation(["PATIENT_READ"]);
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    expect(toggle).toHaveAttribute("aria-controls", nav.id);
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    within(nav).getByRole("link", { name: "Patients" }).focus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });
  it("keeps all permitted destinations accessible in the compact sidebar", async () => {
    const nav = await navigation();
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).getByRole("link", { name: "Accounts and roles" })).toHaveAttribute("href", "/administration");
    await userEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(within(nav).queryByRole("link", { name: "Accounts and roles" })).not.toBeInTheDocument();
  });
  it("does not expose the staff scanner to report readers without download access", async () => {
    const nav = await navigation(["REPORT_READ"]);
    expect(within(nav).getByRole("link", { name: "Reports" })).toBeVisible();
    expect(within(nav).queryByRole("link", { name: "Scan report QR" })).not.toBeInTheDocument();
  });
  it("does not mark Accounts and roles active on a monitoring page", async () => {
    mockFetch(); renderAuth(<AppRoutes />, "/administration/activity");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Authentication Activity" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Accounts and roles" })).not.toHaveAttribute("aria-current");
  });
});

describe("shared domain status semantics", () => {
  it("keeps boolean Active healthy and Inactive neutral with visible labels", () => {
    render(<><Badge>{true}</Badge><Badge>{false}</Badge><Badge>REJECTED</Badge><Badge>PENDING</Badge><Badge>UNKNOWN</Badge></>);
    expect(screen.getByText("Active")).toHaveClass("status-success");
    expect(screen.getByText("Inactive")).toHaveClass("status-neutral");
    expect(screen.getByText("REJECTED")).toHaveClass("status-danger");
    expect(screen.getByText("PENDING")).toHaveClass("status-warning");
    expect(screen.getByText("UNKNOWN")).toHaveClass("status-neutral");
  });
});
