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
      "Dashboard", "Patients", "Laboratory orders", "Specimens", "Results", "Reports",
      "Analytics", "Authentication Activity", "Blockchain Monitor", "Laboratory setup",
      "Physicians", "Referring facilities", "Staff", "Accounts and roles",
    ]);
    expect(within(nav).getAllByRole("heading").map(h => h.textContent)).toEqual(["Overview", "Laboratory", "Administration"]);
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
    ["ANALYTICS_VIEW", "Analytics"], ["AUTH_ACTIVITY_VIEW", "Authentication Activity"],
    ["SESSION_MANAGE", "Authentication Activity"], ["BLOCKCHAIN_EXPLORER_VIEW", "Blockchain Monitor"],
    ["ROLE_READ", "Accounts and roles"], ["REJECTION_REASON_MANAGE", "Laboratory setup"],
  ])("preserves %s visibility without an empty laboratory heading", async (permission, label) => {
    const nav = await navigation([permission]);
    expect(within(nav).getAllByRole("link").map(l => l.textContent)).toEqual(["Dashboard", label]);
    expect(within(nav).queryByRole("heading", { name: "Laboratory" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("heading", { name: "Administration" })).toBeVisible();
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
