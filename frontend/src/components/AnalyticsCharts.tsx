import { useId } from "react";
import type { AnalyticsBreakdown, AnalyticsMetric, AnalyticsSeries } from "../types/analytics";

export function analyticsValue(value: number | null, unit = "count") {
  if (value === null || !Number.isFinite(value)) return "—";
  if (unit === "seconds") {
    const magnitude = Math.abs(value);
    const divisor = magnitude >= 86400 ? 86400 : magnitude >= 3600 ? 3600 : magnitude >= 60 ? 60 : 1;
    return `${(value / divisor).toLocaleString(undefined, { maximumFractionDigits: 1 })} ${divisor === 86400 ? "days" : divisor === 3600 ? "hours" : divisor === 60 ? "min" : "sec"}`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: unit === "count" ? 0 : 2 }) + (unit === "percent" ? "%" : "");
}

export function AnalyticsCard({ metric }: { metric: AnalyticsMetric }) {
  return <article className="analytics-kpi" aria-label={metric.label}>
    <p>{metric.label}</p>
    <strong>{analyticsValue(metric.value, metric.unit)}</strong>
    {metric.value === null && <small>{metric.unit === "seconds" ? "No eligible samples" : "No recorded baseline"}</small>}
    {metric.compared && <div className="analytics-comparison">
      {metric.previous_value === null || metric.value === null ? "No comparable previous data" : metric.percent_change === null ? "No previous baseline" :
        <>{metric.absolute_change !== null && metric.absolute_change > 0 ? "+" : ""}{analyticsValue(metric.absolute_change, metric.unit)} · {metric.percent_change > 0 ? "+" : ""}{analyticsValue(metric.percent_change, "percent")}</>}
      <small>Previous: {analyticsValue(metric.previous_value, metric.unit)}</small>
    </div>}
    <details className="metric-help"><summary>Definition</summary><p>{metric.definition}</p></details>
  </article>;
}

export function TrendChart({ series }: { series: AnalyticsSeries }) {
  const id = useId();
  const max = Math.max(0, ...series.points.map(p => p.value));
  const width = 640, height = 160, bar = width / Math.max(1, series.points.length);
  return <figure className="analytics-chart">
    <figcaption id={id}>{series.label}</figcaption>
    <p className="muted">{series.definition}</p>
    {max === 0 ? <p className="analytics-empty">No activity in this period.</p> : <>
      <svg viewBox={`0 0 ${width} ${height + 12}`} role="img" aria-labelledby={id}>
        {series.points.map((p, i) => <rect key={p.bucket} x={i * bar + 1} y={height - (p.value / max) * height} width={Math.max(1, bar - 2)} height={(p.value / max) * height} rx={2} tabIndex={0} aria-label={`${p.bucket}: ${p.value}`}>
          <title>{p.bucket}: {p.value}</title>
        </rect>)}
      </svg>
      <div className="analytics-axis"><span>{series.points[0]?.bucket}</span><span>Peak bucket: {max}</span><span>{series.points.at(-1)?.bucket}</span></div>
    </>}
    <details><summary>View {series.label.toLowerCase()} data table</summary>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`${series.label} table`}>
        <table><caption>{series.label} · UTC bucket start dates</caption><thead><tr><th scope="col">Bucket start</th><th scope="col">Count</th></tr></thead>
          <tbody>{series.points.map(p => <tr key={p.bucket}><th scope="row">{p.bucket}</th><td>{p.value}</td></tr>)}</tbody></table>
      </div>
    </details>
  </figure>;
}

export function BreakdownChart({ data }: { data: AnalyticsBreakdown }) {
  const maximum = Math.max(0, ...data.items.map(item => item.count));
  const department = data.key === "departments";
  return <section className="analytics-breakdown" aria-label={data.label}>
    <h3>{data.label}</h3><p className="muted">{data.definition}</p>
    {!data.total ? <p className="analytics-empty">No records in this period.</p> : <>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`${data.label} table`}>
        <table><caption className="sr-only">{data.label}</caption><thead><tr><th scope="col">Category</th><th scope="col">Count</th><th scope="col">Share</th>
          {department && <><th scope="col">Currently drafted</th><th scope="col">Currently reviewed</th><th scope="col">Currently verified</th></>}</tr></thead>
          <tbody>{data.items.map(item => <tr key={item.key}><th scope="row"><span>{item.label.replaceAll("_", " ")}</span>
            {item.code && <small>{item.code}{item.department ? ` · ${item.department}` : ""}</small>}
            <span aria-hidden="true" className="analytics-bar-track"><span style={{ width: `${maximum ? 100 * item.count / maximum : 0}%` }} /></span>
          </th><td>{analyticsValue(item.count)}</td><td>{analyticsValue(item.share, "percent")}</td>
            {department && <><td>{item.drafted ?? 0}</td><td>{item.reviewed ?? 0}</td><td>{item.verified ?? 0}</td></>}</tr>)}
          {data.other_count > 0 && <tr><th scope="row">Other categories</th><td>{data.other_count}</td><td>{analyticsValue(100 * data.other_count / data.total, "percent")}</td>{department && <td colSpan={3}>Not shown in top departments</td>}</tr>}
          </tbody></table>
      </div>
      <p className="muted">Total: {analyticsValue(data.total)}</p>
    </>}
  </section>;
}
