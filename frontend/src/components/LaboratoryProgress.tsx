import { Link } from "react-router-dom";
import { useAuth } from "../auth/Auth";
import { Badge } from "./UI";
import type { Order } from "../types/domain";

export function LaboratoryProgress({ order }: { order: Order }) {
  const { can } = useAuth();
  const items = order.items.filter(item => item.status !== "CANCELLED");
  const completed = items.filter(item => item.status === "COMPLETED").length;
  const patientId = (order.patient as { patient_id?: number }).patient_id;
  return <section className="card laboratory-progress" aria-labelledby="laboratory-progress-heading">
    <div className="section-heading"><h2 id="laboratory-progress-heading">Laboratory workflow</h2><Badge>{order.priority}</Badge></div>
    <p>{order.status === "CANCELLED" ? "This order is cancelled. Its history remains available." :
      order.status === "COMPLETED" ? "Testing is complete. Report signing, approval and release are separate steps." :
        "Collect and receive suitable specimens, enter results, then review and verify each result."}</p>
    <div className="laboratory-stages">
      <article><span className="eyebrow">01 · REQUEST</span><h3>{items.length} requested tests</h3>
        <p>{completed} completed · {items.length - completed} remaining</p><Link to={`/orders/${order.order_id}`}>Review request</Link></article>
      {can("SPECIMEN_READ") && <article><span className="eyebrow">02 · SPECIMENS</span><h3>{order.specimens.length} specimens</h3>
        <p>{order.specimens.filter(s => ["RECEIVED", "PROCESSED"].includes(s.specimen_status)).length} received or processed · {order.specimens.filter(s => s.specimen_status === "REJECTED").length} rejected</p>
        <Link to={`/orders/${order.order_id}/specimens`}>Collection & quality</Link></article>}
      {can("LAB_RESULT_READ") && <article><span className="eyebrow">03 · TESTING</span><h3>Enter → Review → Verify</h3>
        <p>Reviewed and verified values are read only. Flags are calculated by the laboratory service.</p><Link to={`/orders/${order.order_id}/results`}>Result workbench</Link></article>}
      {can("REPORT_READ") && <article><span className="eyebrow">04 · REPORTING</span><h3>Sign → Approve → Release</h3>
        <p>All reportable results must be verified before a report is generated.</p><Link to={`/orders/${order.order_id}/reports`}>Reports & versions</Link></article>}
    </div>
    {patientId && can("LAB_ORDER_CREATE") && can("PATIENT_READ") && <details className="laboratory-followup"><summary>Repeat investigations and follow-up</summary>
      <p>Record additional testing as a separate authorized order. Existing verified results and released reports remain unchanged. This creates a new request, not an amendment or an external referral.</p>
      <Link className="button" to={`/orders/new?patient_id=${patientId}`}>New request for this patient</Link>
    </details>}
  </section>;
}
