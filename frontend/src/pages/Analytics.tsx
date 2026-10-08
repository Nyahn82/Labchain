import { useState } from "react";
import { Link } from "react-router-dom";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { useResource } from "../api/useResource";
import { State, Title } from "../components/UI";
import { AnalyticsCard, BreakdownChart, TrendChart, analyticsValue } from "../components/AnalyticsCharts";
import type { AnalyticsData, Grain } from "../types/analytics";

export const analyticsPresets = ["Today", "Last 7 Days", "This Week", "Last 30 Days", "This Month", "This Quarter", "This Year", "Custom"] as const;
export function presetRange(preset: string, now = new Date()) {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const start = new Date(end);
  if (preset === "Last 7 Days") start.setUTCDate(start.getUTCDate() - 6);
  if (preset === "Last 30 Days") start.setUTCDate(start.getUTCDate() - 29);
  if (preset === "This Week") start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
  if (preset === "This Month") start.setUTCDate(1);
  if (preset === "This Quarter") { start.setUTCDate(1); start.setUTCMonth(Math.floor(start.getUTCMonth() / 3) * 3); }
  if (preset === "This Year") { start.setUTCDate(1); start.setUTCMonth(0); }
  return { date_from: start.toISOString().slice(0, 10), date_to: end.toISOString().slice(0, 10) };
}
const sections = [
  ["overview", "Selected period at a glance"], ["patients", "Patient trends"], ["orders", "Orders"],
  ["tests", "Test demand & department workload"], ["specimens", "Specimens & rejection events"],
  ["reports", "Reports, results & turnaround"], ["operations", "Referrals, arrival patterns & payments"], ["system", "System operations"],
];

