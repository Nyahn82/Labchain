import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";
import { ResourcePage } from "../pages/ResourcePage";
import { PersonDetail } from "../pages/People";
import { LabDetail } from "../pages/Laboratory";
import { resources, type Resource } from "../pages/resources";
import type { Row } from "../types/domain";
import { admin, mockFetch, page, renderAuth, respond } from "./helpers";

const cases = [
  { kind: "patients", codeField: "patient_code", code: "PAT-000123" },
  { kind: "staff", codeField: "staff_code", code: "STF-000123" },
  { kind: "departments", codeField: "department_code", code: "DEP-123" },
  { kind: "tests", codeField: "test_code", code: "TST-0123" },
  { kind: "panels", codeField: "panel_code", code: "PNL-0123" },
  { kind: "reasons", codeField: "reason_code", code: "REJ-123" },
];
const immutableCodes = cases.map(({ codeField }) => codeField);

function record(resource: Resource, codeField: string, code: string): Row {
  return {
    [codeField]: code,
    first_name: "Synthetic",
    last_name: "Person",
    department_name: "Synthetic department",
    test_name: "Synthetic test",
    panel_name: "Synthetic panel",
    reason_name: "Synthetic reason",
    department_id: 1,
    result_type: "NUMERIC",
    is_active: true,
    sample_types: [],
    sections: [],
    tests: [],
    [resource.key]: 7,
  };
}
function lookupResponse(path: string) {
  if (path.startsWith("/api/v1/lab/departments?"))
    return respond(page([{ department_id: 1, department_name: "Hematology" }]));
  return respond(page([]));
}
async function fillRequired(resource: Resource) {
  for (const field of resource.fields.filter((f) => f.required)) {
    const label = field.label + " *";
    if (field.lookup) {
      const select = screen.getByLabelText(label);
      await within(select).findByRole("option", { name: "Hematology" });
      await userEvent.selectOptions(select, "1");
    } else if (field.type === "select") {
      await userEvent.selectOptions(screen.getByLabelText(label), "NUMERIC");
    } else {
      await userEvent.type(screen.getByLabelText(label), "Synthetic");
    }
  }
}
function expectNoCodes(body: Row) {
  for (const field of immutableCodes) expect(body).not.toHaveProperty(field);
}

