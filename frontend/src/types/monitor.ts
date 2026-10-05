export type NodeState = "ONLINE" | "DEGRADED" | "OFFLINE" | "UNKNOWN";
export interface MonitorNode {
  name: string; msp: string; status: NodeState; height: number | null;
  channel_member: boolean | null; current_block_hash: string | null;
  previous_block_hash: string | null; checked_at: string; last_success_at: string | null;
  error_code: string | null;
}
export interface NetworkOverview {
  channel: string; topology: "SINGLE_VPS"; status: NodeState;
  ledger_height: number | null; checked_at: string; nodes: MonitorNode[];
  orderer: { name: string; status: NodeState; signal: string; height: null };
  chaincode: { name: string; version: string; sequence: number; endorsement_policy: string } | null;
}
export interface LedgerTransaction {
  transaction_id: string | null; validation_code: number | null;
  validation_status: string; timestamp: string | null;
}
export interface LedgerBlock {
  number: number; block_hash: string; previous_block_hash: string | null;
  transaction_count: number; timestamp: string | null;
}
export interface BlockDetail extends LedgerBlock {
  transactions: LedgerTransaction[]; source_peer: string; checked_at: string;
}
export interface LedgerPage {
  items: LedgerBlock[]; next_before: number | null; ledger_height: number;
  source_peer: string; checked_at: string;
}
export interface TransactionDetail extends LedgerTransaction {
  block_number: number; block_hash: string; source_peer: string; checked_at: string;
}
export interface AnchorEvent {
  event_id: number; event_uuid: string; event_type: string; entity_type: string;
  entity_reference: string; status: string; occurred_at: string; confirmed_at: string | null;
  transaction_id: string | null; block_number: number | null;
  record_hash: string; previous_hash: string | null;
}
export interface AnchorPage { items: AnchorEvent[]; next_before: number | null }
export interface IntegrityResult {
  report_id: number; status: string; checked_at: string; artifact_sha256: string | null;
  report_hash: string | null; record_hash: string | null; ledger_content_hash: string | null;
  source_peer: string | null;
}
