import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { patientFetch, portal } from "./patient.helpers";
import { respond } from "./helpers";
import { documentMatched } from "../pages/Verification";
import type { PublicVerification } from "../types/patient";
const evidence = (): PublicVerification => ({ status: "REGISTERED", message: "PRIVATE-MESSAGE", report_code: "REP-001", issuing_facility: "Synthetic Laboratory", issuer_evidence: "SNAPSHOT", version: 1, released_at: "2026-10-19T00:00:00Z", checked_at: new Date().toISOString(), blockchain_checked_at: new Date().toISOString(), document_comparison: "NOT_COMPARED", stored_artifact: "MATCH", blockchain_evidence: "VERIFIED", max_upload_bytes: 10485760 });
describe("public authenticity", () => {
  it("never certifies a copied QR alone and exposes only safe registration fields", async () => {
    patientFetch(p => p.startsWith("/api/v1/verify/") ? respond({ ...evidence(), patient_name: "PRIVATE-PATIENT", result_value: "PRIVATE-RESULT", pdf_path: "PRIVATE-PATH" }) : undefined, null);
    portal("/verify/TOKEN");
    expect(await screen.findByRole("heading", { name: "Registered / document not yet compared" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Verified document match" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/PRIVATE-/);
    expect(screen.getByText(/cannot validate the surrounding printed text/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Patient reports (sign in required)" })).toHaveAttribute("href", "/patient/reports");
    expect(screen.getByLabelText("PDF to compare")).toHaveAttribute("aria-describedby", "upload-privacy");
  });
  it.each([ ["REVOKED", "Report revoked"], ["SUPERSEDED", "Report superseded"], ["NOT_FOUND", "Verification record not found."], ["UNAVAILABLE", "Verification unavailable"] ])("renders %s with clear textual states", async (status, title) => {
    patientFetch(p => p.startsWith("/api/v1/verify/") ? respond({ ...evidence(), status }) : undefined, null);
    portal("/verify/TOKEN");
    expect(await screen.findByRole("heading", { name: title })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Verified document match" })).not.toBeInTheDocument();
    if (["REVOKED", "SUPERSEDED"].includes(status)) expect(screen.getByRole("alert")).toHaveTextContent("no longer current");
    if (status === "NOT_FOUND") expect(screen.queryByText("Synthetic Laboratory")).not.toBeInTheDocument();
  });
  it.each(["PENDING", "FAILED", "UNAVAILABLE"])("does not turn matching bytes green when blockchain is %s", async blockchain_evidence => {
    patientFetch(p => p.startsWith("/api/v1/verify/") ? respond({ ...evidence(), blockchain_evidence, document_comparison: "MATCH" }) : undefined, null);
    portal("/verify/TOKEN");
    await screen.findByRole("heading", { name: "Document bytes match — review remaining checks" });
    expect(screen.queryByRole("heading", { name: "Verified document match" })).not.toBeInTheDocument();
  });
  it.each(["MATCH", "MISMATCH"])("uploads raw PDF bytes without cookies and renders %s", async comparison => {
    const fetch = patientFetch(p => p.startsWith("/api/v1/verify/") ? respond({ ...evidence(), document_comparison: p.endsWith("/compare") ? comparison : "NOT_COMPARED" }) : undefined, null);
    portal("/verify/TOKEN"); await screen.findByLabelText("PDF to compare");
    const pdf = new File(["%PDF-1.4\nsynthetic\n%%EOF"], "synthetic.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("PDF to compare"), pdf);
    await userEvent.click(screen.getByRole("button", { name: "Compare PDF" }));
    expect(await screen.findByRole("heading", { name: comparison === "MATCH" ? "Verified document match" : "Document hash mismatch" })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith("/api/v1/verify/TOKEN/compare", expect.objectContaining({ method: "POST", body: pdf, credentials: "omit", headers: { Accept: "application/json", "Content-Type": "application/pdf" } }));
    if (comparison === "MISMATCH") expect(screen.getByText(/alone does not prove malicious editing/)).toBeVisible();
    // Selecting another file invalidates prior comparison immediately.
    await userEvent.upload(screen.getByLabelText("PDF to compare"), new File(["%PDF-1.4\nother\n%%EOF"], "other.pdf", { type: "application/pdf" }));
    expect(screen.queryByRole("heading", { name: "Verified document match" })).not.toBeInTheDocument();
  });
  it("bounds file size locally and sanitizes upload failures", async () => {
    const fetch = patientFetch(p => p.endsWith("/compare") ? respond({ detail: "PRIVATE-PDF" }, 503) : p.startsWith("/api/v1/verify/") ? respond({ ...evidence(), max_upload_bytes: 100 }) : undefined, null);
    portal("/verify/TOKEN"); await screen.findByLabelText("PDF to compare");
    await userEvent.upload(screen.getByLabelText("PDF to compare"), new File(["x".repeat(101)], "large.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Compare PDF" }));
    expect(screen.getByRole("alert")).toHaveTextContent("exceeds");
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/compare"))).toBe(false);
    await userEvent.upload(screen.getByLabelText("PDF to compare"), new File(["%PDF-1.4\n%%EOF"], "small.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Compare PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("comparison is unavailable");
    expect(document.body).not.toHaveTextContent("PRIVATE-PDF");
  });
  it.each(["resubmit", "retry"])("retries failed registration via %s", async method => {
    let count=0;
    patientFetch(p => p.endsWith("/verify/TOKEN") ? ++count === 1 ? respond({ detail: "PRIVATE-ERROR" },503) : respond(evidence()) : undefined, null);
    portal("/verify/TOKEN"); await screen.findByRole("alert");
    if (method === "retry") await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    else { await userEvent.type(screen.getByLabelText("Verification token"), "TOKEN"); await userEvent.click(screen.getByRole("button", { name: "Check report" })); }
    expect(await screen.findByRole("heading", { name: "Registered report" })).toBeVisible();
    expect(document.body).not.toHaveTextContent("PRIVATE-ERROR");
  });
  it("accepts token entry without authentication and neutralizes missing records", async () => {
    patientFetch(p => p.startsWith("/api/v1/verify/") ? respond({},404) : undefined,null);
    portal("/verify"); await userEvent.type(screen.getByLabelText("Verification token"),"unknown");
    await userEvent.click(screen.getByRole("button",{name:"Check report"}));
    expect(await screen.findByRole("heading",{name:"Verification record not found."})).toBeVisible();
  });
  it("requires every mandatory check and fresh evidence for document success", () => {
    const data = { ...evidence(), document_comparison: "MATCH" as const }; const now = Date.now();
    expect(documentMatched(data,now)).toBe(true);
    for (const patch of [{status:"REVOKED"},{status:"SUPERSEDED"},{stored_artifact:"MISMATCH"},{issuer_evidence:"LEGACY_UNAVAILABLE"},{blockchain_evidence:"FAILED"},{blockchain_checked_at:new Date(now-61000).toISOString()},{blockchain_checked_at:new Date(now+10000).toISOString()},{document_comparison:"NOT_COMPARED"}]) expect(documentMatched({...data,...patch} as PublicVerification,now)).toBe(false);
  });
  it("uses responsive styles and accessible controls at a mobile viewport", async () => {
    Object.defineProperty(window,"innerWidth",{configurable:true,value:375});
    patientFetch(p => p.startsWith("/api/v1/verify/") ? respond(evidence()) : undefined,null);
    portal("/verify/TOKEN"); await screen.findByLabelText("PDF to compare");
    expect(screen.getByRole("main")).toBeVisible();
    expect(screen.getByRole("region",{name:"Verification outcome"})).toHaveAttribute("aria-live","polite");
    expect(screen.getByRole("button",{name:"Compare PDF"})).toBeDisabled();
    // jsdom verifies semantics only; real responsive layout/camera walkthrough is separate.
  });
});
