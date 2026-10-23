import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { PublicShell, PatientMessage } from "./patient/Shared";
import type { PublicVerification } from "../types/patient";
import "../styles/verification.css";
import { QrScanner } from "../components/QrScanner";
import { ScannedOfficialReport, ScannedLedgerEvidence, type StaffScan } from "../components/ScannedOfficialReport";
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
const chainLabels: Record<string, string> = { FOUR_PEER_VERIFIED: "FOUR-PEER VERIFIED", PARTIAL: "PARTIAL VERIFICATION", CONFLICT: "CONSISTENCY CONFLICT", PENDING: "CONFIRMATION PENDING", FAILED: "VERIFICATION FAILED", UNAVAILABLE: "VERIFICATION UNAVAILABLE" };
const peerNames = ["peer1", "peer2", "peer3", "peer4"];
function fourConfirmed(data: PublicVerification, now: number) {
  return data.blockchain_evidence === "FOUR_PEER_VERIFIED" && data.blockchain_verified_count === 4 &&
    data.blockchain_peers?.length === 4 && peerNames.every(name => data.blockchain_peers?.filter(p => p.peer === name).length === 1 &&
      data.blockchain_peers.some(p => p.peer === name && p.status === "VERIFIED" && now - Date.parse(p.checked_at || "") >= -5000 && now - Date.parse(p.checked_at || "") <= 60000));
}
const date = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Unavailable";
export function documentMatched(data: PublicVerification, now: number) {
  const age = now - Date.parse(data.blockchain_checked_at || "");
  return data.status === "REGISTERED" && data.document_comparison === "MATCH" && data.stored_artifact === "MATCH" &&
    data.issuer_evidence === "SNAPSHOT" && fourConfirmed(data, now) && age >= -5000 && age <= 60000;
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
  const { token } = useParams(); const navigate = useNavigate(); const location = useLocation();
  useEffect(() => { if (!token && location.state?.focusScanner) document.querySelector<HTMLButtonElement>(".qr-scanner button")?.focus(); }, [token, location.key, location.state]);
  const manual = useRef<HTMLDetailsElement>(null);
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
    <p className="eyebrow">REPORT AUTHENTICITY</p><h1>Scan Laboratory Report</h1>
    <p>Point your camera at the QR code on the laboratory report.</p>
    <QrScanner key={token || "empty"} onToken={loadToken} />
    <details ref={manual} className="manual-verification"><summary>Enter Verification Code</summary><form onSubmit={e => { e.preventDefault(); const input = e.currentTarget.elements.namedItem("token") as HTMLInputElement; const value = input.value.trim(); input.value = ""; if (value) loadToken(value); }}>
      <label>Verification token<input name="token" required maxLength={128} autoComplete="off" autoCapitalize="none" spellCheck={false} /></label>
      <button className="primary">Check report</button>
    </form></details>
    <PatientMessage error={error} />{error && token && <button onClick={() => setAttempt(n => n + 1)}>Try again</button>}
    {loading && <p role="status">Checking report evidence on all four peers…</p>}
    <div className={staff ? "staff-scan-results" : undefined}>
    {data && <section className="verification-result" aria-live="polite" aria-label="Verification outcome">
      <h2>Laboratory Report Verification</h2><h3>{titles[data.status] || "Verification unavailable"}</h3>
      {data.status === "NOT_FOUND" && <p>Check the verification token or contact the issuing laboratory.</p>}
      {data.status === "UNAVAILABLE" && <p>The required evidence could not be checked. Refresh before relying on this result.</p>}
      {found && <>
        {["REVOKED", "SUPERSEDED"].includes(data.status) && <p role="alert">This report is no longer current. Do not treat a matching historical PDF as a current report.</p>}
        <dl className="verification-summary">
          <dt>Report Registration</dt><dd>REGISTERED</dd>
          <dt>Report Status</dt><dd>{data.status === "REGISTERED" ? "CURRENT" : data.status}</dd>
          <dt>Blockchain Verification</dt><dd>{!fresh && data.blockchain_evidence === "FOUR_PEER_VERIFIED" ? "STALE — REFRESH REQUIRED" : chainLabels[data.blockchain_evidence || "UNAVAILABLE"]}{data.blockchain_evidence === "PARTIAL" ? ` — ${data.blockchain_verified_count || 0}/4` : ""}</dd>
          <dt>Official PDF Integrity</dt><dd>{data.stored_artifact || "UNAVAILABLE"}</dd>
          <dt>Presented Document</dt><dd>{data.document_comparison?.replaceAll("_", " ") || "NOT COMPARED"}</dd>
        </dl>
        <section className="peer-verification" aria-label="Blockchain Peer Verification">
          <h3>Blockchain Peer Verification</h3>
          <ul>{peerNames.map((name, i) => { const peer = data.blockchain_peers?.find(p => p.peer === name);
            const age = now - Date.parse(peer?.checked_at || "");
            const state = peer?.status === "VERIFIED" && !(age >= -5000 && age <= 60000) ? "STALE" : peer?.status || "UNAVAILABLE";
            return <li key={name}><span>Peer {i + 1}</span><strong className={`peer-status peer-${state.toLowerCase()}`}>{state === "LAGGING" ? "PEER LAGGING" : state}</strong></li>; })}</ul>
          <p><strong>{fresh ? data.blockchain_verified_count || 0 : 0} of 4 peers verified</strong></p>
          <p>{data.blockchain_evidence === "CONFLICT" ? "Blockchain peers returned inconsistent evidence for this report. Full verification cannot be confirmed." :
            data.blockchain_evidence === "FAILED" ? "A required blockchain integrity check failed. Full verification cannot be confirmed." :
            fourConfirmed(data, now) && fresh ? "All 4 blockchain peers confirmed matching report evidence." :
            data.blockchain_evidence === "PARTIAL" && fresh ? `${data.blockchain_verified_count || 0} of 4 blockchain peers confirmed matching evidence. Review the remaining peer states.` :
            data.blockchain_evidence === "PENDING" ? "Report evidence is awaiting blockchain confirmation." : "Blockchain verification is temporarily unavailable. Please try again."}</p>
          {data.blockchain_peers?.some(p => p.status === "LAGGING") && <p className="small">A lagging peer has not reached the block needed to verify this report.</p>}
          <p className="small muted">Observed: {date(data.blockchain_checked_at)} · Refresh after one minute.</p>
          <button onClick={() => setAttempt(n => n + 1)} disabled={checking}>Refresh evidence</button>
        </section>
        <div className={verified ? "document-outcome match" : "document-outcome"}>
          <h3>{verified ? "Verified document match" : data.document_comparison === "MISMATCH" ? "Document hash mismatch" : data.document_comparison === "MATCH" ? "Document bytes match — review remaining checks" : "Registered / document not yet compared"}</h3>
          <p>{data.document_comparison === "MISMATCH" ? "The presented PDF differs from the official file, even if the blockchain confirms the original. This alone does not prove malicious editing." : data.document_comparison === "MATCH" ? "The presented PDF matches the official file’s exact bytes." : "Scan the QR to identify the report; compare the PDF to check its contents."}</p>
        </div>
        <details className="verification-explanation"><summary>What does this verification mean?</summary>
          <p>Blockchain verification checks the official report's recorded integrity evidence. To confirm that a printed or uploaded copy has not been changed, compare it with the official report.</p>
          <p>A QR code cannot validate the surrounding printed text. A copied genuine QR does not authenticate altered results.</p>
          <dl><dt>Report identifier</dt><dd>{data.report_code || "Unavailable"}</dd><dt>Version</dt><dd>{data.version ?? "Unavailable"}</dd>
            <dt>Released</dt><dd>{date(data.released_at)}</dd><dt>Historical issuing facility</dt><dd>{data.issuing_facility || "Historical issuer snapshot unavailable"}</dd>
            <dt>Issuer evidence</dt><dd>{data.issuer_evidence || "Unavailable"}</dd></dl>
          <p>Historical issuer details do not verify current licensing or accreditation.</p>
        </details>
        <form key={token} className="pdf-comparison" onSubmit={async e => {
          e.preventDefault(); if (!file || !token || checking) return;
          setUploadError("");
          const limit = data.max_upload_bytes || 10 * 1024 * 1024;
          if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) { setUploadError("Choose a PDF document."); return; }
          if (file.size > limit) { setUploadError("The PDF exceeds the upload-size limit."); return; }
          const controller = new AbortController(); upload.current?.abort(); upload.current = controller;
          setChecking(true); setData({ ...data, document_comparison: "NOT_COMPARED" });
          try { const result = await compare(token, file, controller.signal); if (!controller.signal.aborted) { if (!titles[result.status]) throw new Error("Verification unavailable."); setData(result); setScan(current => current ? { ...current, ledger_details: [] } : current); setNow(Date.now()); } }
          catch (reason) { if (!controller.signal.aborted) setUploadError(reason instanceof Error && reason.message.startsWith("The PDF") ? reason.message : reason instanceof Error && ["Choose a supported PDF document.", "Too many verification requests. Wait one minute and try again.", "The upload timed out. Try again."].includes(reason.message) ? reason.message : "Document comparison is unavailable. Try again."); }
          finally { if (!controller.signal.aborted) setChecking(false); }
        }}><h3>Compare a PDF</h3>
          <label>PDF to compare<input type="file" accept="application/pdf,.pdf" aria-describedby="upload-privacy" onChange={e => { upload.current?.abort(); setChecking(false); setUploadError(""); setFile(e.target.files?.[0]); setData({ ...data, document_comparison: "NOT_COMPARED" }); }} /></label>
          <p id="upload-privacy">Up to {Math.floor((data.max_upload_bytes || 10485760) / 1048576)} MiB. Compared securely without permanent storage. Upload only an authorized document.</p>
          <button className="primary" disabled={!file || checking}>{checking ? "Comparing PDF…" : "Compare PDF"}</button>
          {checking && <p role="status">Comparing document bytes and checking ledger evidence…</p>}{uploadError && <p role="alert">{uploadError}</p>}
        </form>
        {staff && scan && <ScannedLedgerEvidence scan={scan} />}
      </>}
    </section>}
    {staff && scan && found && <ScannedOfficialReport key={scan.report_id} scan={{ ...scan, verification: data! }} />}
    </div>
    {token && <button onClick={() => { navigate(staff ? "/reports/scan" : "/verify", { state: { focusScanner: true } }); }}>Scan Again</button>}
    <details className="verification-explanation"><summary>Compare a printed report</summary>
      <p>Compare printed results with the exact official PDF. Private report access requires sign-in.</p>
      <p><Link to="/patient/reports">Patient reports (sign in required)</Link> · <Link to="/reports/scan">Personnel scanner (sign in required)</Link></p>
    </details>
  </section></Wrapper>;
}
