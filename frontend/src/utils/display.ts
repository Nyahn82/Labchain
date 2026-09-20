import type { Row } from "../types/domain";
export function value(row: Row, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (v, key) => (v && typeof v === "object" ? (v as Row)[key] : undefined),
      row,
    );
}
export function display(input: unknown): string {
  if (input == null || input === "") return "—";
  if (typeof input === "boolean") return input ? "Active" : "Inactive";
  if (typeof input === "object") return person(input as Row);
  return String(input);
}
export function person(row: Row): string {
  return (
    ["first_name", "middle_name", "last_name", "suffix"]
      .map((k) => row[k])
      .filter(Boolean)
      .join(" ") ||
    String(
      row.patient_name ||
        row.username ||
        row.test_name ||
        row.panel_name ||
        row.sample_name ||
        row.facility_name ||
        "—",
    )
  );
}
export function timestamp(input: unknown) {
  if (!input) return "—";
  const raw = String(input);
  const date = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(raw) ? raw : raw + "Z");
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
export function safeUrl(input: unknown) {
  try {
    const url = new URL(String(input), location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
