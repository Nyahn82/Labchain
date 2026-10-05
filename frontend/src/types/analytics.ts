export type Grain = "auto" | "day" | "week" | "month" | "quarter" | "year";
export interface AnalyticsMetric {
  key: string; label: string; definition: string; value: number | null;
  unit: "count" | "percent" | "seconds" | "amount";
  previous_value: number | null; absolute_change: number | null; percent_change: number | null; compared: boolean;
}
export interface AnalyticsSeries {
  key: string; label: string; definition: string; points: { bucket: string; value: number }[];
}
export interface AnalyticsGroup {
  key: string; label: string; count: number; share: number | null;
  code: string | null; department: string | null;
  drafted: number | null; reviewed: number | null; verified: number | null;
}
export interface AnalyticsBreakdown {
  key: string; label: string; definition: string; items: AnalyticsGroup[]; total: number; other_count: number;
}
export interface AnalyticsData {
  range: { date_from: string; date_to: string; previous_date_from: string; previous_date_to: string; timezone: string; grain: string; week_starts_on: string };
  metrics: AnalyticsMetric[]; series: AnalyticsSeries[]; breakdowns: AnalyticsBreakdown[];
  turnaround: { key: string; label: string; definition: string; average_seconds: number | null; sample_count: number; excluded_count: number; candidate_count: number }[];
  notes: string[];
}
