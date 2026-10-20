import type { PatientBlockchainVerification, SafeAnchoringStatus } from "./blockchain";
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
  blockchain_verification?: PatientBlockchainVerification | null;
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
  status: "REGISTERED" | "REVOKED" | "SUPERSEDED" | "NOT_FOUND" | "UNAVAILABLE";
  report_code?: string; issuing_facility?: string; issuer_evidence?: "SNAPSHOT" | "LEGACY_UNAVAILABLE";
  report_date?: string; released_at?: string; version?: number; message: string;
  checked_at?: string; blockchain_checked_at?: string; max_upload_bytes?: number;
  document_comparison?: "NOT_COMPARED" | "MATCH" | "MISMATCH";
  stored_artifact?: "MATCH" | "MISMATCH" | "UNAVAILABLE";
  blockchain_evidence?: "VERIFIED" | "PENDING" | "FAILED" | "UNAVAILABLE";
}
export interface Enrollment {
  secret: string;
  provisioning_uri: string;
}
export interface RecoveryResponse {
  recovery_codes: string[];
}
