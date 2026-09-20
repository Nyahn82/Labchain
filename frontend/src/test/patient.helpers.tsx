import { vi } from "vitest";
import type { User } from "../types/domain";
import { AppRoutes } from "../App";
import { admin, mockFetch, page, renderAuth, respond } from "./helpers";
export const patientUser: User = {
  ...admin,
  user_id: 11,
  username: "patient-test",
  roles: ["PATIENT"],
  permissions: [],
  staff: null,
  patient: { patient_id: 4, first_name: "Sample", last_name: "Patient" },
};
export const security = {
  mfa_required: true,
  totp_enabled: true,
  mfa_verified_for_current_session: true,
  unused_recovery_codes: 8,
};
export const limited = {
  ...security,
  totp_enabled: false,
  mfa_verified_for_current_session: false,
  unused_recovery_codes: 0,
};
export const profile = {
  patient_id: 4,
  patient_code: "P-004",
  first_name: "Sample",
  last_name: "Patient",
  birth_date: "2000-02-03",
  sex: "F",
  civil_status: "Single",
  nationality: "Filipino",
  contact_number: "000-000",
  email: "patient@example.test",
  address: "Test address",
  password_hash: "MUST-NOT-SHOW",
};
export const summary = {
  report_id: 7,
  report_code: "RPT-007",
  version_no: 2,
  released_at: "2026-09-20T12:00:00Z",
  order_code: "ORD-007",
  issuing_facility: "Test Laboratory",
  verification_status: "AUTHENTIC",
};
export const detail = {
  ...summary,
  report_status: "RELEASED",
  generated_at: "2026-09-20T11:00:00Z",
  facility: { facility_name: "Test Laboratory" },
  patient_snapshot: {
    patient_name: "Sample Patient",
    patient_code: "P-004",
    physician_name: "Test Physician",
    birth_date: "2000-02-03",
    sex: "F",
  },
  result_snapshots: [
    {
      section_name_snapshot: "Second section",
      test_name_snapshot: "Snapshot B",
      result_value_snapshot: "22.000",
      unit_snapshot: "unit B",
      reference_range_snapshot: "10 – 20",
      flag_snapshot: "HIGH",
      sort_order: 2,
    },
    {
      section_name_snapshot: "First section",
      test_name_snapshot: "Snapshot A",
      result_value_snapshot: "0.100",
      unit_snapshot: "unit A",
      reference_range_snapshot: "0.1 – 0.2",
      flag_snapshot: "NORMAL",
      sort_order: 1,
    },
  ],
  signatories: [
    {
      staff_name: "Test Signatory",
      signatory_type: "PATHOLOGIST",
      license_number_snapshot: "LICENSE-1",
      signed_at: "2026-09-20T11:30:00Z",
      sort_order: 1,
    },
  ],
};
export const enrollment = {
  secret: "TEST-ONLY-MANUAL-KEY",
  provisioning_uri:
    "otpauth://totp/Test:sample?secret=JBSWY3DPEHPK3PXP&issuer=Test",
};
export const codes = ["TEST-CODE-ONE", "TEST-CODE-TWO"];
export function patientFetch(
  handler?: (
    path: string,
    options: RequestInit,
  ) => Response | Promise<Response> | undefined,
  user: User | null = patientUser,
) {
  return mockFetch(
    (path, options) =>
      handler?.(path, options) ||
      (path === "/api/v1/patient/security"
        ? respond(security)
        : path === "/api/v1/patient/me"
          ? respond(profile)
          : path === "/api/v1/patient/reports/7"
            ? respond(detail)
            : path.startsWith("/api/v1/patient/reports?")
              ? respond(page([summary]))
              : respond(page([]))),
    user,
  );
}
export function portal(path = "/patient") {
  return renderAuth(<AppRoutes />, path);
}
export function blobs() {
  const create = vi.fn().mockReturnValue("blob:test-private");
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }),
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  return { create, revoke, click };
}
