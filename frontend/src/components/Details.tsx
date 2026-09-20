import { display, value, timestamp } from "../utils/display";
import type { Row } from "../types/domain";
export function Details({
  row,
  fields,
}: {
  row: Row;
  fields: (string | [string, string])[];
}) {
  return (
    <dl className="details">
      {fields.map((f) => {
        const [key, label] = Array.isArray(f) ? f : [f, f.replaceAll("_", " ")];
        return (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {key.endsWith("_at") || key === "order_date"
                ? timestamp(value(row, key))
                : display(value(row, key))}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
