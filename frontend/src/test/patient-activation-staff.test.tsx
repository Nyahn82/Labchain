import { StrictMode } from "react";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { admin, mockFetch, page, renderAuth, respond } from "./helpers";

const patient = { patient_id: 1, patient_code: "PAT-000123", first_name: "Synthetic", last_name: "Patient" };
const issued = { activation_token: "synthetic-one-time-invitation", patient_code: patient.patient_code, expires_at: "2027-01-01T00:00:00" };
function handler(state: () => string = () => "NOT_ACTIVATED") {
  return (p: string) => {
    if (p.endsWith("/activation-status")) return respond({ status: state() });
    if (p === "/api/v1/patients/1") return respond({ ...patient, activation_status: state() });
    if (p.startsWith("/api/v1/patients?")) return respond(page([{ ...patient, activation_status: state() }]));
  };
}
async function confirm() {
  await userEvent.click(await screen.findByRole("button", { name: /^(Issue|Reissue) activation invitation$/ }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm issue invitation" }));
}
const staff = (permissions: string[]) => ({ ...admin, roles: ["LAB_STAFF"], permissions });

describe("staff patient activation", () => {
  it.each([
    ["NOT_ACTIVATED", "No portal account", true],
    ["TOKEN_ACTIVE", "Awaiting activation", true],
    ["TOKEN_EXPIRED", "Invitation expired", true],
    ["TOKEN_REVOKED", "Invitation revoked", true],
    ["ACTIVATED", "Portal activated", false],
    ["REVIEW_REQUIRED", "Account review required", false],
    ["UNKNOWN", "Status unavailable", false],
  ])("renders %s with only supported actions", async (status, label, allowed) => {
    mockFetch(handler(() => String(status)));
    renderAuth(<AppRoutes />, "/patients/1");
    expect(await screen.findByText(String(label))).toBeVisible();
    expect(!!screen.queryByRole("button", { name: /^(Issue|Reissue) activation invitation$/ })).toBe(allowed);
    expect(screen.getByText(patient.patient_code)).toBeVisible();
  });

  it("issues with CSRF, refreshes status and clears the token on close, including StrictMode", async () => {
    let status = "NOT_ACTIVATED";
    const normal = handler(() => status);
    const fetch = mockFetch((p, o) => {
      if (p.endsWith("/activation-token") && o.method === "POST") {
        status = "TOKEN_ACTIVE";
        return respond(issued, 201);
      }
      return normal(p);
    });
    const storage = vi.spyOn(Storage.prototype, "setItem");
    document.cookie = "rhu_csrf=synthetic-csrf; path=/";
    renderAuth(<StrictMode><AppRoutes /></StrictMode>, "/patients/1");
    await confirm();
    expect(await screen.findByLabelText("One-time activation token")).toHaveValue(issued.activation_token);
    expect(screen.getByText(/No email or SMS has been sent/)).toBeVisible();
    expect(screen.getByRole("link", { name: "patient activation page" })).toHaveAttribute("href", "/patient/activate");
    expect(fetch.mock.calls.filter(([p, o]) => p.endsWith("/activation-token") && o?.method === "POST")).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/patients/1/activation-token", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ "X-CSRF-Token": "synthetic-csrf" }), cache: "no-store", credentials: "include", body: undefined,
    }));
    expect(storage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Done — hide token" }));
    expect(screen.queryByDisplayValue(issued.activation_token)).not.toBeInTheDocument();
    expect(await screen.findByText("Awaiting activation", { selector: ".activation-badge" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Reissue activation invitation" }));
    expect(screen.queryByDisplayValue(issued.activation_token)).not.toBeInTheDocument();
    expect(screen.getByText(/Any previous unused invitation/)).toBeVisible();
  });

  it.each([403, 409, 503])("handles issuance failure %s without revealing server details or retrying blindly", async status => {
    const normal = handler();
    mockFetch((p, o) => o.method === "POST" ? respond({ detail: "PRIVATE-SECRET" }, status) : normal(p));
    renderAuth(<AppRoutes />, "/patients/1");
    await confirm();
    expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE-SECRET");
    expect(screen.getByRole("button", { name: "Confirm issue invitation" })).toBeDisabled();
    expect(screen.queryByLabelText("One-time activation token")).not.toBeInTheDocument();
  });

  it("exposes no staff activation UI or fetch without the separate permission", async () => {
    const fetch = mockFetch(handler(), staff(["PATIENT_READ"]));
    renderAuth(<AppRoutes />, "/patients/1");
    await screen.findByText(patient.patient_code);
    expect(screen.queryByRole("heading", { name: "Patient activation" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("activation-"))).toBe(false);
  });

  it("hides staff activation controls from a patient-linked administrator", async () => {
    const fetch = mockFetch(handler(), { ...admin, patient: { patient_id: 2 } });
    renderAuth(<AppRoutes />, "/patients/1");
    await screen.findByText(patient.patient_code);
    expect(screen.queryByRole("heading", { name: "Patient activation" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("activation-"))).toBe(false);
  });

  it("lets account readers inspect states without issuing invitations", async () => {
    mockFetch(handler(() => "TOKEN_EXPIRED"), staff(["PATIENT_READ", "ACCOUNT_READ"]));
    renderAuth(<AppRoutes />, "/patients/1");
    expect(await screen.findByText("Invitation expired")).toBeVisible();
    expect(screen.queryByRole("button", { name: /activation invitation/ })).not.toBeInTheDocument();
  });

  it("shows loading and a retryable unavailable state without inventing activation status", async () => {
    let resolve!: (value: Response) => void;
    const normal = handler();
    mockFetch(p => p.endsWith("/activation-status") ? new Promise<Response>(r => { resolve = r; }) : normal(p));
    renderAuth(<AppRoutes />, "/patients/1");
    const region = await screen.findByRole("region", { name: "Patient activation" });
    expect(within(region).getByText("Loading records…")).toBeVisible();
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    await act(async () => resolve(respond({ detail: "PRIVATE-SECRET" }, 503)));
    expect(await within(region).findByRole("alert")).not.toHaveTextContent("PRIVATE-SECRET");
    expect(screen.queryByText("No portal account")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh activation status" })).toBeEnabled();
  });

  it("refreshes directory status after activation elsewhere and preserves the generated code", async () => {
    let status = "TOKEN_ACTIVE";
    mockFetch(handler(() => status));
    renderAuth(<AppRoutes />, "/patients");
    expect(await screen.findByText("Awaiting activation")).toBeVisible();
    status = "ACTIVATED";
    await userEvent.click(screen.getByRole("button", { name: "Refresh patients" }));
    expect(await screen.findByText("Portal activated", { selector: ".activation-badge" })).toBeVisible();
    expect(screen.getByText(patient.patient_code)).toBeVisible();
    await userEvent.click(screen.getByRole("link", { name: "Open" }));
    expect(await screen.findByRole("heading", { name: "Patient activation" })).toBeVisible();
    expect(await screen.findByText("Portal activated")).toBeVisible();
  });

  it("omits the directory status column for patient readers without account permissions", async () => {
    mockFetch(handler(), staff(["PATIENT_READ"]));
    renderAuth(<AppRoutes />, "/patients");
    await screen.findByText(patient.patient_code);
    expect(screen.queryByRole("columnheader", { name: "Portal activation" })).not.toBeInTheDocument();
  });

  it("clears a visible token when the page becomes hidden", async () => {
    const normal = handler();
    mockFetch((p, o) => o.method === "POST" ? respond(issued, 201) : normal(p));
    renderAuth(<AppRoutes />, "/patients/1");
    await confirm();
    await screen.findByLabelText("One-time activation token");
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(screen.queryByDisplayValue(issued.activation_token)).not.toBeInTheDocument();
  });

  it("aborts issuance on navigation and never renders a late token response", async () => {
    let resolve!: (value: Response) => void;
    let signal: AbortSignal | null | undefined;
    const normal = handler();
    mockFetch((p, o) => {
      if (o.method === "POST") { signal = o.signal; return new Promise<Response>(r => { resolve = r; }); }
      return normal(p);
    });
    renderAuth(<AppRoutes />, "/patients/1");
    await confirm();
    expect(screen.getByRole("button", { name: "Issuing invitation…" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("link", { name: "All patients" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => resolve(respond(issued, 201)));
    expect(screen.queryByDisplayValue(issued.activation_token)).not.toBeInTheDocument();
  });
});
