import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { StarterCatalog } from "../components/StarterCatalog";
import { ResourcePage } from "../pages/ResourcePage";
import { resources } from "../pages/resources";
import { admin, mockFetch, page, renderAuth, respond } from "./helpers";

const preview = {
  version: "synthetic-starter", fingerprint: "a".repeat(64), notice: "Facility approval required before clinical use.",
  inventory: { departments: 1, samples: 1, tests: 1, panels: 1 }, create_count: 3, preserved_count: 1,
  conflicts: [], sources: { synthetic: { title: "Synthetic source", url: "https://example.invalid/source" } },
  items: [
    { kind: "departments", key: "chem", name: "Clinical Chemistry", action: "CREATE_INACTIVE", record_id: null, code: null, definition: { description: "Review capability." } },
    { kind: "samples", key: "serum", name: "Serum", action: "CREATE_INACTIVE", record_id: null, code: null, definition: { description: "Approve container separately." } },
    { kind: "tests", key: "creat", name: "Creatinine", action: "PRESERVE", record_id: 8, code: "TST-0008", definition: { department: "chem", samples: ["serum"], result_type: "NUMERIC", review_note: "Approve method.", reference_policy: "Local interval review.", sources: ["synthetic"] } },
    { kind: "panels", key: "renal", name: "Renal Function Tests", action: "CREATE_INACTIVE", record_id: null, code: null, definition: { department: "chem", tests: ["creat"], description: "Review component grouping." } },
  ],
};
const reader = { ...admin, roles: ["LAB_STAFF"], permissions: ["LAB_MASTER_READ"] };
const test = { test_id: 8, test_code: "TST-0008", test_name: "Creatinine", department_id: 3, default_unit: null, methodology: null, result_type: "NUMERIC", is_active: false };

