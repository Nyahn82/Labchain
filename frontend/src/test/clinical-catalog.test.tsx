import { useState } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ClinicalCatalogBrowser, type CatalogSelection } from "../components/ClinicalCatalogBrowser";
import { ResultForm } from "../pages/Results";
import { AppRoutes } from "../App";
import { mockFetch, renderAuth, respond, order, result } from "./helpers";
const catalog = {
  departments: [{department_id: 1, department_name: "Hematology"}, {department_id: 2, department_name: "Chemistry"}],
  specimens: [{sample_type_id: 1, sample_name: "EDTA Whole Blood"}, {sample_type_id: 2, sample_name: "Serum"}],
  tests: [
    {test_id: 10, test_code: "TST-10", test_name: "Hemoglobin", aliases: "Hgb", department_id: 1, sample_type_ids: [1], result_type: "NUMERIC", orderable: true, facility_status: "APPROVED"},
    {test_id: 11, test_code: "TST-11", test_name: "Creatinine", department_id: 2, sample_type_ids: [2], result_type: "NUMERIC", orderable: false, facility_status: "UNREVIEWED"},
  ],
  panels: [{panel_id: 20, panel_code: "PNL-20", panel_name: "Synthetic blood panel", department_id: 1, test_ids: [10], orderable: true, facility_status: "APPROVED"}],
};
function Picker() { const [selection, setSelection] = useState<CatalogSelection>({test_ids: [], panel_ids: []}); return <ClinicalCatalogBrowser selection={selection} onChange={setSelection} />; }
describe("clinical catalog integration", () => {
  it("searches alternate names and combines department, specimen and availability filters", async () => {
    mockFetch(p => p === "/api/v1/lab/catalog-browser" ? respond(catalog) : undefined);
    renderAuth(<ClinicalCatalogBrowser />);
    await screen.findByRole("link", {name: "Hemoglobin"});
    await userEvent.type(screen.getByRole("searchbox", {name: "Find examinations"}), "Hgb");
    expect(screen.queryByRole("link", {name: "Creatinine"})).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Specimen type"), "2");
    expect(screen.getByText(/No matching examinations/)).toBeVisible();
    await userEvent.clear(screen.getByRole("searchbox"));
    await userEvent.selectOptions(screen.getByLabelText("Department"), "2");
    expect(screen.getByRole("link", {name: "Creatinine"})).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText("Service availability"), "available");
    expect(screen.getByText(/No matching examinations/)).toBeVisible();
  });
  it("deduplicates selection preview across panels and individual tests and disables unavailable services", async () => {
    mockFetch(p => p === "/api/v1/lab/catalog-browser" ? respond(catalog) : undefined);
    renderAuth(<Picker />);
    await userEvent.click(await screen.findByRole("checkbox", {name: "Select Hemoglobin"}));
    await userEvent.selectOptions(screen.getByLabelText("Catalog entries"), "panels");
    await userEvent.click(screen.getByRole("checkbox", {name: "Select Synthetic blood panel"}));
    expect(screen.getByRole("heading", {name: "Selected examinations (1 unique)"})).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText("Catalog entries"), "tests");
    await userEvent.selectOptions(screen.getByLabelText("Service availability"), "all");
    expect(screen.getByRole("checkbox", {name: "Select Creatinine"})).toBeDisabled();
  });
  it("keeps simulation availability visibly distinct from clinical approval", async () => {
    const simulation = structuredClone(catalog);
    simulation.tests[1].orderable = true;
    mockFetch(p => p === "/api/v1/lab/catalog-browser" ? respond(simulation) : undefined);
    renderAuth(<Picker />);
    expect(await screen.findByRole("checkbox", { name: "Select Creatinine" })).toBeEnabled();
    expect(screen.getByText("Simulation only · not clinically approved")).toBeVisible();
    expect(screen.getByText("UNREVIEWED")).toBeVisible();
  });
  it("removes a selected panel while retaining an individually selected component", async () => {
    mockFetch(p => p === "/api/v1/lab/catalog-browser" ? respond(catalog) : undefined);
    renderAuth(<Picker />);
    await userEvent.click(await screen.findByRole("checkbox", {name: "Select Hemoglobin"}));
    await userEvent.selectOptions(screen.getByLabelText("Catalog entries"), "panels");
    await userEvent.click(screen.getByRole("checkbox", {name: "Select Synthetic blood panel"}));
    await userEvent.click(screen.getByRole("button", {name: "Remove Synthetic blood panel"}));
    expect(screen.getByRole("heading", {name: "Selected examinations (1 unique)"})).toBeVisible();
    expect(screen.getByRole("button", {name: "Remove Hemoglobin"})).toBeVisible();
    await userEvent.click(screen.getByRole("button", {name: "Remove Hemoglobin"}));
    expect(screen.getByRole("heading", {name: "Selected examinations (0 unique)"})).toBeVisible();
  });
  it("submits selections through the existing order endpoint", async () => {
    const fetch = mockFetch(p => p === "/api/v1/lab/catalog-browser" ? respond(catalog) : p === "/api/v1/lab-orders" ? respond(order, 201) : undefined);
    renderAuth(<AppRoutes />, "/orders/new?patient_id=1");
    await userEvent.click(await screen.findByRole("checkbox", {name: "Select Hemoglobin"}));
    await userEvent.click(screen.getByRole("button", {name: "Create order"}));
    await waitFor(() => expect(fetch.mock.calls.some(([p, o]) => p === "/api/v1/lab-orders" && o?.method === "POST")).toBe(true));
    const request=fetch.mock.calls.find(([p, o]) => p === "/api/v1/lab-orders" && o?.method === "POST")!;
    expect(JSON.parse(request[1]!.body as string)).toMatchObject({patient_id: 1, test_ids: [10], panel_ids: []});
  });
  it("resumes structured draft fields and saves observations through the existing result endpoint", async () => {
    const test = {...result.test, result_type: "TEXT", result_schema: {version: 1, susceptibility: false, fields: [{key: "growth", label: "Culture findings", kind: "text", choices: [], required: true}]}};
    const draft = {...result, test, structured_values: {growth: "Synthetic draft growth"}};
    const fetch = mockFetch(() => respond(draft));
    renderAuth(<ResultForm order={order} item={order.items[0]} result={draft} done={() => {}} />);
    const growth = await screen.findByRole("textbox", {name: "Culture findings"});
    expect(growth).toHaveValue("Synthetic draft growth");
    await userEvent.clear(growth); await userEvent.type(growth, "Synthetic completed findings");
    await userEvent.click(screen.getByRole("button", {name: "Save"}));
    await waitFor(() => expect(fetch.mock.calls.some(([,o]) => o?.method === "PATCH")).toBe(true));
    const request=fetch.mock.calls.find(([,o]) => o?.method === "PATCH")!;
    expect(JSON.parse(request[1]!.body as string).structured_values).toEqual({growth: "Synthetic completed findings"});
  });
});
