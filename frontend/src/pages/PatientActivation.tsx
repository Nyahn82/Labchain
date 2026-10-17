import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useResource } from "../api/useResource";
import { useAuth } from "../auth/Auth";
import { Dialog, State } from "../components/UI";
import { timestamp } from "../utils/display";

export const activationLabels: Record<string, string> = {
  NOT_ACTIVATED: "No portal account",
  TOKEN_ACTIVE: "Awaiting activation",
  TOKEN_EXPIRED: "Invitation expired",
  TOKEN_REVOKED: "Invitation revoked",
  ACTIVATED: "Portal activated",
  REVIEW_REQUIRED: "Account review required",
};
export const activationLabel = (value: unknown) => activationLabels[String(value)] || "Status unavailable";
const descriptions: Record<string, string> = {
  NOT_ACTIVATED: "No portal account or invitation is recorded. Verify the patient's identity before issuing an invitation.",
  TOKEN_ACTIVE: "An invitation is available for this patient to activate their portal account. Reissuing invalidates the previous unused invitation.",
  TOKEN_EXPIRED: "The unused invitation has expired. Verify the patient's identity and issue a new invitation.",
  TOKEN_REVOKED: "The latest invitation was revoked and cannot be used. A new invitation can be issued after identity verification.",
  ACTIVATED: "A portal account is linked. Activation does not override account suspension, permissions or MFA requirements. Use account administration for access issues.",
  REVIEW_REQUIRED: "A consumed invitation exists without an account link. Ask an administrator to review the account history; another invitation cannot be issued.",
};
type Issued = { activation_token: string; expires_at: string; patient_code: string };

export function PatientActivation({ id }: { id: string }) {
  const { can } = useAuth();
  const state = useResource<{ status: string }>(`/patients/${id}/activation-status`);
  const [open, setOpen] = useState(false);
  const status = state.data?.status;
  const issuable = status && ["NOT_ACTIVATED", "TOKEN_ACTIVE", "TOKEN_EXPIRED", "TOKEN_REVOKED"].includes(status);
  return <section className="card" aria-labelledby="patient-activation-heading">
    <div className="section-heading">
      <h2 id="patient-activation-heading">Patient activation</h2>
      <button onClick={state.reload} disabled={state.loading}>Refresh activation status</button>
    </div>
    <State loading={state.loading} error={state.error} />
    {!state.loading && !state.error && <>
      <p role="status"><strong>{activationLabel(status)}</strong></p>
      {status && <p>{descriptions[status] || "Refresh to retrieve the current activation state."}</p>}
      {can("PATIENT_ACCOUNT_ACTIVATE") && issuable && <button className="primary" onClick={() => setOpen(true)}>
        {status === "NOT_ACTIVATED" ? "Issue activation invitation" : "Reissue activation invitation"}
      </button>}
    </>}
    {open && can("PATIENT_ACCOUNT_ACTIVATE") && <Invitation id={id} reissue={status !== "NOT_ACTIVATED"}
      onClose={() => { setOpen(false); state.reload(); }} onIssued={state.reload} />}
  </section>;
}

function Invitation({ id, reissue, onClose, onIssued }: {
  id: string; reissue: boolean; onClose: () => void; onIssued: () => void;
}) {
  const [issued, setIssued] = useState<Issued>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(new AbortController());
  useEffect(() => {
    const active = new AbortController();
    controller.current = active;
    return () => active.abort();
  }, []);
  useEffect(() => {
    // A hidden tab must not retain a visible activation credential on return.
    const hidden = () => { if (document.visibilityState === "hidden") onClose(); };
    document.addEventListener("visibilitychange", hidden);
    return () => document.removeEventListener("visibilitychange", hidden);
  }, [onClose]);
  async function issue() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Issued>(`/patients/${id}/activation-token`, { method: "POST", signal: controller.current.signal });
      if (!controller.current.signal.aborted) {
        setIssued(result);
        onIssued();
      }
    } catch (e) {
      if (!controller.current.signal.aborted) setError(e instanceof ApiError && e.status === 409
        ? "The patient's activation state has changed or needs administrator review. Close this dialog to refresh the status."
        : e instanceof ApiError && e.status === 403
          ? "You do not have permission to issue invitations. Ask an authorized staff member."
          : "Invitation could not be confirmed. Close and refresh the status before retrying; an invitation may already have been issued.");
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return <Dialog title={issued ? "Activation invitation issued" : "Confirm activation invitation"} onClose={onClose}>
    {issued ? <>
      <p role="status">Invitation issued for patient {issued.patient_code}.</p>
      <p>Share this token only with the verified patient through your approved secure process. No email or SMS has been sent.</p>
      <label>One-time activation token<input readOnly autoComplete="off" value={issued.activation_token} /></label>
      <p>Expires: {timestamp(issued.expires_at)}. The token is shown only in this dialog and cannot be retrieved later.</p>
      <p>The patient can enter it on the <Link to="/patient/activate" target="_blank" rel="noopener noreferrer">patient activation page</Link>.</p>
      <button onClick={onClose}>Done — hide token</button>
    </> : <>
      <p>Confirm the patient's identity before continuing. {reissue && "Any previous unused invitation will stop working."}</p>
      <p>This issues a single-use token for secure manual delivery; it does not send email or SMS.</p>
      {error && <p role="alert">{error}</p>}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !!error} onClick={() => void issue()}>{busy ? "Issuing invitation…" : "Confirm issue invitation"}</button></div>
    </>}
  </Dialog>;
}
