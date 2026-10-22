import { SpecimenGuidance } from "./SpecimenGuidance";
import { Table } from "./UI";
import type { Row } from "../types/domain";
export function OrderedExaminations({ items }: { items: Row[] }) {
  const rows = items.map(item => {
    const definition = item.definition_snapshot as { test: Row; panels: Row[]; specimens: Row[] } | null;
    const test = definition?.test || item.test as Row;
    return { ...item, examination: test?.test_name || item.test_id, panels: definition?.panels.map(p => String(p.panel_name)).join(" / ") || "Individual test",
      specimens: definition?.specimens.map(s => String(s.sample_name)).join(" / ") || "Legacy order: review current specimen mapping", definition, test };
  });
  return <section className="card"><h2>Ordered examinations and specimen requirements</h2>
    <Table rows={rows} caption="Ordered examinations" columns={[
      {key:"examination",label:"Examination"}, {key:"panels",label:"Panel / request"},
      {key:"specimens",label:"Compatible specimens"},
      {key:"definition",label:"Collection and format",render: row => {
        const definition = row.definition as { specimens: Row[] } | null, test = row.test as Row;
        return <details><summary>View guidance</summary>{definition?.specimens.map(s => <SpecimenGuidance key={String(s.sample_type_id)} specimen={s} />)}
          <p>Format: {String(test?.result_type || "See test details")} · Unit: {String(test?.default_unit || "Facility configuration required")}</p></details>;
      }},
    ]} />
  </section>;
}
