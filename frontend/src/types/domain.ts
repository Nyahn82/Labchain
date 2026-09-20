export type Row = Record<string, unknown>;
export interface Page<T = Row> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
export interface User {
  user_id: number;
  username: string;
  roles: string[];
  permissions: string[];
  staff: { staff_id: number; first_name: string; last_name: string } | null;
  patient: unknown;
}
export interface Order extends Row {
  order_id: number;
  order_code: string;
  status: string;
  patient: Row;
  physician: Row | null;
  panels: Row[];
  items: Row[];
  payments: Row[];
  specimens: Specimen[];
}
export interface Specimen extends Row {
  specimen_id: number;
  specimen_code: string;
  order_id: number;
  specimen_status: string;
  sample_type: Row;
  mappings: Row[];
  rejections: Row[];
}
export interface Result extends Row {
  result_item_id: number;
  order_item_id: number;
  result_value: string;
  status: string;
  flag: string | null;
  test: Row;
}
export interface Report extends Row {
  report_id: number;
  report_code: string;
  order_id: number;
  report_status: string;
  version_no: number;
  signatories: Row[];
  result_snapshots: Row[];
  patient_snapshot: Row | null;
}
