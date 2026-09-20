import type { Row } from "./domain";
export interface PatientSecurity {
  mfa_required: boolean;
  totp_enabled: boolean;
  mfa_verified_for_current_session: boolean;
  unused_recovery_codes: number;
}
export interface PatientReportSummary extends Row {
  report_id: number;
  report_code: string;
  version_no: number;
  released_at: string;
  order_code: string;
  issuing_facility: string;
  verification_status: "AUTHENTIC" | "REVOKED" | null;
}
export interface PatientReport extends PatientReportSummary {
  report_status: "RELEASED";
  generated_at: string;
  facility: Row;
  patient_snapshot: Row;
  result_snapshots: PatientResult[];
  signatories: Row[];
}
export interface PatientResult extends Row {
  section_name_snapshot: string | null;
  test_name_snapshot: string;
  result_value_snapshot: string;
  unit_snapshot: string | null;
  reference_range_snapshot: string | null;
  flag_snapshot: string | null;
  sort_order: number;
}
export interface PublicVerification {
  status: "VERIFIED" | "REVOKED" | "ALTERED" | "NOT_FOUND";
  issuing_facility?: string;
  report_date?: string;
  version?: number;
  message: string;
}
export interface Enrollment {
  secret: string;
  provisioning_uri: string;
}
export interface RecoveryResponse {
  recovery_codes: string[];
}
