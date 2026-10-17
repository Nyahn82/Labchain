import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Dialog, State } from "./UI";

export function ReportPreview({ id, onClose }: { id: number; onClose: () => void }) {
  const [url, setUrl] = useState<string>();
  const [error, setError] = useState<Error>();
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    api<Blob>(`/reports/${id}/pdf`, { blob: true, signal: controller.signal }).then(blob => {
      if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }
    }).catch(e => { if (!controller.signal.aborted) setError(e); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id]);
  return <Dialog title="Official report PDF" onClose={onClose}>
    <p>This is the stored, integrity-checked report. Check its current verification status before use.</p>
    <State loading={!url && !error} error={error} />
    {url && <iframe className="report-pdf-preview" title="Official laboratory report PDF" src={url} />}
    <p className="muted">If your browser cannot preview PDFs, close this dialog and use Download PDF.</p>
  </Dialog>;
}
