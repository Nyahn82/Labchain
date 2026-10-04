import { useId } from "react";
import { Badge } from "./UI";
import { timestamp } from "../utils/display";
import type {
  BlockchainAnchoringStatus,
  ReportAnchoring,
  ReportAnchoringLifecycle,
  SafeAnchoringStatus,
} from "../types/blockchain";

const presentation = {
  NOT_ANCHORED: { label: "Not anchored", tone: "neutral" },
  PENDING: { label: "Anchoring pending", tone: "info" },
  PROCESSING: { label: "Anchoring in progress", tone: "info" },
  RETRYING: { label: "Anchoring retry scheduled", tone: "warning" },
  CONFIRMED: { label: "Anchored", tone: "success" },
  FAILED: { label: "Anchoring failed", tone: "danger" },
} satisfies Record<BlockchainAnchoringStatus, { label: string; tone: string }>;

function isAnchoringStatus(status: unknown): status is BlockchainAnchoringStatus {
  return typeof status === "string" && Object.hasOwn(presentation, status);
}
export function isSafeAnchoringStatus(status: unknown): status is SafeAnchoringStatus {
  return isAnchoringStatus(status) && status !== "PROCESSING";
}
export function AnchoringBadge({ status }: { status: BlockchainAnchoringStatus }) {
  const item = isAnchoringStatus(status) ? presentation[status] : undefined;
  return (
    <span className={`anchoring-state tone-${item?.tone || "neutral"}`}>
      <Badge>{item?.label || "Anchoring status unavailable"}</Badge>
    </span>
  );
}
function EvidenceNote() {
  return (
    <p className="small muted">
      Blockchain anchoring records tamper-evident evidence for this report.
      It does not determine the clinical validity of the report.
    </p>
  );
}
function ConfirmationTime({ at }: { at?: string | null }) {
  return at == null ? null : (
    <p className="small">Confirmed: {timestamp(at)}</p>
  );
}
function Lifecycle({ label, event }: {
  label: string;
  event?: ReportAnchoringLifecycle | null;
}) {
  const id = useId();
  return (
    <section className="anchoring-lifecycle" aria-labelledby={id}>
      <h3 id={id}>{label}</h3>
      {event ? (
        <>
          <AnchoringBadge status={event.status} />
          {event.status === "CONFIRMED" && (
            <>
              <ConfirmationTime at={event.confirmed_at} />
              <dl className="anchoring-receipt">
                {typeof event.transaction_id === "string" && event.transaction_id && (
                  <div>
                    <dt>Transaction ID</dt>
                    <dd><code>{event.transaction_id}</code></dd>
                  </div>
                )}
                {typeof event.block_number === "number" &&
                  Number.isInteger(event.block_number) && event.block_number >= 0 && (
                    <div><dt>Block number</dt><dd>{event.block_number}</dd></div>
                  )}
              </dl>
            </>
          )}
        </>
      ) : <p className="muted">Not applicable</p>}
    </section>
  );
}
export function StaffReportAnchoring({ anchoring }: {
  anchoring?: ReportAnchoring | null;
}) {
  const id = useId();
  return (
    <section className="card anchoring-panel" aria-labelledby={id}>
      <h2 id={id}>Blockchain anchoring</h2>
      <div className="anchoring-lifecycles" aria-live="polite">
        <Lifecycle label="Release" event={anchoring?.release ?? { status: "NOT_ANCHORED" }} />
        <Lifecycle label="Revocation" event={anchoring?.revocation} />
        <Lifecycle label="Supersession" event={anchoring?.supersession} />
      </div>
      <EvidenceNote />
    </section>
  );
}
const safeMessages: Record<SafeAnchoringStatus, string> = {
  NOT_ANCHORED: "No blockchain anchor is available for this report.",
  PENDING: "Blockchain anchoring is pending.",
  RETRYING: "The laboratory is retrying blockchain anchoring.",
  CONFIRMED: "Tamper-evident evidence for this report has been anchored.",
  FAILED: "Blockchain anchoring requires laboratory attention. This does not by itself mean the report is invalid.",
};
// Deliberately accepts only safe scalar fields, never a full report/receipt object.
export function SafeReportAnchoring({ status = "NOT_ANCHORED", confirmedAt, audience }: {
  status?: SafeAnchoringStatus;
  confirmedAt?: string | null;
  audience: "patient" | "public";
}) {
  const id = useId();
  const safe = isSafeAnchoringStatus(status);
  const Heading = audience === "public" ? "h3" : "h2";
  return (
    <section
      className={audience === "patient" ? "card anchoring-panel" : "anchoring-panel anchoring-public"}
      aria-labelledby={id}
    >
      <Heading id={id}>{audience === "patient" ? "Blockchain verification" : "Blockchain anchoring"}</Heading>
      <div aria-live="polite">
        {safe ? (
          <>
            <AnchoringBadge status={status} />
            <p>{safeMessages[status]}</p>
            {audience === "patient" && (status === "PENDING" || status === "RETRYING") && (
              <p>Your released report remains available.</p>
            )}
            {status === "CONFIRMED" && <ConfirmationTime at={confirmedAt} />}
          </>
        ) : <p>Anchoring status unavailable</p>}
      </div>
      {audience === "public" && (
        <p>The laboratory report verification above remains based on the laboratory’s official report record.</p>
      )}
      <EvidenceNote />
    </section>
  );
}
