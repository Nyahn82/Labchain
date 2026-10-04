// Phase 8B-4A response contracts. Receipt fields are staff-only.
export type BlockchainAnchoringStatus =
  | "NOT_ANCHORED"
  | "PENDING"
  | "PROCESSING"
  | "RETRYING"
  | "CONFIRMED"
  | "FAILED";
export type SafeAnchoringStatus = Exclude<BlockchainAnchoringStatus, "PROCESSING">;
export type BlockchainWorkerHealth = "IDLE" | "ACTIVE" | "DEGRADED" | "ERROR";
export interface ReportAnchoringLifecycle {
  status: BlockchainAnchoringStatus;
  confirmed_at?: string | null;
  transaction_id?: string | null;
  block_number?: number | null;
}
export interface ReportAnchoring {
  status: BlockchainAnchoringStatus;
  release: ReportAnchoringLifecycle;
  revocation?: ReportAnchoringLifecycle | null;
  supersession?: ReportAnchoringLifecycle | null;
}
export interface PatientBlockchainVerification {
  status: SafeAnchoringStatus;
  confirmed_at?: string | null;
}
export interface BlockchainStatusResponse {
  delivery_enabled: boolean | null;
  counts: {
    pending: number;
    processing: number;
    confirmed: number;
    failed: number;
    dead: number;
  };
  last_confirmed_at: string | null;
  last_confirmed_transaction_id: string | null;
  oldest_pending_at: string | null;
  worker_health: BlockchainWorkerHealth;
}
