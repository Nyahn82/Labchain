import { useState } from "react";
import { api } from "../api/client";
import { Alert } from "./UI";
import type { Row } from "../types/domain";
export type ClinicalField = { key: string; label: string; kind: "number" | "text" | "choice"; unit?: string | null; choices: string[]; required: boolean };
export type ClinicalSchema = { version: number; fields: ClinicalField[]; susceptibility: boolean };
export function ResultSchemaEditor({ test, done }: { test: Row; done: () => void }) {
  const initial = test.result_schema as ClinicalSchema | null;
  const [fields, setFields] = useState<ClinicalField[]>(initial?.fields || []);
  const [susceptibility, setSusceptibility] = useState(initial?.susceptibility || false);
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  function change(i: number, patch: Partial<ClinicalField>) { setFields(rows => rows.map((r, n) => n === i ? { ...r, ...patch } : r)); }
  return <section className="card"><h2>Structured result configuration</h2>
    <p>Scalar test values remain in the standard result field. Use key result_value to constrain that field to approved options. Additional fields appear in result entry and the released PDF. Referenced examination definitions cannot be changed.</p>
    {fields.map((f, i) => <fieldset key={i}><legend>Field {i + 1}</legend>
      <label>Field key<input value={f.key} onChange={e => change(i, { key: e.target.value })} /></label>
      <label>Field label<input value={f.label} onChange={e => change(i, { label: e.target.value })} /></label>
      <label>Field format<select value={f.kind} onChange={e => change(i, { kind: e.target.value as ClinicalField["kind"] })}><option value="text">Text</option><option value="number">Number</option><option value="choice">Approved options</option></select></label>
      <label>Field unit<input value={f.unit || ""} onChange={e => change(i, { unit: e.target.value || null })} /></label>
      {f.kind === "choice" && <label>Options (one per line)<textarea value={f.choices.join("\n")} onChange={e => change(i, { choices: e.target.value.split("\n") })} /></label>}
      <label><input type="checkbox" checked={f.required} onChange={e => change(i, { required: e.target.checked })} />Required before review</label>
      <button type="button" onClick={() => setFields(rows => rows.filter((_, n) => n !== i))}>Remove field {i + 1}</button>
    </fieldset>)}
    <button type="button" disabled={fields.length >= 40} onClick={() => setFields([...fields, { key: "", label: "", kind: "text", choices: [], required: true }])}>Add result field</button>
    <label><input type="checkbox" checked={susceptibility} onChange={e => setSusceptibility(e.target.checked)} />Structured organism / antimicrobial susceptibility observations</label>
    <Alert error={error} />
    <button type="button" disabled={busy} onClick={async () => { setBusy(true); setError(undefined); try { await api(`/lab/tests/${test.test_id}`, { method: "PATCH", body: { result_schema: { version: 1, fields, susceptibility } } }); done(); } catch (e) { setError(e as Error); } finally { setBusy(false); } }}>Save result configuration</button>
  </section>;
}
