import { choices, type Field, type LookupSpec } from "../components/Form";
import type { Column } from "../components/UI";
export interface Resource {
  title: string;
  singular: string;
  path: string;
  key: string;
  read: string;
  create: string;
  update: string;
  fields: Field[];
  columns: Column[];
  filters?: Field[];
  detail?: string;
  editPath?: string;
  searchable?: boolean;
}
export const lookup = (
  path: string,
  key: string,
  label: string | undefined,
  permission = "LAB_MASTER_READ",
  params = "&is_active=true",
): LookupSpec => ({ path, key, label, permission, params });
export const patientLookup = lookup(
  "/patients",
  "patient_id",
  undefined,
  "PATIENT_READ",
  "",
);
export const physicianLookup = lookup(
  "/physicians",
  "physician_id",
  undefined,
  "PHYSICIAN_READ",
);
export const testsLookup = lookup("/lab/tests", "test_id", "test_name");
export const panelsLookup = lookup("/lab/panels", "panel_id", "panel_name");
export const sampleLookup = lookup(
  "/lab/sample-types",
  "sample_type_id",
  "sample_name",
);
export const field = (
  name: string,
  label: string,
  extra: Partial<Field> = {},
): Field => ({ name, label, ...extra });
const active = field("is_active", "Active", { type: "boolean", default: true });
const names = [
  field("first_name", "First name", { required: true, max: 60 }),
  field("middle_name", "Middle name", { max: 60 }),
  field("last_name", "Last name", { required: true, max: 60 }),
  field("suffix", "Suffix", { max: 20 }),
];
const contact = [
  field("contact_number", "Contact number", { max: 30 }),
  field("email", "Email", { type: "email", max: 254 }),
];
const nameColumns: Column[] = [
  { key: "first_name", label: "First name" },
  { key: "last_name", label: "Last name" },
  { key: "contact_number", label: "Contact" },
];
const activeFilter = [
  field("is_active", "Activity", {
    type: "select",
    options: [
      { value: "true", label: "Active" },
      { value: "false", label: "Inactive" },
    ],
  }),
];
export const resources: Record<string, Resource> = {
  patients: {
    title: "Patients",
    singular: "patient",
    path: "/patients",
    key: "patient_id",
    read: "PATIENT_READ",
    create: "PATIENT_CREATE",
    update: "PATIENT_UPDATE",
    detail: "patients",
    fields: [
      field("patient_code", "Patient code", { required: true, max: 20 }),
      ...names,
      field("birth_date", "Birth date", { type: "date" }),
      field("sex", "Sex", {
        type: "select",
        options: choices("M", "F", "Other"),
      }),
      field("civil_status", "Civil status"),
      field("nationality", "Nationality"),
      ...contact,
      field("address", "Address", { type: "textarea" }),
    ],
    columns: [
      { key: "patient_code", label: "Patient code" },
      ...nameColumns,
      { key: "birth_date", label: "Birth date" },
    ],
    filters: [
      field("sex", "Sex", {
        type: "select",
        options: choices("M", "F", "Other"),
      }),
    ],
  },
  physicians: {
    title: "Physicians",
    singular: "physician",
    path: "/physicians",
    key: "physician_id",
    read: "PHYSICIAN_READ",
    create: "PHYSICIAN_CREATE",
    update: "PHYSICIAN_UPDATE",
    fields: [
      ...names,
      field("license_number", "License number"),
      field("specialization", "Specialization"),
      field("referring_facility_id", "Referring facility", {
        type: "lookup",
        lookup: lookup(
          "/referring-facilities",
          "referring_facility_id",
          "facility_name",
          "REFERRING_FACILITY_READ",
          "",
        ),
      }),
      contact[0],
      active,
    ],
    columns: [
      ...nameColumns,
      { key: "specialization", label: "Specialization" },
      { key: "license_number", label: "License" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
  facilities: {
    title: "Referring facilities",
    singular: "facility",
    path: "/referring-facilities",
    key: "referring_facility_id",
    read: "REFERRING_FACILITY_READ",
    create: "REFERRING_FACILITY_CREATE",
    update: "REFERRING_FACILITY_UPDATE",
    fields: [
      field("facility_name", "Facility name", { required: true, max: 150 }),
      field("facility_type", "Facility type"),
      field("address", "Address", { type: "textarea" }),
      contact[0],
    ],
    columns: [
      { key: "facility_name", label: "Facility" },
      { key: "facility_type", label: "Type" },
      { key: "contact_number", label: "Contact" },
    ],
  },
  staff: {
    title: "Staff",
    singular: "staff member",
    path: "/staff",
    key: "staff_id",
    read: "STAFF_READ",
    create: "STAFF_CREATE",
    update: "STAFF_UPDATE",
    detail: "staff",
    fields: [
      field("staff_code", "Staff code", { required: true, max: 20 }),
      ...names,
      field("position_title", "Position"),
      field("license_number", "License number"),
      ...contact,
      active,
    ],
    columns: [
      { key: "staff_code", label: "Staff code" },
      ...nameColumns,
      { key: "position_title", label: "Position" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
  departments: {
    title: "Departments",
    singular: "department",
    path: "/lab/departments",
    key: "department_id",
    read: "LAB_MASTER_READ",
    create: "LAB_DEPARTMENT_MANAGE",
    update: "LAB_DEPARTMENT_MANAGE",
    fields: [
      field("department_code", "Department code", { required: true }),
      field("department_name", "Department name", { required: true }),
      field("description", "Description", { type: "textarea" }),
      active,
    ],
    columns: [
      { key: "department_code", label: "Code" },
      { key: "department_name", label: "Department" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
  samples: {
    title: "Sample types",
    singular: "sample type",
    path: "/lab/sample-types",
    key: "sample_type_id",
    read: "LAB_MASTER_READ",
    create: "SAMPLE_TYPE_MANAGE",
    update: "SAMPLE_TYPE_MANAGE",
    fields: [
      field("sample_name", "Sample name", { required: true }),
      field("description", "Description", { type: "textarea" }),
      active,
    ],
    columns: [
      { key: "sample_name", label: "Sample type" },
      { key: "description", label: "Description" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
  tests: {
    title: "Tests",
    singular: "test",
    path: "/lab/tests",
    key: "test_id",
    read: "LAB_MASTER_READ",
    create: "TEST_CATALOG_MANAGE",
    update: "TEST_CATALOG_MANAGE",
    detail: "laboratory/tests",
    fields: [
      field("test_code", "Test code", { required: true }),
      field("test_name", "Test name", { required: true }),
      field("department_id", "Department", {
        lookup: lookup("/lab/departments", "department_id", "department_name"),
        required: true,
      }),
      field("default_unit", "Unit"),
      field("result_type", "Result type", {
        type: "select",
        options: choices("NUMERIC", "TEXT", "POS_NEG"),
        required: true,
      }),
      field("methodology", "Methodology"),
      field("default_sort_order", "Sort order", { type: "number" }),
      active,
    ],
    columns: [
      { key: "test_code", label: "Code" },
      { key: "test_name", label: "Test" },
      { key: "result_type", label: "Type" },
      { key: "default_unit", label: "Unit" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: [
      ...activeFilter,
      field("result_type", "Result type", {
        type: "select",
        options: choices("NUMERIC", "TEXT", "POS_NEG"),
      }),
    ],
  },
  panels: {
    title: "Panels",
    singular: "panel",
    path: "/lab/panels",
    key: "panel_id",
    read: "LAB_MASTER_READ",
    create: "TEST_PANEL_MANAGE",
    update: "TEST_PANEL_MANAGE",
    detail: "laboratory/panels",
    fields: [
      field("panel_code", "Panel code", { required: true }),
      field("panel_name", "Panel name", { required: true }),
      field("department_id", "Department", {
        lookup: lookup("/lab/departments", "department_id", "department_name"),
      }),
      field("description", "Description", { type: "textarea" }),
      active,
    ],
    columns: [
      { key: "panel_code", label: "Code" },
      { key: "panel_name", label: "Panel" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
  reasons: {
    title: "Rejection reasons",
    singular: "rejection reason",
    path: "/lab/rejection-reasons",
    key: "rejection_reason_id",
    read: "REJECTION_REASON_MANAGE",
    create: "REJECTION_REASON_MANAGE",
    update: "REJECTION_REASON_MANAGE",
    fields: [
      field("reason_code", "Reason code", { required: true }),
      field("reason_name", "Reason name", { required: true }),
      field("description", "Description", { type: "textarea" }),
      active,
    ],
    columns: [
      { key: "reason_code", label: "Code" },
      { key: "reason_name", label: "Reason" },
      { key: "is_active", label: "Status", badge: true },
    ],
    filters: activeFilter,
  },
};
export function ranges(testId: string): Resource {
  return {
    title: "Reference ranges",
    searchable: false,
    singular: "reference range",
    path: `/lab/tests/${testId}/reference-ranges`,
    editPath: "/lab/reference-ranges",
    key: "range_id",
    read: "LAB_MASTER_READ",
    create: "REFERENCE_RANGE_MANAGE",
    update: "REFERENCE_RANGE_MANAGE",
    fields: [
      field("sex", "Sex", {
        required: true,
        type: "select",
        options: choices("M", "F", "ANY"),
      }),
      ...[
        "age_min",
        "age_max",
        "normal_low",
        "normal_high",
        "critical_low",
        "critical_high",
      ].map((n) =>
        field(n, n.replaceAll("_", " "), {
          type: "decimal",
          group: n === "normal_low" ? "Numeric range configuration" : undefined,
          help: n.startsWith("age")
            ? "Age in years"
            : "Numeric range configuration",
        }),
      ),
      field("qualitative_normal", "Qualitative normal", {
        group: "Qualitative normal configuration",
        help: "Use for qualitative configuration; not a diagnosis.",
      }),
      field("unit", "Unit"),
      field("effective_from", "Effective from", { type: "date" }),
      field("effective_to", "Effective to", { type: "date" }),
      active,
    ],
    columns: [
      { key: "sex", label: "Sex" },
      { key: "age_min", label: "Age min" },
      { key: "age_max", label: "Age max" },
      { key: "normal_low", label: "Normal low" },
      { key: "normal_high", label: "Normal high" },
      { key: "qualitative_normal", label: "Qualitative normal" },
      { key: "is_active", label: "Status", badge: true },
    ],
  };
}
export function rules(testId: string): Resource {
  return {
    title: "Interpretation rules",
    searchable: false,
    singular: "interpretation rule",
    path: `/lab/tests/${testId}/interpretation-rules`,
    editPath: "/lab/interpretation-rules",
    key: "rule_id",
    read: "LAB_MASTER_READ",
    create: "INTERPRETATION_RULE_MANAGE",
    update: "INTERPRETATION_RULE_MANAGE",
    fields: [
      field("flag", "Flag", {
        required: true,
        type: "select",
        options: choices(
          "NORMAL",
          "LOW",
          "HIGH",
          "CRITICAL_LOW",
          "CRITICAL_HIGH",
          "ABNORMAL",
        ),
      }),
      ...["interpretation_text", "possible_causes", "recommendation"].map((n) =>
        field(n, n.replaceAll("_", " "), {
          type: "textarea",
          help: "Approved explanatory text only; not an automated diagnosis.",
        }),
      ),
      active,
    ],
    columns: [
      { key: "flag", label: "Flag", badge: true },
      { key: "interpretation_text", label: "Explanation" },
      { key: "is_active", label: "Status", badge: true },
    ],
  };
}
