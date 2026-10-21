import { SpecimenGuidance } from "./SpecimenGuidance";
import type { Row } from "../types/domain";
export function OrderedExaminations({ items }: { items: Row[] }) {
  return <section className="card"><h2>Ordered examinations and specimen requirements</h2>
    {items.map(item => {
      const definition = item.definition_snapshot as { test: Row; panels: Row[]; specimens: Row[] } | null;
      const test = definition?.test || item.test as Row;
      return <details key={String(item.order_item_id)}><summary>{String(test?.test_name || item.test_id)}</summary>
        <p>Panels: {definition?.panels.map(p => String(p.panel_name)).join(" / ") || "Individual test"}</p>
        <p>Compatible specimens: {definition?.specimens.map(s => String(s.sample_name)).join(" / ") || "Legacy order: review current specimen mapping"}</p>
        {definition?.specimens.map(s => <SpecimenGuidance key={String(s.sample_type_id)} specimen={s} />)}
        <p>Format: {String(test?.result_type || "See test details")} · Unit: {String(test?.default_unit || "Facility configuration required")}</p>
      </details>;
    })}
  </section>;
}
