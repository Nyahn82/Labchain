import { useState } from "react";
import { Link } from "react-router-dom";
import { useResource } from "../api/useResource";
import { useAuth } from "../auth/Auth";
import { State, Badge } from "./UI";
import type { Row } from "../types/domain";
export type CatalogSelection = { test_ids: number[]; panel_ids: number[] };
type Catalog = { tests: Row[]; panels: Row[]; departments: Row[]; specimens: Row[] };
export function ClinicalCatalogBrowser({ selection, onChange }: { selection?: CatalogSelection; onChange?: (s: CatalogSelection) => void }) {
  const { can } = useAuth();
  const state = useResource<Catalog>(can("LAB_MASTER_READ") ? "/lab/catalog-browser" : null);
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [specimen, setSpecimen] = useState("");
  const [availability, setAvailability] = useState(selection ? "available" : "all");
  const [kind, setKind] = useState("tests");
  const [page, setPage] = useState(1);
  const data = state.data;
  if (!can("LAB_MASTER_READ")) return <p>Catalog read permission is required to select examinations.</p>;
  const testById = new Map(data?.tests.map(t => [Number(t.test_id), t]));
  const componentIds = (r: Row): number[] => kind === "tests" ? [Number(r.test_id)] : r.test_ids as number[];
  const source = data ? (kind === "tests" ? data.tests : data.panels) : [];
  const rows = source.filter(r => {
    const ids = componentIds(r);
    const text = `${r.test_name || r.panel_name} ${r.test_code || r.panel_code} ${r.aliases || ""}`.toLowerCase();
    return text.includes(search.toLowerCase()) && (!department || String(r.department_id) === department)
      && (!specimen || ids.some(id => (testById.get(id)?.sample_type_ids as number[] || []).includes(Number(specimen))))
      && (availability === "all" || (availability === "available" ? r.orderable : !r.orderable));
  });
  const selectedIds = new Set(selection?.test_ids || []);
  for (const panel of data?.panels || []) if (selection?.panel_ids.includes(Number(panel.panel_id)))
    for (const id of panel.test_ids as number[]) selectedIds.add(id);
  const specimenNames = (test: Row) => (test.sample_type_ids as number[] || []).map(id => data?.specimens.find(s => s.sample_type_id === id)?.sample_name).filter(Boolean).join(" / ");
  const reset = (setter: (v: string) => void) => (v: string) => { setter(v); setPage(1); };
  return <section className="card" aria-label="Examination catalog">
    <h2>{selection ? "Choose examinations and panels" : "Clinical laboratory catalog"}</h2>
    <p>Availability requires facility approval. Each component retains its own specimen requirements. A catalog listing does not authorize a service.</p>
    <State {...state} />
    <div className="toolbar">
      <label>Find examinations<input type="search" value={search} onChange={e => reset(setSearch)(e.target.value)} placeholder="Name, code or alternate name" /></label>
      <label>Catalog entries<select aria-label="Catalog entries" value={kind} onChange={e => reset(setKind)(e.target.value)}><option value="tests">Individual tests</option><option value="panels">Panels</option></select></label>
      <label>Department<select aria-label="Department" value={department} onChange={e => reset(setDepartment)(e.target.value)}><option value="">All departments</option>{data?.departments.map(d => <option key={String(d.department_id)} value={String(d.department_id)}>{String(d.department_name)}</option>)}</select></label>
      <label>Specimen type<select aria-label="Specimen type" value={specimen} onChange={e => reset(setSpecimen)(e.target.value)}><option value="">All specimens</option>{data?.specimens.map(s => <option key={String(s.sample_type_id)} value={String(s.sample_type_id)}>{String(s.sample_name)}</option>)}</select></label>
      <label>Service availability<select aria-label="Service availability" value={availability} onChange={e => reset(setAvailability)(e.target.value)}><option value="all">All services</option><option value="available">Approved and available</option><option value="unavailable">Unavailable / awaiting review</option></select></label>
    </div>
    {data && <p>{data.tests.length} test/analyte entries · {data.panels.length} panels · {rows.length} matching entries</p>}
    {data && !rows.length && <p>No matching examinations. Imported services need facility review before ordering.</p>}
    {rows.slice((page - 1) * 20, page * 20).map(r => {
      const id = Number(kind === "tests" ? r.test_id : r.panel_id);
      const field = kind === "tests" ? "test_ids" : "panel_ids";
      const meta = r.catalog_metadata as Row | null;
      return <article className="card compact" key={`${kind}:${id}`}>
        {selection && onChange && <label className="check"><input type="checkbox" checked={selection[field].includes(id)} disabled={!r.orderable} onChange={e => onChange({ ...selection, [field]: e.target.checked ? [...selection[field], id] : selection[field].filter(v => v !== id) })} />Select {String(r.test_name || r.panel_name)}</label>}
        <Link to={`/laboratory/${kind}/${id}`}><strong>{String(r.test_name || r.panel_name)}</strong></Link> · {String(r.test_code || r.panel_code)}
        <p><Badge>{r.orderable ? "AVAILABLE" : String(r.facility_status || "UNAVAILABLE")}</Badge> {String(meta?.service_tier || "Facility configuration")}</p>
        <details><summary>Components, specimens and configuration</summary>
          <ul>{componentIds(r).map(testId => { const test = testById.get(testId); return test && <li key={testId}>{String(test.test_name)} — {specimenNames(test) || "Specimen mapping required"}; {String(test.result_type)}{test.default_unit ? ` (${test.default_unit})` : ""}</li>; })}</ul>
          {!!meta?.review_note && <p>{String(meta.review_note)}</p>}
          {!!meta?.restricted_workflow && <p role="note">{String(meta.restricted_workflow)}</p>}
        </details>
      </article>;
    })}
    {rows.length > 20 && <nav aria-label="Catalog pages"><button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous examinations</button><span> Page {page} </span><button type="button" disabled={page * 20 >= rows.length} onClick={() => setPage(page + 1)}>Next examinations</button></nav>}
    {selection && <section aria-label="Selected examination summary"><h3>Selected examinations ({selectedIds.size} unique)</h3>
      <p>Panels selected: {data?.panels.filter(p => selection.panel_ids.includes(Number(p.panel_id))).map(p => String(p.panel_name)).join(", ") || "None"}</p>
      <ul>{[...selectedIds].map(id => { const t = testById.get(id); return <li key={id}>{String(t?.test_name || id)} — {t && specimenNames(t)}</li>; })}</ul>
      <p>Overlapping panels and individually selected tests share one result entry. Different specimen types require separate registrations.</p>
    </section>}
  </section>;
}
