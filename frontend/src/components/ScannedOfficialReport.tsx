import { useEffect, useState } from "react";
import { api } from "../api/client";
import { State } from "./UI";
import type { PublicVerification } from "../types/patient";
export interface StaffScan {
  report_id: number;
  verification: PublicVerification;
  ledger_details_authorized: boolean;
  ledger_details: { event_type: string; artifact_sha256: string; content_hash: string; transaction_id: string; block_number: number; validation_status: string; source_msp: string; source_peer: string; checked_at: string }[];
}
export function ScannedOfficialReport({ scan }: { scan: StaffScan }) {
  const [url, setUrl] = useState<string>(); const [error, setError] = useState<Error>();
  useEffect(() => {
    const controller = new AbortController(); let objectUrl: string | undefined;
    setUrl(undefined); setError(undefined);
    api<Blob>(`/reports/${scan.report_id}/pdf`, { blob: true, signal: controller.signal }).then(blob => {
      if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }
    }).catch(e => { if (!controller.signal.aborted) setError(e); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [scan.report_id]);
  return <section className="official-scan-report" aria-label="Authorized official report">
    <h2>Official laboratory report — version {scan.verification.version}</h2>
    <p>Compare the patient identification, specimen, dates, laboratory results, reference ranges and signatories on this original report with the presented document. Historical reports retain the information recorded at release.</p>
    <State loading={!url && !error} error={error} />
    {url && <><p><a href={url} target="_blank" rel="noopener noreferrer">Open full official PDF</a></p><iframe className="report-pdf-preview" title="Official laboratory report PDF" src={url + "#view=FitH&navpanes=0"} /><p className="small">If this browser cannot display PDFs inline, use Open full official PDF. This is the exact stored artifact, not a regenerated report.</p></>}
    <h3>Independent ledger evidence</h3>
    <p>The verification outcome above comes from live anchor and committed-transaction checks. Viewing the official PDF does not compare the surrounding printed document automatically.</p>
    {scan.ledger_details_authorized ? scan.ledger_details.length ? scan.ledger_details.map((e, i) => <details key={e.transaction_id+i}><summary>{e.event_type} — committed transaction {e.validation_status}, block {e.block_number}</summary><dl>
      <dt>Official PDF SHA-256</dt><dd>{e.artifact_sha256}</dd><dt>Canonical commitment SHA-256</dt><dd>{e.content_hash}</dd><dt>Transaction</dt><dd>{e.transaction_id}</dd><dt>Issuer organization</dt><dd>{e.source_msp}</dd><dt>Queried peer</dt><dd>{e.source_peer}</dd><dt>Evidence observed</dt><dd>{new Date(e.checked_at).toLocaleString()}</dd></dl><p>Each listed witness passed its independent checks at this time. The overall outcome above also includes lifecycle and freshness checks.</p></details>) : <p>No independently validated transaction details are available.</p> : <p>Detailed ledger identifiers require blockchain explorer and integrity permissions. The privacy-safe live verification outcome remains visible above.</p>}
  </section>;
}
