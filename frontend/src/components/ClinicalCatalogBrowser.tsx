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
    return text.includes(search.toLowerCase()) && (!department || ids.some(id => String(testById.get(id)?.department_id) === department))
      && (!specimen || ids.some(id => (testById.get(id)?.sample_type_ids as number[] || []).includes(Number(specimen))))
      && (availability === "all" || (availability === "available" ? r.orderable : !r.orderable));
  });
  const selectedIds = new Set(selection?.test_ids || []);
  const selectedPanels = data?.panels.filter(p => selection?.panel_ids.includes(Number(p.panel_id))) || [];
  for (const panel of selectedPanels) for (const id of panel.test_ids as number[]) selectedIds.add(id);
  const specimenNames = (test: Row) => (test.sample_type_ids as number[] || []).map(id => data?.specimens.find(s => s.sample_type_id === id)?.sample_name).filter(Boolean).join(" / ");
  const specimenSummary = [...new Set([...selectedIds].flatMap(id => (testById.get(id)?.sample_type_ids as number[] || [])))];
  const reset = (setter: (v: string) => void) => (v: string) => { setter(v); setPage(1); };
  return <section className="card catalog-browser" aria-label="Examination catalog">
    <div className="section-heading"><div>
      {selection && <p className="eyebrow">02 · EXAMINATIONS</p>}
      <h2>{selection ? "Choose examinations and panels" : "Clinical laboratory catalog"}</h2>
      <p className="muted small">Search individual tests or panels. Availability and facility review status are shown separately.</p>
    </div>{data && <span className="catalog-count">{data.tests.length} tests · {data.panels.length} panels</span>}</div>
    <State {...state} />
    <div className="toolbar catalog-search">
      <label>Find examinations<input type="search" value={search} onChange={e => reset(setSearch)(e.target.value)} placeholder="Name, code or alternate name" /></label>
      <label>Catalog entries<select aria-label="Catalog entries" value={kind} onChange={e => reset(setKind)(e.target.value)}><option value="tests">Individual tests</option><option value="panels">Panels</option></select></label>
    </div>
    <div className="toolbar catalog-filters">
      <label>Department<select aria-label="Department" value={department} onChange={e => reset(setDepartment)(e.target.value)}><option value="">All departments</option>{data?.departments.map(d => <option key={String(d.department_id)} value={String(d.department_id)}>{String(d.department_name)}</option>)}</select></label>
      <label>Specimen type<select aria-label="Specimen type" value={specimen} onChange={e => reset(setSpecimen)(e.target.value)}><option value="">All specimens</option>{data?.specimens.map(s => <option key={String(s.sample_type_id)} value={String(s.sample_type_id)}>{String(s.sample_name)}</option>)}</select></label>
      <label>Service availability<select aria-label="Service availability" value={availability} onChange={e => reset(setAvailability)(e.target.value)}><option value="all">All services</option><option value="available">Available for ordering</option><option value="unavailable">Unavailable / awaiting review</option></select></label>
    </div>
    <div className={selection ? "catalog-layout" : ""}>
      <div className="catalog-results">
        {data && <p className="small muted" role="status">{rows.length} matching entries{rows.length > 20 && ` · Showing ${(page - 1) * 20 + 1}–${Math.min(page * 20, rows.length)}`}</p>}
        {data && !rows.length && <p className="empty empty-state">No matching examinations. Try another name or adjust the filters.</p>}
        {rows.slice((page - 1) * 20, page * 20).map(r => {
          const id = Number(kind === "tests" ? r.test_id : r.panel_id);
          const field = kind === "tests" ? "test_ids" : "panel_ids";
          const meta = r.catalog_metadata as Row | null;
          const name = String(r.test_name || r.panel_name);
          const checked = !!selection?.[field].includes(id);
          const names = [...new Set(componentIds(r).map(testId => testById.get(testId)).filter(Boolean).map(t => specimenNames(t!)))].filter(Boolean).join(" · ");
          return <article className={"catalog-row" + (checked ? " is-selected" : "")} key={`${kind}:${id}`}>
            <div className="catalog-row-heading">
              {selection && onChange ? <label className="check catalog-choice"><input type="checkbox" aria-label={`Select ${name}`} checked={checked} disabled={!r.orderable} onChange={e => onChange({ ...selection, [field]: e.target.checked ? [...selection[field], id] : selection[field].filter(v => v !== id) })} /><span>{name}</span></label> : <Link to={`/laboratory/${kind}/${id}`}><strong>{name}</strong></Link>}
              <span className="catalog-code">{String(r.test_code || r.panel_code)}</span>
            </div>
            <p className="catalog-specimens">{kind === "panels" && <strong>{componentIds(r).length} components · </strong>}{names || "Specimen mapping required"}</p>
            <div className="catalog-status"><Badge>{r.orderable ? "AVAILABLE" : "UNAVAILABLE"}</Badge>{r.facility_status != null && <Badge>{String(r.facility_status)}</Badge>}
              {!!r.orderable && r.facility_status === "UNREVIEWED" && <span>Simulation only · not clinically approved</span>}
              {!r.orderable && !!meta?.restricted_workflow && <span>Dedicated clinical workflow required</span>}
            </div>
            <details><summary>Components, specimens and configuration</summary>
              <ul className="component-list">{componentIds(r).map(testId => { const test = testById.get(testId); return test && <li key={testId}><strong>{String(test.test_name)}</strong><span>{specimenNames(test) || "Specimen mapping required"} · {String(test.result_type)}{test.default_unit ? ` (${test.default_unit})` : ""}</span></li>; })}</ul>
              {!!meta?.service_tier && <p className="small">{String(meta.service_tier)}</p>}
              {!!meta?.review_note && <p className="small">{String(meta.review_note)}</p>}
              {!!meta?.restricted_workflow && <p role="note">{String(meta.restricted_workflow)}</p>}
              {selection && <Link to={`/laboratory/${kind}/${id}`} target="_blank" rel="noreferrer">Open examination definition in a new tab</Link>}
            </details>
          </article>;
        })}
        {rows.length > 20 && <nav className="pagination" aria-label="Catalog pages"><button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous examinations</button><span>Page {page} of {Math.ceil(rows.length / 20)}</span><button type="button" disabled={page * 20 >= rows.length} onClick={() => setPage(page + 1)}>Next examinations</button></nav>}
      </div>
      {selection && <section className="catalog-selection" aria-label="Selected examination summary">
        <p className="eyebrow">03 · REVIEW SELECTION</p><h3>Selected examinations ({selectedIds.size} unique)</h3>
        {selectedIds.size === 0 ? <p className="muted">Select tests or panels from the catalog. Their specimen requirements will appear here.</p> : <>
          <div className="selected">{[...selectedPanels.map(p => ({id:Number(p.panel_id),field:"panel_ids" as const,name:String(p.panel_name)})), ...selection.test_ids.map(id => ({id,field:"test_ids" as const,name:String(testById.get(id)?.test_name || id)}))].map(item => <span className="chip" key={item.field+item.id}>{item.name}<button type="button" aria-label={`Remove ${item.name}`} onClick={() => onChange?.({...selection,[item.field]:selection[item.field].filter(id => id !== item.id)})}>×</button></span>)}</div>
          <h4>Specimen requirements</h4><ul>{specimenSummary.map(id => <li key={id}>{String(data?.specimens.find(s => s.sample_type_id === id)?.sample_name || id)}</li>)}</ul>
          <details><summary>Review all {selectedIds.size} components</summary><ul className="component-list">{[...selectedIds].map(id => { const t = testById.get(id); return <li key={id}><strong>{String(t?.test_name || id)}</strong><span>{t && specimenNames(t)}</span></li>; })}</ul></details>
          <p className="small muted">Overlapping panels and individually selected tests share one result entry. Different specimen types require separate registrations.</p>
        </>}
      </section>}
    </div>
  </section>;
}
