import { useState, type FormEvent } from "react";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { useResource } from "../api/useResource";
import { Info, CheckCircle2, XCircle, CircleHelp } from "lucide-react";
import { Tabs } from "../components/Tabs";
import { Badge, State, Title, statusTone } from "../components/UI";
import { HashValue } from "../components/HashValue";
import { timestamp } from "../utils/display";
import type { BlockchainStatusResponse } from "../types/blockchain";
import type { AnchorPage, BlockDetail, IntegrityResult, LedgerPage, MonitorNode, NetworkOverview, NodeState, TransactionDetail } from "../types/monitor";

const BASE = "/admin/blockchain";
function Scroll({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
function Health({ status, name }: { status: NodeState; name: string }) {
  return <span className={`health-status status-${statusTone(status)}`} aria-label={`${name}: ${status}`}>
    <span className="status-dot" aria-hidden="true" />{status}
  </span>;
}
function PeerCard({ peer }: { peer: MonitorNode }) {
  return <article className={`card peer-card health-${statusTone(peer.status)}`} aria-label={peer.name}>
    <header className="node-heading"><div><h3>{peer.name}</h3><p>{peer.msp}</p></div><Health name={peer.name} status={peer.status} /></header>
    <dl className="node-facts">
      <div><dt>Ledger height</dt><dd>{peer.height ?? "Unknown"}</dd></div>
      <div><dt>Channel member</dt><dd>{peer.channel_member === null ? "Unknown" : peer.channel_member ? "Yes" : "No"}</dd></div>
    </dl>
    <details className="node-details"><summary>Observation details & hashes</summary>
      <p>Last check: {timestamp(peer.checked_at)}<br />Last success: {timestamp(peer.last_success_at)}</p>
      <p>Current block</p><HashValue value={peer.current_block_hash} label={`${peer.name} current block hash`} />
      <p>Previous block</p><HashValue value={peer.previous_block_hash} label={`${peer.name} previous block hash`} />
    </details>
  </article>;
}
function Network() {
  const network = useResource<NetworkOverview>(`${BASE}/overview`);
  const queue = useResource<BlockchainStatusResponse>(`${BASE}/queue`);
  const n = network.data;
  return <>
    <div className="section-heading monitor-refresh"><p className="muted">{n ? `Observed ${timestamp(n.checked_at)}` : "Current Fabric observations"}</p><button onClick={() => { network.reload(); queue.reload(); }}>Refresh network and queue</button></div>
    <State loading={network.loading} error={network.error} />
    {n && <>
      <section aria-label="Fabric network overview" className="monitor-summary card-grid">
        <article className="card"><h2>Network health</h2><Health name="Network" status={n.status} /></article>
        <article className="card"><h2>Peers online</h2><strong>{n.nodes.filter(p => p.status === "ONLINE").length} / {n.nodes.length}</strong><small>Online peers</small></article>
        <article className="card"><h2>Ledger height</h2><strong>{n.ledger_height ?? "Unknown"}</strong><small>Highest observed block count</small></article>
        <article className="card"><h2>Orderer</h2><Health name="Orderer summary" status={n.orderer.status} /></article>
        <article className="card"><h2>Chaincode</h2><p className="chaincode-summary">{n.chaincode ? <>{n.chaincode.name}<small>Version {n.chaincode.version}</small></> : "Unavailable"}</p></article>
      </section>
      <section aria-label="Fabric nodes" className="peer-section">
        <div className="section-heading"><h2>Peer health</h2><span className="muted">Channel: {n.channel}</span></div>
        <p className="muted">Successful channel queries confirm membership. Unknown is not offline.</p>
        <div className="peer-grid">{n.nodes.map(peer => <PeerCard key={peer.name} peer={peer} />)}</div>
        {n.nodes.length === 0 && <p className="empty-state">No peer observations available.</p>}
      </section>
      <section className={`card orderer-card health-${statusTone(n.orderer.status)}`} aria-label="Orderer health">
        <header className="node-heading"><div><h2>Orderer</h2><p>{n.orderer.name}</p></div><Health name={n.orderer.name} status={n.orderer.status} /></header>
        <p>Health signal: <strong>{n.orderer.signal}</strong></p>
        <p className="muted">This observation does not prove ordering consensus or write availability.</p>
      </section>
      <section className="card"><h2>Channel & committed chaincode</h2><p>Channel: <strong>{n.channel}</strong></p>
        {n.chaincode ? <dl className="monitor-facts"><div><dt>Name</dt><dd>{n.chaincode.name}</dd></div><div><dt>Version</dt><dd>{n.chaincode.version}</dd></div><div><dt>Sequence</dt><dd>{n.chaincode.sequence}</dd></div><div><dt>Endorsement policy</dt><dd>{n.chaincode.endorsement_policy}</dd></div></dl> : <p>Committed definition unavailable. A configured name is not proof of a committed chaincode.</p>}
      </section>
    </>}
    <section className="card" aria-label="Application outbox status"><h2>Application outbox status</h2>
      <p>MySQL delivery records, separate from Fabric ledger confirmation. Worker activity does not establish network health.</p>
      <State loading={queue.loading} error={queue.error} />
      {queue.data && <><div className="monitor-cards">{Object.entries(queue.data.counts).map(([key, count]) => <div key={key}><h3>{key.charAt(0).toUpperCase() + key.slice(1)} anchors</h3><strong>{count}</strong></div>)}</div><p>Worker activity: <Badge>{queue.data.worker_health}</Badge></p><p>FAILED means a retry is scheduled; DEAD requires review.</p></>}
    </section>
  </>;
}
function Ledger() {
  const [before, setBefore] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [numberInput, setNumberInput] = useState("");
  const [txInput, setTxInput] = useState("");
  const [txId, setTxId] = useState<string | null>(null);
  const blocks = useResource<LedgerPage>(`${BASE}/blocks?limit=10${before === null ? "" : `&before=${before}`}`);
  const block = useResource<BlockDetail>(selected === null ? null : `${BASE}/blocks/${selected}`);
  const tx = useResource<TransactionDetail>(txId ? `${BASE}/transactions/${txId}` : null);
  return <>
    <section className="card"><h2>Fabric ledger</h2><p>Committed block metadata from peer1. Timestamps come from transaction proposals, not a trusted commit clock.</p>
      <form className="monitor-filters" onSubmit={e => { e.preventDefault(); setSelected(Number(numberInput)); }}><label>Block number<input type="number" min="0" max="9007199254740991" required value={numberInput} onChange={e => setNumberInput(e.target.value)} /></label><button>Find block</button></form>
      <State loading={blocks.loading} error={blocks.error} empty={blocks.data?.items.length === 0} />
      {blocks.data && <Scroll label="Recent blocks"><table><caption className="sr-only">Recent blocks</caption><thead><tr>{["Block", "Transactions", "Hash", "Previous hash", "Time"].map(x => <th scope="col" key={x}>{x}</th>)}</tr></thead><tbody>{blocks.data.items.map(b => <tr key={b.number}><th scope="row"><button onClick={() => setSelected(b.number)}>Block {b.number}</button></th><td>{b.transaction_count}</td><td><HashValue value={b.block_hash} /></td><td><HashValue value={b.previous_block_hash} label="previous hash" /></td><td>{timestamp(b.timestamp)}</td></tr>)}</tbody></table></Scroll>}
      <div className="actions"><button onClick={() => { setBefore(null); blocks.reload(); }}>Latest blocks</button><button disabled={blocks.loading || blocks.data?.next_before == null} onClick={() => setBefore(blocks.data!.next_before)}>Older blocks</button></div>
    </section>
    {selected !== null && <section className="card" aria-label="Block detail"><h2>Block {selected} detail</h2><State loading={block.loading} error={block.error} />{block.data && <><HashValue value={block.data.block_hash} label="block hash" /><HashValue value={block.data.previous_block_hash} label="previous block hash" /><h3>Transactions</h3>{block.data.transactions.length === 0 && <p>No transactions.</p>}<ul className="monitor-transactions">{block.data.transactions.map((t, i) => <li key={t.transaction_id ?? i}><HashValue value={t.transaction_id} label="transaction ID" /><Badge>{t.validation_status}</Badge><span>Code: {t.validation_code ?? "Unknown"} · {timestamp(t.timestamp)}</span>{t.transaction_id && <button onClick={() => { setTxInput(t.transaction_id!); setTxId(t.transaction_id); }}>View transaction</button>}</li>)}</ul></>}</section>}
    <section className="card"><h2>Transaction lookup</h2><form className="monitor-filters" onSubmit={e => { e.preventDefault(); setTxId(txInput); tx.reload(); }}><label>Transaction ID<input required pattern="[0-9a-f]{64}" maxLength={64} value={txInput} onChange={e => setTxInput(e.target.value.trim())} /></label><button>Find transaction</button></form><State loading={tx.loading} error={tx.error} />{tx.data && <div aria-label="Transaction detail"><p>Fabric validation: <Badge>{tx.data.validation_status}</Badge> · Code {tx.data.validation_code ?? "Unknown"} · Block {tx.data.block_number}</p><HashValue value={tx.data.transaction_id} label="transaction ID" /><HashValue value={tx.data.block_hash} label="block hash" /><p>Observed on {tx.data.source_peer} at {timestamp(tx.data.checked_at)}</p></div>}</section>
  </>;
}
function Anchors() {
  const [filter, setFilter] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const anchors = useResource<AnchorPage>(`${BASE}/anchors?limit=20${filter}${before === null ? "" : `&before=${before}`}`);
  function apply(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const params = new URLSearchParams();
    new FormData(e.currentTarget).forEach((v, k) => { if (String(v).trim()) params.set(k, String(v).trim()); });
    setFilter(`&${params}`); setBefore(null); anchors.reload();
  }
  return <section className="card"><h2>Anchoring events</h2><p>Application outbox status records delivery attempts. CONFIRMED here is a stored receipt; use the ledger to inspect current Fabric evidence.</p>
    <form className="monitor-filters" onSubmit={apply}>
      <label>Status<select name="status"><option value="">All statuses</option>{["PENDING", "PROCESSING", "CONFIRMED", "FAILED", "DEAD"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Event type<select name="event_type"><option value="">All events</option>{["REPORT_RELEASED", "REPORT_REVOKED", "REPORT_SUPERSEDED"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Block number<input name="block_number" type="number" min="0" max="9007199254740991" /></label>
      <label>Transaction ID<input name="transaction_id" pattern="[0-9a-f]{64}" maxLength={64} /></label>
      <label>Entity reference<input name="entity_reference" pattern="[0-9a-fA-F-]{36}" maxLength={36} /></label><button>Apply filters</button>
    </form>
    <State loading={anchors.loading} error={anchors.error} empty={anchors.data?.items.length === 0} />
    {anchors.data && <Scroll label="Anchoring events"><table><caption className="sr-only">Application anchoring events</caption><thead><tr>{["Event", "Entity", "Outbox status", "Transaction / block", "Time", "Details"].map(s => <th key={s} scope="col">{s}</th>)}</tr></thead><tbody>{anchors.data.items.map(a => <tr key={a.event_id}><th scope="row">{a.event_type}</th><td><HashValue value={a.entity_reference} label="entity reference" /></td><td><Badge>{a.status}</Badge></td><td><HashValue value={a.transaction_id} label="transaction ID" />Block {a.block_number ?? "—"}</td><td>{timestamp(a.occurred_at)}</td><td><details><summary>Anchor details</summary><p>Confirmed: {timestamp(a.confirmed_at)}</p><HashValue value={a.record_hash} label="record hash" /><HashValue value={a.previous_hash} label="previous hash" /><HashValue value={a.event_uuid} label="event reference" /></details></td></tr>)}</tbody></table></Scroll>}
    <div className="actions"><button onClick={() => { setBefore(null); anchors.reload(); }}>Latest events</button><button disabled={anchors.loading || anchors.data?.next_before == null} onClick={() => setBefore(anchors.data!.next_before)}>Older events</button></div>
  </section>;
}
function Integrity() {
  const [input, setInput] = useState(""); const [id, setId] = useState<string | null>(null);
  const result = useResource<IntegrityResult>(id ? `${BASE}/reports/${id}/integrity` : null);
  return <section className="card"><h2>Report integrity</h2><p>Read-only comparison of the released PDF, stored verification hash, immutable event and live Fabric evidence. No report content is returned.</p>
    <form className="monitor-filters" onSubmit={e => { e.preventDefault(); setId(input); result.reload(); }}><label>Report ID<input type="number" required min="1" value={input} onChange={e => setInput(e.target.value)} /></label><button>Verify integrity</button></form>
    <State loading={result.loading} error={result.error} />{result.data && <div role="status" className={`integrity-result health-${statusTone(result.data.status)}`}><h3 className="integrity-heading">
      {result.data.status === "VERIFIED" ? <CheckCircle2 aria-hidden="true" /> : result.data.status === "MISMATCH" ? <XCircle aria-hidden="true" /> : <CircleHelp aria-hidden="true" />}
      <Badge>{result.data.status}</Badge><span>{result.data.status === "VERIFIED" ? "Verified / Match" : result.data.status === "MISMATCH" ? "Mismatch" : "Unable to verify"}</span></h3><p>Checked {timestamp(result.data.checked_at)}. VERIFIED describes artifact integrity, not clinical accuracy.</p>{result.data.status === "UNKNOWN" && <p>Evidence is unavailable or incomplete; integrity could not be established.</p>}<dl className="monitor-facts">{[["PDF SHA-256", result.data.artifact_sha256], ["Stored report hash", result.data.report_hash], ["Event record hash", result.data.record_hash], ["Ledger content hash", result.data.ledger_content_hash]].map(([label, value]) => <div key={label!}><dt>{label}</dt><dd><HashValue value={value} label={label!} /></dd></div>)}</dl></div>}
  </section>;
}
function MonitorContent() {
  const { can } = useAuth(); const [view, setView] = useState("Network");
  const views = ["Network", "Ledger", "Anchors", ...(can("BLOCKCHAIN_INTEGRITY_VERIFY") ? ["Integrity"] : [])];
  return <div className="blockchain-monitor page-shell"><Title title="Blockchain Monitor" eyebrow="ADMINISTRATION"
    description="Monitor Fabric network health, ledger activity, report anchors, and integrity." />
    <aside className="monitor-note"><Info size={20} aria-hidden="true" /><div><strong>Single-host Fabric deployment</strong><p>Four Fabric peers across two organizations share one VPS and a single-host fault domain. Ledger replication does not provide physical infrastructure decentralization.</p></div></aside>
    <Tabs label="Monitor sections" items={views} value={view} onChange={setView}>
      {view === "Network" && <Network />}{view === "Ledger" && <Ledger />}{view === "Anchors" && <Anchors />}{view === "Integrity" && can("BLOCKCHAIN_INTEGRITY_VERIFY") && <Integrity />}
    </Tabs>
  </div>;
}
export function BlockchainMonitor() {
  return <PermissionGuard permission="BLOCKCHAIN_EXPLORER_VIEW"><MonitorContent /></PermissionGuard>;
}
