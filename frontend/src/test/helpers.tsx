import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { ReactNode } from "react";
import { AuthProvider } from "../auth/Auth";
import type { Order, Report, Result, User } from "../types/domain";
export const admin: User = {
  user_id: 1,
  username: "staff-demo",
  roles: ["SYSTEM_ADMIN"],
  permissions: [],
  staff: { staff_id: 1, first_name: "Test", last_name: "Staff" },
  patient: null,
};
export const order: Order = {
  order_id: 1,
  order_code: "ORD-001",
  status: "IN_PROGRESS",
  priority: "ROUTINE",
  patient: { patient_id: 1, first_name: "Test", last_name: "Patient" },
  physician: null,
  panels: [
    {
      order_panel_id: 10,
      panel: { panel_name: "Chemistry" },
      status: "REQUESTED",
    },
  ],
  items: [
    {
      order_item_id: 1,
      test_id: 1,
      test: { test_name: "Glucose", test_id: 1 },
      status: "IN_PROGRESS",
      order_panel_id: 10,
    },
  ],
  payments: [],
  specimens: [],
};
export const result: Result = {
  result_item_id: 1,
  order_item_id: 1,
  result_value: "5.100",
  status: "DRAFT",
  flag: "HIGH",
  test: {
    test_id: 1,
    test_name: "Glucose",
    result_type: "NUMERIC",
    default_unit: "mmol/L",
  },
  specimen_id: null,
  remarks: null,
};
export const report: Report = {
  report_id: 1,
  report_code: "RPT-001",
  order_id: 1,
  report_status: "GENERATED",
  version_no: 2,
  supersedes_report_id: 8,
  signatories: [
    {
      report_signatory_id: 1,
      signatory_type: "MEDICAL_TECHNOLOGIST",
      profile: { staff_id: 1 },
      signed_at: null,
    },
  ],
  result_snapshots: [],
  patient_snapshot: null,
};
export function page(items: unknown[], total = items.length) {
  return { items, total, page: 1, page_size: 20 };
}
export function respond(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
export function mockFetch(
  handler?: (
    path: string,
    options: RequestInit,
  ) => Response | Promise<Response> | undefined,
  user: User | null = admin,
) {
  const mock = vi.fn((input: string, options: RequestInit = {}) =>
    Promise.resolve(
      input === "/api/v1/auth/me"
        ? respond(user || {}, user ? 200 : 401)
        : handler?.(input, options) || respond(page([])),
    ),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}
export function renderAuth(node: ReactNode, route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>{node}</AuthProvider>
    </MemoryRouter>,
  );
}
