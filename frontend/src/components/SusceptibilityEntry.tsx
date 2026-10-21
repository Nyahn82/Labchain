export type Susceptibility = Record<"organism" | "antimicrobial" | "measurement" | "unit" | "interpretation" | "method" | "standard", string>;
export function SusceptibilityEntry({ rows, onChange }: { rows: Susceptibility[]; onChange: (r: Susceptibility[]) => void }) {
  const labels: Record<keyof Susceptibility, string> = { organism: "Organism", antimicrobial: "Antimicrobial", measurement: "Measured MIC / zone", unit: "Measurement unit", interpretation: "Authorized interpretation", method: "Test method", standard: "Interpretation standard and version" };
  return <section><h3>Antimicrobial susceptibility observations</h3>
    <p>Enter laboratory-approved observations. No antibiotic recommendation or breakpoint interpretation is generated automatically.</p>
    {rows.map((r, i) => <fieldset key={i}><legend>Observation {i + 1}</legend>{(Object.keys(labels) as (keyof Susceptibility)[]).map(k => <label key={k}>{labels[k]}{k === "interpretation" ? <select value={r[k]} onChange={e => onChange(rows.map((row, n) => n === i ? {...row, [k]: e.target.value} : row))}><option value="">Choose interpretation</option>{["S", "I", "R", "SDD", "NS", "NOT_INTERPRETED"].map(v => <option key={v}>{v}</option>)}</select> : <input maxLength={120} value={r[k]} onChange={e => onChange(rows.map((row, n) => n === i ? {...row, [k]: e.target.value} : row))} />}</label>)}<button type="button" onClick={() => onChange(rows.filter((_, n) => n !== i))}>Remove observation {i + 1}</button></fieldset>)}
    <button type="button" disabled={rows.length >= 80} onClick={() => onChange([...rows, {organism: "", antimicrobial: "", measurement: "", unit: "", interpretation: "", method: "", standard: ""}])}>Add susceptibility observation</button>
  </section>;
}
