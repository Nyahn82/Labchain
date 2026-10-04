import { useId } from "react";
import { useResource } from "../api/useResource";
import { Badge } from "./UI";
import { timestamp } from "../utils/display";
import type { BlockchainStatusResponse, BlockchainWorkerHealth } from "../types/blockchain";

const health = {
  IDLE: { label: "Idle", tone: "neutral" },
  ACTIVE: { label: "Active", tone: "info" },
  DEGRADED: { label: "Degraded", tone: "warning" },
  ERROR: { label: "Attention required", tone: "danger" },
} satisfies Record<BlockchainWorkerHealth, { label: string; tone: string }>;
const counts = [
  ["pending", "Pending"],
  ["processing", "Processing"],
  ["confirmed", "Confirmed"],
  ["failed", "Retrying"],
  ["dead", "Failed"],
] as const;

// Mount only after the dashboard's existing permission check succeeds.
export function BlockchainQueue() {
  const id = useId();
  const { data, loading, error } = useResource<BlockchainStatusResponse>("/blockchain/status");
  const valid = data && typeof data.worker_health === "string" &&
    Object.hasOwn(health, data.worker_health) && data.counts &&
    counts.every(([key]) => Number.isInteger(data.counts[key]) && data.counts[key] >= 0);
  const state = valid ? health[data.worker_health] : undefined;
  return (
    <section className="card anchoring-panel" aria-labelledby={id}>
      <h2 id={id}>Blockchain anchoring</h2>
      {loading ? <p role="status">Loading anchoring queue status…</p> :
        error || !state || !data ? <p role="alert">Anchoring status unavailable</p> : (
          <>
            <p aria-live="polite">
              Anchoring queue status: {" "}
              <span className={`anchoring-state tone-${state.tone}`}><Badge>{state.label}</Badge></span>
            </p>
            <dl className="details anchoring-counts">
              {counts.map(([key, label]) => (
                <div key={key}><dt>{label}</dt><dd>{data.counts[key]}</dd></div>
              ))}
            </dl>
            <p className="small">Last confirmed: {data.last_confirmed_at == null ? "Never" : timestamp(data.last_confirmed_at)}</p>
            <p className="small muted">
              Worker configuration: {data.delivery_enabled === true ? "Enabled (reported configuration)" :
                data.delivery_enabled === false ? "Disabled (reported configuration)" : "Not reported by this API"}
            </p>
          </>
        )}
      <p className="small muted">Based on the anchoring queue. This does not establish worker service or Fabric network availability.</p>
    </section>
  );
}
