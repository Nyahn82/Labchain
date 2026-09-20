import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import {
  patientFetch,
  portal,
  summary,
  detail,
  blobs,
} from "./patient.helpers";
import { page, respond, renderAuth } from "./helpers";
import { PatientPdf, SnapshotResults } from "../pages/patient/PatientReport";
import type { PatientResult } from "../types/patient";
describe("own patient information", () => {
  it("shows a read-only allowlisted profile", async () => {
    patientFetch();
    portal("/patient/profile");
    expect(await screen.findByText("Sample Patient")).toBeInTheDocument();
    expect(screen.getByText("P-004")).toBeInTheDocument();
    expect(screen.getByText("Test address")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("MUST-NOT-SHOW")).not.toBeInTheDocument();
  });
  it("shows real recent released reports and no staff menu", async () => {
    patientFetch();
    portal();
    expect(await screen.findByText("RPT-007")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Patients" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Security settings" }),
    ).toBeInTheDocument();
  });
  it("shows a neutral empty report state", async () => {
    patientFetch((p) =>
      p.includes("/patient/reports?") ? respond(page([])) : undefined,
    );
    portal("/patient/reports");
    expect(
      await screen.findByText(/No released reports are available yet/),
    ).toBeInTheDocument();
  });
  it("paginates report summaries", async () => {
    const fetch = patientFetch((p) =>
      p.includes("/patient/reports?")
        ? respond(page([summary], 25))
        : undefined,
    );
    portal("/patient/reports");
    await screen.findByText("RPT-007");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("page=2"),
        expect.anything(),
      ),
    );
  });
  it("searches and filters releases without any patient-id parameter", async () => {
    const fetch = patientFetch();
    portal("/patient/reports");
    await userEvent.type(await screen.findByLabelText("Search reports"), "RPT");
    await userEvent.type(screen.getByLabelText("Released from"), "2026-09-01");
    await userEvent.type(
      screen.getByLabelText("Released through"),
      "2026-09-20",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Apply filters" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "search=RPT&date_from=2026-09-01&date_to=2026-09-20",
        ),
        expect.anything(),
      ),
    );
    expect(fetch.mock.calls.every(([p]) => !p.includes("patient_id"))).toBe(
      true,
    );
  });
  it("uses historical snapshot names, values, units, ranges and signatories", async () => {
    const fetch = patientFetch();
    portal("/patient/reports/7");
    expect(await screen.findByText("Snapshot A")).toBeInTheDocument();
    expect(screen.getByText("0.100")).toBeInTheDocument();
    expect(screen.getByText("0.1 – 0.2")).toBeInTheDocument();
    expect(screen.getByText("Test Signatory")).toBeInTheDocument();
    expect(screen.getByText("Test Physician")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/lab/tests"))).toBe(
      false,
    );
  });
  it("sorts snapshot rows/sections without recalculating flags", () => {
    patientFetch();
    renderAuth(
      <SnapshotResults rows={detail.result_snapshots as PatientResult[]} />,
    );
    const sections = screen.getAllByRole("heading", { level: 3 });
    expect(sections.map((el) => el.textContent)).toEqual([
      "First section",
      "Second section",
    ]);
    expect(screen.getByText("Within reference range")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });
  it("shows neutral unavailable text for ownership 404 without alternate requests", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/patient/reports/7")
        ? respond({ detail: "Another patient private detail" }, 404)
        : undefined,
    );
    portal("/patient/reports/7");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Report not available.",
    );
    expect(screen.queryByText(/Another patient/)).not.toBeInTheDocument();
    expect(
      fetch.mock.calls.filter(([p]) => p.includes("/patient/reports/")),
    ).toHaveLength(1);
  });
  it("renders safe access history and readable action labels", async () => {
    patientFetch((p) =>
      p.includes("/access-history?")
        ? respond(
            page(
              [
                {
                  action: "PATIENT_REPORT_VIEW",
                  timestamp: "2026-09-20T12:00:00Z",
                  report_code: "RPT-007",
                  raw_audit: "PRIVATE-AUDIT",
                  ip: "PRIVATE-IP",
                },
                {
                  action: "PATIENT_REPORT_DOWNLOAD",
                  timestamp: "2026-09-20T13:00:00Z",
                  report_code: "RPT-007",
                },
              ],
              21,
            ),
          )
        : undefined,
    );
    portal("/patient/access-history");
    expect(await screen.findByText("Viewed report")).toBeInTheDocument();
    expect(screen.getByText("Downloaded report")).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE-AUDIT")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE-IP")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });
  it("paginates access history", async () => {
    const fetch = patientFetch((p) =>
      p.includes("/access-history?") ? respond(page([], 21)) : undefined,
    );
    portal("/patient/access-history");
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/patient/access-history?page=2&page_size=20",
        expect.anything(),
      ),
    );
  });
});
describe("authenticated patient PDFs", () => {
  it("opens the patient PDF endpoint in an accessible native viewer and revokes on close", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/pdf")
        ? new Response("PDF", {
            headers: { "Content-Type": "application/pdf" },
          })
        : undefined,
    );
    const { create, revoke } = blobs();
    renderAuth(<PatientPdf reportId={7} code="RPT-007" />);
    await userEvent.click(screen.getByRole("button", { name: "View PDF" }));
    expect(
      await screen.findByTitle("Official PDF for RPT-007"),
    ).toHaveAttribute("src", "blob:test-private");
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/patient/reports/7/pdf",
      expect.objectContaining({ credentials: "include" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(revoke).toHaveBeenCalledWith("blob:test-private");
  });
  it("downloads an authenticated Blob and revokes on unmount", async () => {
    patientFetch((p) => (p.endsWith("/pdf") ? new Response("PDF") : undefined));
    const { click, revoke } = blobs();
    const view = renderAuth(<PatientPdf reportId={7} code="RPT-007" />);
    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    view.unmount();
    expect(revoke).toHaveBeenCalledWith("blob:test-private");
  });
  it("does not create a PDF URL after a safe integrity failure", async () => {
    patientFetch((p) =>
      p.endsWith("/pdf")
        ? respond({ detail: "/var/lib/private report hash mismatch" }, 409)
        : undefined,
    );
    const { create } = blobs();
    renderAuth(<PatientPdf reportId={7} code="RPT-007" />);
    await userEvent.click(screen.getByRole("button", { name: "View PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The report could not be verified",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("/var/lib");
    expect(create).not.toHaveBeenCalled();
  });
});