describe("automatic resource codes", () => {
  it.each(cases)("creates $kind without code inputs and displays the returned identifier", async ({ kind, codeField, code }) => {
    const resource = resources[kind];
    let saved: Row | undefined;
    document.cookie = "rhu_csrf=resource-token; path=/";
    const fetch = mockFetch((path, options) => {
      if (path === "/api/v1" + resource.path && options.method === "POST") {
        saved = { ...JSON.parse(String(options.body)), [resource.key]: 7, [codeField]: code };
        return respond(saved, 201);
      }
      if (path.startsWith("/api/v1" + resource.path + "?")) return respond(page(saved ? [saved] : []));
      return lookupResponse(path);
    });
    renderAuth(<ResourcePage resource={resource} />);
    await userEvent.click(await screen.findByRole("button", { name: "New " + resource.singular }));
    expect(screen.queryByLabelText(/code/i)).not.toBeInTheDocument();
    await fillRequired(resource);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(`${resource.singular} saved (${code}).`);
    expect(await within(screen.getByRole("table")).findByText(code)).toBeInTheDocument();
    const request = fetch.mock.calls.find(([, options]) => options?.method === "POST")!;
    expectNoCodes(JSON.parse(String(request[1]?.body)));
    expect(request[1]).toMatchObject({
      credentials: "include",
      cache: "no-store",
      headers: expect.objectContaining({ "X-CSRF-Token": "resource-token" }),
    });
    if (kind !== "patients") expect(JSON.parse(String(request[1]?.body)).is_active).toBe(true);
  });

  it.each(cases)("edits $kind without resubmitting codes from prefill data", async ({ kind, codeField, code }) => {
    const resource = resources[kind];
    // Response-only keys must not leak into the form's request body.
    let saved = {
      ...Object.fromEntries(immutableCodes.map((field) => [field, "STALE-CODE"])),
      ...record(resource, codeField, code),
      created_at: "2026-10-15T00:00:00",
    };
    const fetch = mockFetch((path, options) => {
      if (options.method === "PATCH") {
        saved = { ...saved, ...JSON.parse(String(options.body)) };
        return respond(saved);
      }
      if (path.startsWith("/api/v1" + resource.path + "?")) return respond(page([saved]));
      return lookupResponse(path);
    });
    renderAuth(<ResourcePage resource={resource} />);
    await screen.findByText(code);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(within(screen.getByRole("dialog")).getByText(new RegExp(code))).toBeInTheDocument();
    expect(screen.queryByLabelText(/code/i)).not.toBeInTheDocument();
    const field = resource.fields.find((f) => f.required && !f.lookup && f.type !== "select")!;
    await userEvent.clear(screen.getByLabelText(field.label + " *"));
    await userEvent.type(screen.getByLabelText(field.label + " *"), "Revised");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const request = fetch.mock.calls.find(([, options]) => options?.method === "PATCH")!;
    expect(request[0]).toBe(`/api/v1${resource.path}/7`);
    const body = JSON.parse(String(request[1]?.body));
    expectNoCodes(body);
    expect(body).not.toHaveProperty(resource.key);
    expect(body).not.toHaveProperty("created_at");
    expect(body[field.name]).toBe("Revised");
    expect(within(screen.getByRole("table")).getByText(code)).toBeInTheDocument();
    // Opening a new form must not reuse the previous edit's defaults or code.
    await userEvent.click(screen.getByRole("button", { name: "New " + resource.singular }));
    expect(screen.getByLabelText(field.label + " *")).toHaveValue("");
    expect(screen.queryByLabelText(/code/i)).not.toBeInTheDocument();
  });

  it.each(["patients", "staff", "tests", "panels"] as const)("preserves the %s detail identifier while editing only allowed fields", async (kind) => {
    const resource = resources[kind];
    const { codeField, code } = cases.find((item) => item.kind === kind)!;
    const row = record(resource, codeField, code);
    const fetch = mockFetch((path, options) => {
      if (path === `/api/v1${resource.path}/7`) return respond(row);
      return lookupResponse(path);
    });
    renderAuth(
      <Routes>
        <Route path="/record/:id" element={kind === "patients" || kind === "staff"
          ? <PersonDetail kind={kind} /> : <LabDetail kind={kind} />} />
      </Routes>,
      "/record/7",
    );
    expect(await screen.findByText(code)).toHaveProperty("tagName", "DD");
    await userEvent.click(screen.getByRole("button", { name: kind === "patients" || kind === "staff" ? "Edit details" : "Edit metadata" }));
    expect(screen.queryByLabelText(/code/i)).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetch.mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(true));
    const request = fetch.mock.calls.find(([, options]) => options?.method === "PATCH")!;
    expectNoCodes(JSON.parse(String(request[1]?.body)));
    expect(screen.getByText(code)).toBeInTheDocument();
  });

  it.each([
    [403, "permission"], [409, "conflicts"], [422, "form fields"], [500, "could not complete"],
  ])("handles HTTP %s on create without losing form input or showing a success", async (status, message) => {
    mockFetch((_, options) => options.method === "POST"
      ? respond({ detail: "SQL private secret" }, Number(status)) : respond(page([])));
    renderAuth(<ResourcePage resource={resources.patients} />);
    await userEvent.click(await screen.findByRole("button", { name: "New patient" }));
    await fillRequired(resources.patients);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(String(message));
    expect(screen.getByRole("alert")).not.toHaveTextContent(/SQL|private|secret/);
    expect(screen.getByLabelText("First name *")).toHaveValue("Synthetic");
    expect(screen.queryByText(/patient saved/)).not.toBeInTheDocument();
  });

  it("retains required field validation without requiring a code", async () => {
    const fetch = mockFetch(() => respond(page([])));
    renderAuth(<ResourcePage resource={resources.patients} />);
    await userEvent.click(await screen.findByRole("button", { name: "New patient" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    expect(screen.getByLabelText("First name *")).toBeInvalid();
  });

  it("shows identifiers to readers without offering create or edit actions", async () => {
    mockFetch(() => respond(page([record(resources.patients, "patient_code", "PAT-000123")])),
      { ...admin, roles: ["STAFF"], permissions: ["PATIENT_READ"] });
    renderAuth(<ResourcePage resource={resources.patients} />, "/patients?new=1");
    await screen.findByText("PAT-000123");
    expect(screen.queryByRole("button", { name: "New patient" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not fetch a directory without read permission", async () => {
    const fetch = mockFetch(undefined, { ...admin, roles: ["STAFF"], permissions: [] });
    renderAuth(<ResourcePage resource={resources.patients} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/v1/auth/me", expect.anything()));
    expect(screen.getByText("Permission required")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([path]) => path.startsWith("/api/v1/patients"))).toBe(false);
  });
});
