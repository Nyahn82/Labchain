import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { PublicShell, PatientMessage } from "./patient/Shared";
import type { PublicVerification } from "../types/patient";
import "../styles/verification.css";
import { QrScanner } from "../components/QrScanner";
import { ScannedOfficialReport, type StaffScan } from "../components/ScannedOfficialReport";
import { useAuth } from "../auth/Auth";

export function StaffVerification() {
  const { user, can } = useAuth();
  const permitted = !!user && !user.roles.includes("PATIENT") &&
    (user.roles.includes("SYSTEM_ADMIN") || (!!user.staff && user.roles.some(r => ["LAB_STAFF","LAB_SUPERVISOR","DOCTOR","LAB_SIGNER"].includes(r)))) && can("REPORT_READ") && can("REPORT_DOWNLOAD");
  return permitted ? <Verification staff /> : <section className="card"><h1>Personnel report access required</h1><p>Active personnel access with report read and download permissions is required.</p></section>;
}

const titles: Record<string, string> = {
  REGISTERED: "Registered report", REVOKED: "Report revoked", SUPERSEDED: "Report superseded",
  NOT_FOUND: "Verification record not found.", UNAVAILABLE: "Verification unavailable",
};
const chainLabels: Record<string, string> = { VERIFIED: "Independently confirmed on Fabric", PENDING: "Blockchain confirmation pending", FAILED: "Blockchain verification failed", UNAVAILABLE: "Blockchain verification unavailable" };
const date = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Unavailable";
export function documentMatched(data: PublicVerification, now: number) {
  const age = now - Date.parse(data.blockchain_checked_at || "");
  return data.status === "REGISTERED" && data.document_comparison === "MATCH" && data.stored_artifact === "MATCH" &&
    data.issuer_evidence === "SNAPSHOT" && data.blockchain_evidence === "VERIFIED" && age >= -5000 && age <= 60000;
}
async function compare(token: string, file: File, signal: AbortSignal): Promise<PublicVerification> {
  const response = await fetch(`/api/v1/verify/${encodeURIComponent(token)}/compare`, {
    method: "POST", headers: { Accept: "application/json", "Content-Type": "application/pdf" },
    body: file, credentials: "omit", cache: "no-store", signal,
  });
  if (!response.ok) {
    const messages: Record<number, string> = { 413: "The PDF exceeds the upload-size limit.", 415: "Choose a supported PDF document.", 429: "Too many verification requests. Wait one minute and try again.", 408: "The upload timed out. Try again." };
    throw new Error(messages[response.status] || "Document comparison is unavailable. Try again.");
  }
  return response.json();
}
export function Verification({ staff = false }: { staff?: boolean }) {
  const { token } = useParams(); const navigate = useNavigate();
  const [scan, setScan] = useState<StaffScan>();
  const [data, setData] = useState<PublicVerification>(); const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error>(); const [attempt, setAttempt] = useState(0);
  const [file, setFile] = useState<File>(); const [checking, setChecking] = useState(false);
  const [uploadError, setUploadError] = useState(""); const [now, setNow] = useState(Date.now);
  const upload = useRef<AbortController | null>(null);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 15000); return () => window.clearInterval(timer); }, []);
  useEffect(() => {
    const controller = new AbortController(); upload.current?.abort(); setChecking(false); setFile(undefined); setUploadError("");
    setData(undefined); setScan(undefined); setError(undefined); setLoading(!!token);
    if (token) (staff ? api<StaffScan>("/verify/staff/resolve", { method: "POST", body: { token }, signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setScan(result); return result.verification; })
      : api<PublicVerification>("/verify/" + encodeURIComponent(token), { public: true, signal: controller.signal }))
      .then(result => { if (!controller.signal.aborted) { if (!titles[result.status]) throw new Error("Verification unavailable. Try again."); setData(result); setNow(Date.now()); } })
      .catch(e => { if (!controller.signal.aborted) { if (e instanceof ApiError && e.status === 404) setData({ status: "NOT_FOUND", message: "" }); else setError(e); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); upload.current?.abort(); };
  }, [token, attempt, staff]);
  const found = data && !["NOT_FOUND", "UNAVAILABLE"].includes(data.status);
  const verified = data && documentMatched(data, now);
  const fresh = data?.blockchain_checked_at && now - Date.parse(data.blockchain_checked_at) <= 60000 && now - Date.parse(data.blockchain_checked_at) >= -5000;
  const Wrapper = staff ? Fragment : PublicShell;
  const loadToken = (value: string) => { if (value === token) setAttempt(n => n + 1); else navigate((staff ? "/reports/scan/" : "/verify/") + encodeURIComponent(value)); };
  return <Wrapper><section className={"card verification-page" + (staff ? " staff-scan-page" : "")}>
    <p className="eyebrow">REPORT AUTHENTICITY</p><h1>{staff ? "Scan and view an official laboratory report" : "Verify a laboratory report"}</h1>
    <p>A QR code identifies a registered report. It cannot validate the surrounding printed text or a PDF you have not compared.</p>
    <QrScanner key={token || "empty"} onToken={loadToken} />
    <form onSubmit={e => { e.preventDefault(); const input = e.currentTarget.elements.namedItem("token") as HTMLInputElement; const value = input.value.trim(); input.value = ""; if (value) loadToken(value); }}>
      <label>Verification token<input name="token" required maxLength={128} autoComplete="off" autoCapitalize="none" spellCheck={false} /></label>
      <button className="primary">Check report</button>
    </form>
    <PatientMessage error={error} />{error && token && <button onClick={() => setAttempt(n => n + 1)}>Try again</button>}
    {loading && <p role="status">Checking registration and independent evidence…</p>}
    <div className={staff ? "staff-scan-results" : undefined}>
    {data && <section className="verification-result" aria-live="polite" aria-label="Verification outcome">
      <h2>{titles[data.status] || "Verification unavailable"}</h2>
      {data.status === "NOT_FOUND" && <p>Check the verification token or contact the issuing laboratory.</p>}
      {data.status === "UNAVAILABLE" && <p>The required evidence could not be checked. Refresh before relying on this result.</p>}
      {found && <>
        {["REVOKED", "SUPERSEDED"].includes(data.status) && <p role="alert">This report is no longer current. Do not treat a matching historical PDF as a current report.</p>}
        <dl><dt>Registered report identifier</dt><dd>{data.report_code || "Unavailable"}</dd>
          <dt>Issuing facility recorded at issuance</dt><dd>{data.issuing_facility || "Historical issuer snapshot unavailable"}</dd>
          <dt>Document version</dt><dd>{data.version ?? "Unavailable"}</dd><dt>Released</dt><dd>{data.released_at ? date(data.released_at) : data.report_date || "Unavailable"}</dd>
          <dt>Verification checked</dt><dd>{date(data.checked_at)}</dd></dl>
        <p className="small muted">Issuer information comes from the laboratory’s historical record. This is not verification of current DOH licensing or accreditation.</p>
        <div className={verified ? "document-outcome match" : "document-outcome"}>
          <h3>{verified ? "Verified document match" : data.document_comparison === "MISMATCH" ? "Document hash mismatch" : data.document_comparison === "MATCH" ? "Document bytes match — review remaining checks" : "Registered / document not yet compared"}</h3>
          <p>{data.document_comparison === "MISMATCH" ? "The submitted PDF bytes differ from the official released artifact. This alone does not prove malicious editing. A copied genuine QR does not make these different bytes authentic." : data.document_comparison === "MATCH" ? "The submitted PDF has the exact official SHA-256 digest. Current status, stored-artifact integrity, historical issuer information and independent blockchain evidence must also pass." : "No presented document has been verified. Compare the PDF below; scanning its QR alone is insufficient."}</p>
        </div>
        <h3>Official stored artifact</h3><p>{data.stored_artifact === "MATCH" ? "Stored PDF matches the release digest." : data.stored_artifact === "MISMATCH" ? "Stored PDF integrity check failed. Contact the laboratory." : "Stored PDF integrity verification unavailable."}</p>
        <h3>Blockchain evidence</h3><p>{data.blockchain_evidence === "VERIFIED" && !fresh ? "Evidence is stale. Refresh to verify again." : chainLabels[data.blockchain_evidence || "UNAVAILABLE"] || chainLabels.UNAVAILABLE}</p>
        <p className="small">Evidence checked: {date(data.blockchain_checked_at)}. Live evidence expires on this page after one minute.</p>
        <button onClick={() => setAttempt(n => n + 1)} disabled={checking}>Refresh evidence</button>
        <form key={token} className="pdf-comparison" onSubmit={async e => {
          e.preventDefault(); if (!file || !token || checking) return;
          setUploadError("");
          const limit = data.max_upload_bytes || 10 * 1024 * 1024;
          if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) { setUploadError("Choose a PDF document."); return; }
          if (file.size > limit) { setUploadError("The PDF exceeds the upload-size limit."); return; }
          const controller = new AbortController(); upload.current?.abort(); upload.current = controller;
          setChecking(true); setData({ ...data, document_comparison: "NOT_COMPARED" });
          try { const result = await compare(token, file, controller.signal); if (!controller.signal.aborted) { if (!titles[result.status]) throw new Error("Verification unavailable."); setData(result); setNow(Date.now()); } }
          catch (reason) { if (!controller.signal.aborted) setUploadError(reason instanceof Error && reason.message.startsWith("The PDF") ? reason.message : reason instanceof Error && ["Choose a supported PDF document.", "Too many verification requests. Wait one minute and try again.", "The upload timed out. Try again."].includes(reason.message) ? reason.message : "Document comparison is unavailable. Try again."); }
          finally { if (!controller.signal.aborted) setChecking(false); }
        }}><h3>Compare a PDF</h3>
          <label>PDF to compare<input type="file" accept="application/pdf,.pdf" aria-describedby="upload-privacy" onChange={e => { upload.current?.abort(); setChecking(false); setUploadError(""); setFile(e.target.files?.[0]); setData({ ...data, document_comparison: "NOT_COMPARED" }); }} /></label>
          <p id="upload-privacy">Limit: {Math.floor((data.max_upload_bytes || 10485760) / 1048576)} MiB. The document is sent securely for byte comparison, not rendered or permanently stored. Upload only a document you are authorized to share.</p>
          <button className="primary" disabled={!file || checking}>{checking ? "Comparing PDF…" : "Compare PDF"}</button>
          {checking && <p role="status">Comparing document bytes and checking ledger evidence…</p>}{uploadError && <p role="alert">{uploadError}</p>}
        </form>
      </>}
    </section>}
    {staff && scan && found && <ScannedOfficialReport key={scan.report_id} scan={scan} />}
    </div>
    <section><h2>Compare printed information privately</h2><p>A camera scan cannot check every printed result. Authorized patients and staff can sign in, open the official report with this identifier and version, and compare the printed information. Access remains limited by existing permissions and patient ownership.</p>
      <p><Link to="/patient/reports">Patient reports (sign in required)</Link> · <Link to="/reports">Staff reports (sign in required)</Link> · <Link to="/reports/scan">Personnel scanner and official PDF (sign in required)</Link></p>
    </section>
  </section></Wrapper>;
}
