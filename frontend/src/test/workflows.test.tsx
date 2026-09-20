import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { AppRoutes } from "../App";
import { ResourcePage } from "../pages/ResourcePage";
import { resources } from "../pages/resources";
import { SpecimenActions, RegisterSpecimen } from "../pages/Specimens";
import { ResultActions, ResultForm, Results } from "../pages/Results";
import { ReportActions } from "../pages/Reports";
import { AccountEditor } from "../pages/People";
import { OrderDetail, CreateOrder } from "../pages/Orders";
import type { Specimen } from "../types/domain";
import {
  admin,
  mockFetch,
  renderAuth,
  respond,
  page,
  order,
  result,
  report,
} from "./helpers";
const patient = {
  patient_id: 1,
  patient_code: "P-001",
  first_name: "Test",
  last_name: "Patient",
  birth_date: "2000-01-01",
};
const specimen: Specimen = {
  specimen_id: 1,
  specimen_code: "SP-001",
  order_id: 1,
  specimen_status: "PENDING",
  sample_type: { sample_name: "Blood" },
  mappings: [],
  rejections: [],
};
async function ready() {
  await waitFor(() =>
    expect(screen.queryByText("Permission required")).not.toBeInTheDocument(),
  );
}
async function confirm(label: string) {
  await userEvent.click(await screen.findByRole("button", { name: label }));
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm " + label.toLowerCase() }),
  );
}
describe("patient directory", () => {
  it("renders the list and page controls", async () => {
    mockFetch(() => respond(page([patient], 22)));
    renderAuth(<ResourcePage resource={resources.patients} />);
    expect(await screen.findByText("P-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });
  it("requests pagination and search using supported query parameters", async () => {
    const fetch = mockFetch(() => respond(page([patient], 22)));
    renderAuth(<ResourcePage resource={resources.patients} />);
    await screen.findByText("P-001");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("page=2"),
        expect.anything(),
      ),
    );
    await userEvent.type(screen.getByLabelText("Search patients"), "P-001");
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("search=P-001"),
        expect.anything(),
      ),
    );
  });
  it("creates a patient from a labeled form", async () => {
    const fetch = mockFetch(() => respond(page([])));
    renderAuth(<ResourcePage resource={resources.patients} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "New patient" }),
    );
    await userEvent.type(screen.getByLabelText("Patient code *"), "P-002");
    await userEvent.type(screen.getByLabelText("First name *"), "Test");
    await userEvent.type(screen.getByLabelText("Last name *"), "Patient");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/patients",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"patient_code":"P-002"'),
        }),
      ),
    );
  });
  it("renders field validation errors safely", async () => {
    mockFetch((_, o) =>
      o?.method === "POST"
        ? respond(
            {
              detail: [
                {
                  loc: ["body", "patient_code"],
                  input: "secret",
                  msg: "SQL private",
                },
              ],
            },
            422,
          )
        : respond(page([])),
    );
    renderAuth(<ResourcePage resource={resources.patients} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "New patient" }),
    );
    for (const [label, v] of [
      ["Patient code *", "P-2"],
      ["First name *", "Test"],
      ["Last name *", "Patient"],
    ])
      await userEvent.type(screen.getByLabelText(label), v);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("patient_code");
    expect(screen.getByRole("alert")).not.toHaveTextContent("SQL");
  });
  it("handles backend 403 without exposing raw content", async () => {
    mockFetch(() => respond({ detail: "SQL failed" }, 403));
    renderAuth(<ResourcePage resource={resources.patients} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("permission");
    expect(screen.getByRole("alert")).not.toHaveTextContent("SQL");
  });
  it("renders API strings as text", async () => {
    mockFetch(() =>
      respond(
        page([{ ...patient, first_name: "<img src=x onerror=alert(1)>" }]),
      ),
    );
    const { container } = renderAuth(
      <ResourcePage resource={resources.patients} />,
    );
    expect(
      await screen.findByText("<img src=x onerror=alert(1)>"),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
describe("orders", () => {
  it("preserves panel and individual selections in create payload", async () => {
    const fetch = mockFetch((p, o) => {
      if (o?.method === "POST") return respond({ order_id: 2 });
      if (p.includes("/patients?")) return respond(page([patient]));
      if (p.includes("/lab/panels?"))
        return respond(page([{ panel_id: 1, panel_name: "Chemistry" }]));
      if (p.includes("/lab/tests?"))
        return respond(page([{ test_id: 1, test_name: "Glucose" }]));
      return respond(page([]));
    });
    renderAuth(
      <Routes>
        <Route path="/orders/new" element={<CreateOrder />} />
        <Route path="/orders/:id" element={<p>Order created</p>} />
      </Routes>,
      "/orders/new",
    );
    await screen.findByRole("option", { name: "Test Patient" });
    await userEvent.selectOptions(screen.getByLabelText("Patient *"), "1");
    await userEvent.click(await screen.findByLabelText("Chemistry"));
    await userEvent.click(screen.getByLabelText("Glucose"));
    await userEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect(await screen.findByText("Order created")).toBeInTheDocument();
    const call = fetch.mock.calls.find(([, o]) => o?.method === "POST")!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      patient_id: 1,
      physician_id: null,
      priority: "ROUTINE",
      request_reason: null,
      clinical_notes: null,
      diagnosis: null,
      panel_ids: [1],
      test_ids: [1],
    });
  });
  it("renders order details, provenance, and cancellation confirmation", async () => {
    const fetch = mockFetch((p) =>
      p === "/api/v1/lab-orders/1" ? respond(order) : respond(page([])),
    );
    renderAuth(
      <Routes>
        <Route path="/orders/:id" element={<OrderDetail />} />
      </Routes>,
      "/orders/1",
    );
    expect(await screen.findByText("ORD-001")).toBeInTheDocument();
    expect(screen.getByText("Glucose")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel order" }));
    expect(fetch.mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
    await userEvent.type(
      screen.getByLabelText("Cancellation reason"),
      "Duplicate request",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm cancel order" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/lab-orders/1/cancel",
        expect.objectContaining({ body: '{"reason":"Duplicate request"}' }),
      ),
    );
  });
});
describe("specimen lifecycle", () => {
  it.each([
    ["PENDING", "Collect specimen"],
    ["COLLECTED", "Receive specimen"],
    ["RECEIVED", "Reject specimen"],
  ])("shows appropriate action for %s", async (status, label) => {
    mockFetch();
    renderAuth(
      <SpecimenActions
        specimen={{ ...specimen, specimen_status: status }}
        orderOpen
        done={() => {}}
      />,
    );
    expect(
      await screen.findByRole("button", { name: label }),
    ).toBeInTheDocument();
    if (status !== "PENDING")
      expect(
        screen.queryByRole("button", { name: "Collect specimen" }),
      ).not.toBeInTheDocument();
  });
  it.each(["REJECTED", "PROCESSED"])("keeps %s immutable", async (status) => {
    mockFetch();
    renderAuth(
      <SpecimenActions
        specimen={{ ...specimen, specimen_status: status }}
        orderOpen
        done={() => {}}
      />,
    );
    await ready();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it.each([
    ["PENDING", "Collect specimen", "collect"],
    ["COLLECTED", "Receive specimen", "receive"],
  ])(
    "executes %s transition only after confirmation",
    async (status, label, endpoint) => {
      const fetch = mockFetch();
      renderAuth(
        <SpecimenActions
          specimen={{ ...specimen, specimen_status: status }}
          orderOpen
          done={() => {}}
        />,
      );
      await confirm(label);
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/specimens/1/" + endpoint,
        expect.objectContaining({ method: "POST" }),
      );
    },
  );
  it("registers only chosen current-order items", async () => {
    const fetch = mockFetch((p) =>
      p.includes("/lab/sample-types")
        ? respond(page([{ sample_type_id: 2, sample_name: "Blood" }]))
        : respond({}),
    );
    renderAuth(<RegisterSpecimen order={order} done={() => {}} />);
    await screen.findByRole("option", { name: "Blood" });
    await userEvent.selectOptions(screen.getByLabelText("Sample type *"), "2");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(
      screen.getByRole("button", { name: "Register specimen" }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/lab-orders/1/specimens",
      expect.objectContaining({
        body: '{"sample_type_id":2,"order_item_ids":[1],"remarks":null}',
      }),
    );
  });
  it("rejects with active reason, details, and recollection flag", async () => {
    const fetch = mockFetch((p) =>
      p.includes("/lab/rejection-reasons")
        ? respond(page([{ rejection_reason_id: 2, reason_name: "Clotted" }]))
        : respond({}),
    );
    renderAuth(
      <SpecimenActions
        specimen={{ ...specimen, specimen_status: "RECEIVED" }}
        orderOpen
        done={() => {}}
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Reject specimen" }),
    );
    await screen.findByRole("option", { name: "Clotted" });
    await userEvent.selectOptions(
      screen.getByLabelText("Rejection reason *"),
      "2",
    );
    await userEvent.type(
      screen.getByLabelText("Rejection details"),
      "Clot present",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm reject specimen" }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/specimens/1/reject",
      expect.objectContaining({
        body: '{"rejection_reason_id":2,"details":"Clot present","recollection_required":true}',
      }),
    );
    expect(fetch.mock.calls.some(([p]) => p.includes("is_active=true"))).toBe(
      true,
    );
  });
});
describe("results", () => {
  it("submits decimal result strings without server-derived fields", async () => {
    const fetch = mockFetch((p) =>
      p === "/api/v1/lab/tests/1" ? respond(result.test) : respond({}),
    );
    renderAuth(
      <ResultForm order={order} item={order.items[0]} done={() => {}} />,
    );
    await userEvent.type(
      await screen.findByLabelText("Result value *"),
      "0.100",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/lab-order-items/1/result",
      expect.objectContaining({
        body: '{"result_value":"0.100","specimen_id":null,"remarks":null}',
      }),
    );
  });
  it("edits only draft allowlisted values", async () => {
    const fetch = mockFetch();
    renderAuth(
      <ResultForm
        order={order}
        item={order.items[0]}
        result={result}
        done={() => {}}
      />,
    );
    await userEvent.clear(screen.getByLabelText("Result value *"));
    await userEvent.type(screen.getByLabelText("Result value *"), "5.200");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/results/1",
      expect.objectContaining({
        method: "PATCH",
        body: '{"result_value":"5.200","specimen_id":null,"remarks":null}',
      }),
    );
  });
  it.each([
    ["DRAFT", "Review result", "review"],
    ["REVIEWED", "Verify result", "verify"],
  ])("confirms result %s transition", async (status, label, endpoint) => {
    const fetch = mockFetch();
    renderAuth(
      <ResultActions
        result={{ ...result, status }}
        done={() => {}}
        onEdit={() => {}}
      />,
    );
    await confirm(label);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/results/1/" + endpoint,
      expect.objectContaining({ method: "POST" }),
    );
  });
  it("makes verified results read only", async () => {
    mockFetch();
    renderAuth(
      <ResultActions
        result={{ ...result, status: "VERIFIED" }}
        done={() => {}}
        onEdit={() => {}}
      />,
    );
    expect(screen.getByText("Verified · read only")).toBeInTheDocument();
    await ready();
    expect(
      screen.queryByRole("button", { name: "Edit draft" }),
    ).not.toBeInTheDocument();
  });
  it("displays backend-calculated flags", async () => {
    mockFetch(() => respond(page([result])));
    renderAuth(<Results order={order} reload={() => {}} />);
    expect(await screen.findByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("5.100")).toBeInTheDocument();
  });
});
describe("report lifecycle", () => {
  it.each([
    ["GENERATED", "Assign signatory"],
    ["APPROVED", "Release report"],
    ["RELEASED", "Revoke report"],
    ["REVOKED", "Download PDF"],
  ])("shows valid %s actions", async (status, label) => {
    mockFetch();
    renderAuth(
      <ReportActions
        report={{ ...report, report_status: status }}
        done={() => {}}
      />,
    );
    expect(
      await screen.findByRole("button", { name: label }),
    ).toBeInTheDocument();
    if (status !== "GENERATED")
      expect(
        screen.queryByRole("button", { name: "Assign signatory" }),
      ).not.toBeInTheDocument();
    if (status === "REVOKED")
      expect(
        screen.queryByRole("button", { name: "Revoke report" }),
      ).not.toBeInTheDocument();
  });
  it("signs only the current staff assignment", async () => {
    const fetch = mockFetch();
    renderAuth(<ReportActions report={report} done={() => {}} />);
    await confirm("Sign as MEDICAL TECHNOLOGIST");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/reports/1/sign",
      expect.objectContaining({ body: '{"report_signatory_id":1}' }),
    );
  });
  it("does not allow signing another staff member’s assignment", async () => {
    mockFetch(undefined, {
      ...admin,
      staff: { staff_id: 99, first_name: "Other", last_name: "Staff" },
    });
    renderAuth(<ReportActions report={report} done={() => {}} />);
    await screen.findByRole("button", { name: "Assign signatory" });
    expect(
      screen.queryByRole("button", { name: /Sign as/ }),
    ).not.toBeInTheDocument();
  });
  it.each([
    ["GENERATED", "Approve report", "approve"],
    ["APPROVED", "Release report", "release"],
  ])("confirms %s transition", async (status, label, endpoint) => {
    const fetch = mockFetch();
    renderAuth(
      <ReportActions
        report={{
          ...report,
          report_status: status,
          signatories: [{ ...report.signatories[0], signed_at: "2026-01-01" }],
        }}
        done={() => {}}
      />,
    );
    await confirm(label);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/reports/1/" + endpoint,
      expect.objectContaining({ method: "POST" }),
    );
  });
  it("requires a reason and confirmation before revocation", async () => {
    const fetch = mockFetch();
    renderAuth(
      <ReportActions
        report={{ ...report, report_status: "RELEASED" }}
        done={() => {}}
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Revoke report" }),
    );
    expect(
      screen.getByRole("button", { name: "Confirm revoke report" }),
    ).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("Revocation reason"),
      "Correction required",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm revoke report" }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/reports/1/revoke",
      expect.objectContaining({ body: '{"reason":"Correction required"}' }),
    );
  });
  it("displays version and superseded report link", async () => {
    mockFetch(() => respond(report));
    renderAuth(<AppRoutes />, "/reports/1");
    expect(await screen.findByText("Version 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "report #8" })).toHaveAttribute(
      "href",
      "/reports/8",
    );
  });
});
describe("administration and dialogs", () => {
  const account = {
    user_id: 2,
    username: "operator",
    account_status: "ACTIVE",
    roles: ["STAFF"],
  };
  it("assigns selected role codes only after confirmation", async () => {
    const fetch = mockFetch((p) =>
      p.endsWith("/roles")
        ? respond([
            { role_code: "STAFF", role_name: "Staff", is_active: true },
            { role_code: "REVIEWER", role_name: "Reviewer", is_active: true },
          ])
        : respond({}),
    );
    renderAuth(
      <AccountEditor account={account} done={() => {}} can={() => true} />,
    );
    await userEvent.click(await screen.findByLabelText(/Reviewer/));
    await confirm("Replace roles");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/users/2/roles",
      expect.objectContaining({ body: '{"role_codes":["STAFF","REVIEWER"]}' }),
    );
  });
  it("confirms account disable", async () => {
    const fetch = mockFetch(() => respond([]));
    renderAuth(
      <AccountEditor account={account} done={() => {}} can={() => true} />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText("New account status"),
      "INACTIVE",
    );
    await confirm("Update account status");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/users/2/status",
      expect.objectContaining({ body: '{"account_status":"INACTIVE"}' }),
    );
  });
  it("hides unauthorized MFA reset", () => {
    mockFetch();
    renderAuth(
      <AccountEditor account={account} done={() => {}} can={() => false} />,
    );
    expect(
      screen.queryByRole("button", { name: "Reset MFA" }),
    ).not.toBeInTheDocument();
  });
  it("confirms authorized MFA reset in labeled dialog", async () => {
    const fetch = mockFetch(() => respond([]));
    renderAuth(
      <AccountEditor account={account} done={() => {}} can={() => true} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset MFA" }));
    const dialog = screen.getByRole("dialog", { name: "Reset MFA" });
    expect(within(dialog).getByText(/Remove this account/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/mfa/reset"))).toBe(
      false,
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Confirm reset mfa" }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/users/2/mfa/reset",
      expect.objectContaining({ method: "POST" }),
    );
  });
  it("supports keyboard activation and restores focus on dialog close", async () => {
    mockFetch(() => respond([]));
    renderAuth(
      <AccountEditor
        account={account}
        done={() => {}}
        can={(p) => p === "ACCOUNT_MFA_RESET"}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Reset MFA" });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    expect(
      screen.getByRole("dialog", { name: "Reset MFA" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
