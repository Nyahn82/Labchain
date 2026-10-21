import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/Auth";
import { Alert, State } from "./UI";

type Item = {
  kind: string; key: string; name: string; action: string;
  record_id: number | null; code: string | null;
  definition: { department?: string; samples?: string[]; tests?: string[];
    result_type?: string; description?: string; review_note?: string;
    reference_policy?: string; sources?: string[] };
};
type Preview = {
  version: string; fingerprint: string; notice: string;
  inventory: Record<string, number>; create_count: number; preserved_count: number;
  conflicts: string[]; items: Item[]; sources: Record<string, { title: string; url: string }>;
};
type Imported = { created: { kind: string; name: string; code: string | null; record_id: number }[]; preserved_count: number; notice: string };
const manage = ["LAB_DEPARTMENT_MANAGE", "SAMPLE_TYPE_MANAGE", "TEST_CATALOG_MANAGE", "TEST_PANEL_MANAGE"];

export function StarterCatalog({ expanded = false }: { expanded?: boolean }) {
  const endpoint = expanded ? "/lab/clinical-catalog" : "/lab/starter-catalog";
  const { can, user } = useAuth();
  const [preview, setPreview] = useState<Preview>();
  const [result, setResult] = useState<Imported>();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  if (!can("LAB_MASTER_READ") || user?.patient || user?.roles.includes("PATIENT")) return null;
  const editable = manage.every(can);
  async function load() {
    setBusy(true); setError(undefined); setPreview(undefined); setConfirmed(false); setResult(undefined);
    try { setPreview(await api<Preview>(endpoint)); }
    catch (e) { setError(e as Error); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!preview || !confirmed || preview.conflicts.length || busy) return;
    setBusy(true); setError(undefined);
    try {
      setResult(await api<Imported>(endpoint, { method: "POST", body: {
        fingerprint: preview.fingerprint, acknowledge_inactive_review: true,
      } }));
      setPreview(undefined); setConfirmed(false);
    } catch (e) {
      setError(e as Error); setPreview(undefined); setConfirmed(false);
    } finally { setBusy(false); }
  }
  const names = (kind: string, keys?: string[]) => keys?.map(key => preview?.items.find(i => i.kind === kind && i.key === key)?.name || key).join(", ");
  return <section className="card" aria-labelledby="starter-heading">
    <h2 id="starter-heading">{expanded ? "Import Philippine clinical catalog" : "Philippine laboratory starter catalog"}</h2>
    <p>Review proposed departments, specimen types, tests and panels before adding them to your existing catalog. New entries remain inactive. Inclusion does not establish facility capability or authorization to perform a test.</p>
    <button disabled={busy} onClick={load}>Preview starter catalog</button>
    <State loading={busy} />
    <Alert error={error} />
    {error && <p>Review a fresh preview before retrying. Existing catalog data is preserved.</p>}
    {result && <div role="status" className="success">
      <p>Catalog import complete: {result.created.length} inactive entries added; {result.preserved_count} existing entries preserved.</p>
      <p>{result.notice}</p>
      <ul>{result.created.map(i => <li key={`${i.kind}:${i.record_id}`}>{i.name}{i.code ? ` · ${i.code}` : ""}</li>)}</ul>
      <Link to="/laboratory/tests">Review tests and approved configuration →</Link>
    </div>}
    {preview && <>
      <p><strong>{preview.version}</strong> · {Object.entries(preview.inventory).map(([k, n]) => `${n} ${k}`).join(" · ")}</p>
      <p>{preview.notice}</p>
      <p>{preview.create_count} proposed additions · {preview.preserved_count} existing matches preserved</p>
      {!!preview.conflicts.length && <div role="alert"><strong>Import blocked: resolve ambiguous mappings first.</strong><ul>{preview.conflicts.map(c => <li key={c}>{c}</li>)}</ul></div>}
      {!preview.create_count && !preview.conflicts.length && <p role="status">Nothing to add. Existing codes, clinical configuration and relationships will remain unchanged.</p>}
      <details><summary>Review all entries, specimen associations and panel members</summary>
        {Object.keys(preview.inventory).map(kind => <section key={kind}>
          <h3>{kind.charAt(0).toUpperCase() + kind.slice(1)}</h3>
          <ul>{preview.items.filter(i => i.kind === kind).map(item => <li key={item.key}>
            <strong>{item.name}</strong> · {item.action === "PRESERVE" ? "Preserve existing configuration" : "Create inactive"}{item.code && ` · ${item.code}`}
            <p>{names("departments", item.definition.department ? [item.definition.department] : [])}{item.definition.result_type && ` · ${item.definition.result_type}`}</p>
            {item.definition.samples && <p>Proposed specimens: {names("samples", item.definition.samples)}. No default container or additive is assigned.</p>}
            {item.definition.tests && <p>Proposed members: {names("tests", item.definition.tests)}</p>}
            <p>{item.definition.review_note || item.definition.description}</p>
            {item.definition.reference_policy && <p>{item.definition.reference_policy} Units, methods and reference values are left unconfigured.</p>}
            {item.definition.sources?.map(key => <p key={key}><a href={preview.sources[key].url} target="_blank" rel="noreferrer">{preview.sources[key].title}</a></p>)}
          </li>)}</ul>
        </section>)}
      </details>
      <p>Matches use catalog names and documented aliases, not predicted codes. Existing sample mappings and panel memberships are preserved even when they differ from these proposals. Resolve other local synonyms before import.</p>
      {editable && preview.create_count > 0 && !preview.conflicts.length && <>
        <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I reviewed this preview and understand that new entries must remain inactive until facility approval.</label>
        <button className="primary" disabled={!confirmed || busy} onClick={apply}>Import inactive starter entries</button>
      </>}
      {!editable && <p>Import requires department, sample type, test catalog and panel management permissions.</p>}
    </>}
  </section>;
}