describe("starter catalog administration", () => {
  it("requires a preview and explicit confirmation, then shows actual generated codes", async () => {
    const fetch = mockFetch((p, o) => p.includes("starter-catalog") ? o.method === "POST"
      ? respond({ created: [{ kind: "tests", name: "Creatinine", code: "TST-0042", record_id: 42 }], preserved_count: 1, notice: preview.notice })
      : respond(preview) : undefined);
    renderAuth(<StarterCatalog />);
    await screen.findByRole("button", { name: "Preview starter catalog" });
    expect(fetch.mock.calls.some(([p]) => p.includes("starter-catalog"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Preview starter catalog" }));
    const importButton = await screen.findByRole("button", { name: "Import inactive starter entries" });
    expect(importButton).toBeDisabled();
    await userEvent.click(screen.getByText("Review all entries, specimen associations and panel members"));
    expect(screen.getByText(/Proposed specimens: Serum/)).toBeVisible();
    expect(screen.getByText(/Proposed members: Creatinine/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Synthetic source" })).toHaveAttribute("href", "https://example.invalid/source");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(importButton);
    expect(await screen.findByText("Creatinine · TST-0042")).toBeVisible();
    const request = fetch.mock.calls.find(([, o]) => o?.method === "POST")!;
    expect(JSON.parse(String(request[1]?.body))).toEqual({ fingerprint: preview.fingerprint, acknowledge_inactive_review: true });
    expect(request[1]).toMatchObject({ credentials: "include", cache: "no-store" });
    expect(screen.queryByRole("button", { name: "Import inactive starter entries" })).not.toBeInTheDocument();
  });
  it("blocks ambiguous matches without offering import", async () => {
    const fetch = mockFetch(() => respond({ ...preview, conflicts: ["tests: Creatinine: multiple existing matches"] }));
    renderAuth(<StarterCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview starter catalog" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Import blocked");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
  });
  it("shows an idempotent empty plan", async () => {
    mockFetch(() => respond({ ...preview, create_count: 0, preserved_count: 4 }));
    renderAuth(<StarterCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview starter catalog" }));
    expect(await screen.findByText(/Nothing to add/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Import inactive starter entries" })).not.toBeInTheDocument();
  });
  it("keeps a read-only user's preview separate from management actions", async () => {
    mockFetch(() => respond(preview), reader);
    renderAuth(<StarterCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview starter catalog" }));
    expect(await screen.findByText(/Import requires department/)).toBeVisible();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
  it.each([403, 409, 503])("requires a fresh preview after an import error %s", async status => {
    const fetch = mockFetch((_, o) => o.method === "POST" ? respond({ detail: "PRIVATE_DATABASE_MESSAGE" }, status) : respond(preview));
    renderAuth(<StarterCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview starter catalog" }));
    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Import inactive starter entries" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE_DATABASE_MESSAGE");
    expect(screen.getByText(/Review a fresh preview before retrying/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Import inactive starter entries" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
  });
  it("shows loading and recovers from a preview error", async () => {
    let resolve!: (response: Response) => void;
    mockFetch(() => new Promise<Response>(r => { resolve = r; }));
    renderAuth(<StarterCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview starter catalog" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    expect(screen.getByRole("button", { name: "Preview starter catalog" })).toBeDisabled();
    resolve(respond({}, 503));
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Preview starter catalog" })).toBeEnabled();
  });
  it.each([{ ...reader, permissions: [] }, { ...admin, roles: ["SYSTEM_ADMIN", "PATIENT"] }])("hides the import from unauthorized or patient identities", async user => {
    const fetch = mockFetch(undefined, user);
    renderAuth(<StarterCatalog />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByText("Philippine laboratory starter catalog")).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("starter-catalog"))).toBe(false);
  });
});

describe("existing catalog integration", () => {
  it("combines department, status and generated-code search filters", async () => {
    const fetch = mockFetch(p => respond(p.includes("/lab/departments") ? page([{ department_id: 3, department_name: "Clinical Chemistry", is_active: false }]) : page([test])));
    renderAuth(<ResourcePage resource={resources.tests} />);
    expect(await screen.findByText("TST-0008")).toBeVisible();
    await screen.findByRole("option", { name: "Clinical Chemistry" });
    await userEvent.selectOptions(screen.getByLabelText("Department filter"), "3");
    await userEvent.selectOptions(screen.getByLabelText("Activity"), "false");
    await userEvent.type(screen.getByLabelText("Search tests"), "TST-0008");
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p.includes("department_id=3") && p.includes("is_active=false") && p.includes("search=TST-0008"))).toBe(true));
    expect(fetch.mock.calls.filter(([p]) => p.includes("/lab/departments")).every(([p]) => !p.includes("is_active=true"))).toBe(true);
  });
  it.each(["NUMERIC", "TEXT"])("shows specimen guidance and edits %s configuration without sending immutable codes", async resultType => {
    const fetch = mockFetch(p => p === "/api/v1/lab/tests/8" ? respond({ ...test, result_type: resultType, sample_types: [{ sample_type_id: 7, is_default: false, sample_type: { sample_name: "Serum", description: "Use approved container SOP", is_active: false } }] })
      : p.includes("/sample-types?") ? respond(page([{ sample_type_id: 7, sample_name: "Serum", is_active: false }]))
      : p.includes("/departments?") ? respond(page([{ department_id: 3, department_name: "Clinical Chemistry", is_active: false }])) : respond(page([])));
    renderAuth(<AppRoutes />, "/laboratory/tests/8");
    expect(await screen.findByText("Use approved container SOP")).toBeVisible();
    expect(screen.getByText(/qualified laboratory personnel must approve/)).toBeVisible();
    expect(screen.getByText("TST-0008")).toBeVisible();
    if (resultType === "TEXT") expect(screen.getByText(/Text results allow a 100-character summary/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Edit metadata" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText(/Test code/)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetch.mock.calls.some(([, o]) => o?.method === "PATCH")).toBe(true));
    const request = fetch.mock.calls.find(([, o]) => o?.method === "PATCH")!;
    expect(JSON.parse(String(request[1]?.body))).not.toHaveProperty("test_code");
    expect(fetch.mock.calls.filter(([p]) => p.includes("/sample-types?")).every(([p]) => !p.includes("is_active=true"))).toBe(true);
  });
});
