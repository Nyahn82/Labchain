import { useState } from "react";

export function abbreviateHash(value: string) {
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-8)}` : value;
}
export function HashValue({ value, label = "Hash" }: { value: string | null; label?: string }) {
  const [notice, setNotice] = useState("");
  if (!value) return <span aria-label={`${label} unavailable`}>—</span>;
  async function copy() {
    try { await navigator.clipboard.writeText(value!); setNotice("Copied"); }
    catch { setNotice("Copy unavailable. Expand and select the full value."); }
  }
  return <div className="hash-value">
    <code>{abbreviateHash(value)}</code>
    <button type="button" onClick={copy} aria-label={`Copy ${label}`}>Copy</button>
    <details><summary aria-label={`Show full ${label}`}>Show full value</summary><code className="hash-full">{value}</code></details>
    <span role="status" className="hash-notice">{notice}</span>
  </div>;
}