export function Analytics() {
  return <PermissionGuard permission="ANALYTICS_VIEW"><AnalyticsContent /></PermissionGuard>;
}
function AnalyticsContent() {
  const { can } = useAuth();
  const [preset, setPreset] = useState("Last 30 Days");
  const [range, setRange] = useState(() => presetRange("Last 30 Days"));
  const [grain, setGrain] = useState<Grain>("auto");
  const [applied, setApplied] = useState(() => ({ ...presetRange("Last 30 Days"), grain: "auto" as Grain }));
  const [validation, setValidation] = useState("");
  const query = new URLSearchParams(applied).toString();
  return <div className="analytics-page page-shell">
    <Title title="Laboratory Analytics" eyebrow="ADMINISTRATION · OPERATIONAL INSIGHTS" />
    <section className="card analytics-controls" aria-label="Analytics date range">
      <form onSubmit={e => {
        e.preventDefault();
        if (!range.date_from || !range.date_to || range.date_from > range.date_to) { setValidation("Choose a valid start and end date."); return; }
        if ((Date.parse(range.date_to) - Date.parse(range.date_from)) / 86400000 >= 3660) { setValidation("Choose a range of at most 3660 days."); return; }
        setValidation(""); setApplied({ ...range, grain });
      }}>
        <label>Date range<select value={preset} onChange={e => { setPreset(e.target.value); if (e.target.value !== "Custom") setRange(presetRange(e.target.value)); }}>
          {analyticsPresets.map(p => <option key={p}>{p}</option>)}
        </select></label>
        <label>From (UTC)<input required type="date" min="1970-01-01" max="2100-12-31" value={range.date_from} onChange={e => { setPreset("Custom"); setRange({ ...range, date_from: e.target.value }); }} /></label>
        <label>Through (UTC)<input required type="date" min="1970-01-01" max="2100-12-31" value={range.date_to} onChange={e => { setPreset("Custom"); setRange({ ...range, date_to: e.target.value }); }} /></label>
        <label>Group by<select value={grain} onChange={e => setGrain(e.target.value as Grain)}>{["auto", "day", "week", "month", "quarter", "year"].map(g => <option key={g} value={g}>{g === "auto" ? "Automatic" : g[0].toUpperCase() + g.slice(1)}</option>)}</select></label>
        <button type="submit" className="primary">Apply range</button>
      </form>
      {validation && <p role="alert">{validation}</p>}
      <p className="muted">Showing {applied.date_from} through {applied.date_to}, inclusive · UTC · Weeks start Monday. Up to 120 buckets; choose a coarser grouping for long ranges.</p>
      <details><summary>Metric definitions</summary><dl>
        <dt>New patient registrations</dt><dd>Patient records created during the selected period; registration does not necessarily mean a laboratory encounter.</dd>
        <dt>Patients served</dt><dd>Distinct patients with non-cancelled orders created during the period.</dd>
        <dt>Returning patients</dt><dd>Patients served who had a non-cancelled order before the period. Trend buckets compare against each bucket’s start.</dd>
        <dt>Tests requested</dt><dd>Individual requested test items, including tests expanded from panels and cancelled requests. Panels are counted separately.</dd>
        <dt>Comparisons</dt><dd>The immediately preceding equal number of UTC calendar days. A zero previous baseline has no percentage change.</dd>
        <dt>Events and current states</dt><dd>Event counts use their own persisted timestamp. Status charts describe current states of records created or encoded during the selected period.</dd>
        <dt>Rejection ratio</dt><dd>Distinct specimens rejected per 100 specimens registered in the period. These are different cohorts; this is not a QC rejection probability.</dd>
      </dl></details>
    </section>
    <nav className="analytics-jumps" aria-label="Analytics sections">{sections.map(([key, title]) => <a key={key} href={`#analytics-${key}`} onClick={e => { e.preventDefault(); document.getElementById(`analytics-${key}`)?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }}>{title}</a>)}</nav>
    <div key={query}>{sections.map(([name, title]) => <AnalyticsSection key={name} name={name} title={title} query={query} />)}</div>
    <section className="card"><h2>Continue in the workspace</h2><div className="actions">
      {can("LAB_ORDER_READ") && <Link to="/orders">Orders</Link>}{can("REPORT_READ") && <Link to="/reports">Reports</Link>}
      {can("AUTH_ACTIVITY_VIEW") && <Link to="/administration/activity">Authentication Activity</Link>}
      {can("BLOCKCHAIN_EXPLORER_VIEW") && <Link to="/administration/blockchain">Blockchain Monitor</Link>}
    </div><p className="muted">These links open existing workspaces with their own permissions and filters.</p></section>
  </div>;
}
function AnalyticsSection({ name, title, query }: { name: string; title: string; query: string }) {
  const state = useResource<AnalyticsData>(`/admin/analytics/${name}?${query}`);
  const data = state.data;
  const empty = name === "orders" && data?.breakdowns.find(b => b.key === "order_status")?.total === 0 ? "No orders in this period" :
    name === "specimens" && data && data.metrics.every(m => !m.value) ? "No specimen activity in this period" :
    name === "reports" && data?.metrics.find(m => m.key === "released")?.value === 0 ? "No released reports in this period" : null;
  return <section id={`analytics-${name}`} aria-labelledby={`analytics-heading-${name}`} className="card analytics-section">
    <div className="section-heading"><h2 id={`analytics-heading-${name}`}>{title}</h2>{state.error && <button onClick={state.reload}>Retry {title.toLowerCase()}</button>}</div>
    <State loading={state.loading} error={state.error} />
    {data && <>
      {name === "overview" && <p className="muted">Compared with {data.range.previous_date_from} through {data.range.previous_date_to} · Aggregation: {data.range.grain} · {data.range.timezone}</p>}
      {empty && <p className="analytics-empty">{empty}</p>}
      {data.metrics.length > 0 && <div className="analytics-kpis">{data.metrics.map(m => <AnalyticsCard key={m.key} metric={m} />)}</div>}
      <div className="analytics-grid">{data.series.map(s => <TrendChart key={s.key} series={s} />)}{data.breakdowns.map(b => <BreakdownChart key={b.key} data={b} />)}</div>
      {data.turnaround.length > 0 && <div className="table-scroll" tabIndex={0} role="region" aria-label={`${title} duration table`}><table><caption>Durations from persisted timestamps</caption><thead><tr><th scope="col">Stage</th><th scope="col">Average</th><th scope="col">Eligible samples</th><th scope="col">Excluded samples</th></tr></thead>
        <tbody>{data.turnaround.map(t => <tr key={t.key}><th scope="row">{t.label}<details><summary>Definition</summary><p>{t.definition}</p></details></th><td>{t.average_seconds === null ? "No eligible samples" : analyticsValue(t.average_seconds, "seconds")}</td><td>{t.sample_count}</td><td>{t.excluded_count} / {t.candidate_count}</td></tr>)}</tbody></table></div>}
      {data.notes.length > 0 && <ul className="analytics-notes">{data.notes.map(note => <li key={note}>{note}</li>)}</ul>}
    </>}
  </section>;
}
