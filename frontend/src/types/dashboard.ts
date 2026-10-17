export interface WorkflowCounts {
  total: number;
  statuses: Record<string, number>;
}
export interface Overview {
  generated_at: string;
  patients?: number;
  orders?: WorkflowCounts;
  specimens?: WorkflowCounts;
  results?: WorkflowCounts;
  reports?: WorkflowCounts;
}
