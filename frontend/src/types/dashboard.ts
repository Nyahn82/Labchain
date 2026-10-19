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
  presence?: { recently_active: number; window_seconds: number };
  activation?: { not_activated: number; review_required: number };
  accounts?: { active: number; suspended: number };
  failed_logins?: { count: number; since: string; until: string };
  signing?: { unassigned: number; awaiting_signature: number; awaiting_approval: number };
  services?: { name: string; status: "HEALTHY" | "UNHEALTHY" | "STALE" | "UNKNOWN" | "STOPPED"; checked_at?: string }[];
}
