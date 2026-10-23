import { useEffect, useRef, useState } from "react";
import type { IScannerControls } from "@zxing/browser";
import { reportToken } from "../utils/qr";

export function QrScanner({ onToken }: { onToken: (token: string) => void }) {
  const [open, setOpen] = useState(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const video = useRef<HTMLVideoElement>(null); const callback = useRef(onToken); callback.current = onToken;
  const generation = useRef(0); const stopCamera = useRef<() => void>(() => {});
  useEffect(() => () => { generation.current++; stopCamera.current(); }, []);
  useEffect(() => {
    if (!open) return;
    let disposed = false; let stream: MediaStream | undefined; let controls: IScannerControls | undefined;
    const preview = video.current!;
    const stop = () => { disposed = true; controls?.stop(); stream?.getTracks().forEach(t => t.stop()); preview.srcObject = null; };
    stopCamera.current = stop;
    const hidden = () => { if (document.hidden) { stop(); setOpen(false); } };
    document.addEventListener("visibilitychange", hidden);
    setError(""); setBusy(true);
    (async () => {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error("UNSUPPORTED");
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      if (disposed) return;
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } } });
      if (disposed) { stream.getTracks().forEach(t => t.stop()); return; }
      const reader = new BrowserQRCodeReader(undefined, { delayBetweenScanAttempts: 200, delayBetweenScanSuccess: 500 });
      controls = await reader.decodeFromStream(stream, preview, result => {
        if (!result || disposed) return;
        const token = reportToken(result.getText());
        if (!token) { setError("This QR is not a supported RHU LabChain report. Scan another code or enter its verification token."); return; }
        stop(); setOpen(false); setBusy(false); callback.current(token);
      });
      if (disposed) controls.stop(); else setBusy(false);
    })().catch(reason => {
      if (disposed) return;
      stop(); setOpen(false); setBusy(false);
      const name = reason && typeof reason === "object" && "name" in reason ? String(reason.name) : "";
      setError(name === "NotAllowedError" ? "Camera permission was denied. Allow camera access in your browser settings, or choose a QR image or enter the token." : name === "NotFoundError" || name === "NotReadableError" ? "No available camera could be opened. Close other camera apps or use a QR image or token." : "Camera scanning is unavailable in this browser. Use HTTPS with a supported browser, choose a QR image or enter the token.");
    });
    return () => { stop(); document.removeEventListener("visibilitychange", hidden); };
  }, [open, facing]);
  return <section className="qr-scanner" aria-label="QR scanner">
    <div className="toolbar"><button className="primary" type="button" onClick={() => { generation.current++; setError(""); setOpen(true); }}>Start Camera</button>
      {open && <><button type="button" onClick={() => { stopCamera.current(); setFacing(f => f === "environment" ? "user" : "environment"); }}>Switch camera</button><button type="button" onClick={() => { stopCamera.current(); setOpen(false); setBusy(false); }}>Stop Camera</button></>}
    </div>
    {open && <><video ref={video} autoPlay muted playsInline aria-label="Live QR camera preview" /><p role="status">{busy ? "Opening camera…" : "Point the camera at the report QR. Scanning stops when a valid report is found."}</p></>}
    <label>Upload QR Image<input type="file" accept="image/png,image/jpeg,image/webp" disabled={open} onChange={async e => {
      const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
      const current = ++generation.current; setError(""); setBusy(true);
      if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) { setError("Choose a PNG, JPEG or WebP QR image up to 10 MiB."); setBusy(false); return; }
      const url = URL.createObjectURL(file);
      try {
        const { BrowserQRCodeReader } = await import("@zxing/browser");
        const img = new Image(); img.src = url; await img.decode();
        if (current !== generation.current) return;
        if (!img.naturalWidth || img.naturalWidth * img.naturalHeight > 25000000) throw new Error("Image dimensions unsupported");
        const scale = Math.min(1, 2400 / Math.max(img.naturalWidth, img.naturalHeight));
        const canvas = document.createElement("canvas"); canvas.width = Math.round(img.naturalWidth * scale); canvas.height = Math.round(img.naturalHeight * scale);
        canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
        const result = new BrowserQRCodeReader().decodeFromCanvas(canvas); const token = reportToken(result.getText());
        if (!token) { setError("This QR is not a supported RHU LabChain report."); return; }
        callback.current(token);
      } catch { if (current === generation.current) setError("No readable report QR was found. Choose a clearer image or enter the verification token."); }
      finally { URL.revokeObjectURL(url); if (current === generation.current) setBusy(false); }
    }} /></label>
    {busy && !open && <p role="status">Reading QR image…</p>}
    {error && <p role="alert">{error}</p>}
    <p className="small muted">Camera frames and QR images stay on this device.</p>
  </section>;
}
